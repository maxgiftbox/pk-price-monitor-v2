import unittest
from unittest.mock import MagicMock, patch

import gspread
import requests

from daraz_selfhosted import (
    CHECKPOINT_SIZE,
    PRICE_DAILY_COLUMNS,
    classify_result,
    crawl_daraz_with_retries,
    normalized_key,
    upsert_daraz_rows,
)
from scraper import GOOGLE_SHEETS_MAX_ATTEMPTS, google_sheets_retry, parse_daraz


class FakeWorksheet:
    def __init__(self, records):
        self.records = records
        self.updates = []
        self.appends = []

    def get_all_records(self):
        return self.records

    def update(self, cell_range, values, value_input_option=None):
        self.updates.append((cell_range, values, value_input_option))

    def append_row(self, values, value_input_option=None):
        self.appends.append((values, value_input_option))


def row(**overrides):
    value = {column: "" for column in PRICE_DAILY_COLUMNS}
    value.update({
        "crawl_date": "2026-08-23",
        "platform": "daraz",
        "country": "PK",
        "brand": "Example",
        "model": "Phone",
        "memory": "8/256",
        "product_price": 100,
    })
    value.update(overrides)
    return value


class DarazUpsertTests(unittest.TestCase):
    @patch("daraz_selfhosted.google_sheets_retry", side_effect=lambda operation, *args, **kwargs: operation(*args, **kwargs))
    def test_matching_daily_key_updates_instead_of_appending(self, _retry):
        worksheet = FakeWorksheet([row(product_price=90)])

        updated, appended = upsert_daraz_rows(worksheet, [row(product_price=100)])

        self.assertEqual((updated, appended), (1, 0))
        self.assertEqual(worksheet.updates[0][0], "A2:N2")
        self.assertEqual(worksheet.appends, [])

    @patch("daraz_selfhosted.google_sheets_retry", side_effect=lambda operation, *args, **kwargs: operation(*args, **kwargs))
    def test_new_key_appends_only_once_within_run(self, _retry):
        worksheet = FakeWorksheet([])
        new_row = row(country="BD")

        updated, appended = upsert_daraz_rows(worksheet, [new_row, new_row])

        self.assertEqual((updated, appended), (1, 1))
        self.assertEqual(len(worksheet.appends), 1)
        self.assertEqual(worksheet.updates[0][0], "A2:N2")

    def test_key_is_case_and_whitespace_insensitive(self):
        self.assertEqual(
            normalized_key(row(platform=" Daraz ", country="pk", brand="EXAMPLE")),
            normalized_key(row(platform="daraz", country="PK", brand="example")),
        )

    def test_checkpoint_size_remains_twenty(self):
        self.assertEqual(CHECKPOINT_SIZE, 20)

    def test_lost_append_response_does_not_duplicate_daily_key(self):
        class LostResponseWorksheet(FakeWorksheet):
            def append_row(self, values, value_input_option=None):
                self.records.append(dict(zip(PRICE_DAILY_COLUMNS, values)))
                self.appends.append((values, value_input_option))
                if len(self.appends) == 1:
                    raise requests.exceptions.ProxyError("response lost")

        worksheet = LostResponseWorksheet([])
        with patch("scraper.time.sleep"):
            updated, appended = upsert_daraz_rows(worksheet, [row(country="BD")])

        self.assertEqual((updated, appended), (0, 1))
        self.assertEqual(len(worksheet.appends), 1)
        self.assertEqual(len(worksheet.records), 1)


class GoogleSheetsRetryTests(unittest.TestCase):
    @patch("scraper.time.sleep")
    def test_transport_errors_retry_and_recover(self, sleep):
        for error in (
            requests.exceptions.ProxyError("proxy"),
            requests.exceptions.ConnectionError("connection reset"),
            requests.exceptions.Timeout("timed out"),
        ):
            with self.subTest(error=type(error).__name__):
                operation = MagicMock(side_effect=[error, "ok"])
                self.assertEqual(google_sheets_retry(operation), "ok")
                self.assertEqual(operation.call_count, 2)
        self.assertEqual(sleep.call_count, 3)

    @patch("scraper.time.sleep")
    def test_transport_error_is_raised_after_max_attempts(self, sleep):
        operation = MagicMock(
            side_effect=requests.exceptions.ConnectionError("connection closed")
        )

        with self.assertRaises(requests.exceptions.ConnectionError):
            google_sheets_retry(operation)

        self.assertEqual(operation.call_count, GOOGLE_SHEETS_MAX_ATTEMPTS)
        self.assertEqual(sleep.call_count, GOOGLE_SHEETS_MAX_ATTEMPTS - 1)

    @patch("scraper.random.uniform", return_value=0)
    @patch("scraper.time.sleep")
    def test_transient_api_error_retry_remains_intact(self, _sleep, _uniform):
        response = MagicMock()
        response.status_code = 503
        response.json.return_value = {
            "error": {"code": 503, "message": "unavailable", "status": "UNAVAILABLE"}
        }
        operation = MagicMock(side_effect=[gspread.exceptions.APIError(response), "ok"])

        self.assertEqual(google_sheets_retry(operation), "ok")
        self.assertEqual(operation.call_count, 2)


class DarazResilienceTests(unittest.TestCase):
    @patch("daraz_selfhosted.time.sleep")
    @patch("daraz_selfhosted.parse_daraz")
    def test_transient_network_failure_retries_at_most_three_times(self, parse, _sleep):
        parse.side_effect = [
            {"error_message": "Crawl failed: Page.goto: net::ERR_CONNECTION_RESET"},
            {"error_message": "Crawl failed: Page.goto: net::ERR_CONNECTION_RESET"},
            {"error_message": "Crawl failed: Page.goto: net::ERR_CONNECTION_RESET"},
        ]

        result, _ = crawl_daraz_with_retries(
            object(),
            "https://example.test",
            {"country": "PK", "model": "Phone"},
        )

        self.assertEqual(parse.call_count, 3)
        self.assertEqual(result["error_message"], "Network failure after 3 attempts")

    @patch("daraz_selfhosted.random.uniform", return_value=3)
    @patch("daraz_selfhosted.time.sleep")
    @patch("daraz_selfhosted.parse_daraz")
    def test_parse_failure_gets_only_one_fresh_retry(self, parse, _sleep, _uniform):
        parse.return_value = {"error_message": "Product price not parsed"}

        result, _ = crawl_daraz_with_retries(object(), "https://example.test", {})

        self.assertEqual(parse.call_count, 2)
        self.assertEqual(result["error_message"], "Product price not parsed")

    @patch("daraz_selfhosted.parse_daraz")
    def test_unavailable_and_captcha_are_not_retried(self, parse):
        for message, category in (
            ("Daraz PDP unavailable / 404", "unavailable"),
            ("CAPTCHA detected; crawl not bypassed", "captcha"),
        ):
            with self.subTest(message=message):
                parse.reset_mock()
                parse.return_value = {"error_message": message}
                result, _ = crawl_daraz_with_retries(object(), "https://example.test", {})
                self.assertEqual(parse.call_count, 1)
                self.assertEqual(classify_result(result), category)


class FakeDarazPage:
    def __init__(self, status=200, title="Product", body="Product details"):
        self.response = type("Response", (), {"status": status})()
        self._title = title
        self._body = body

    def goto(self, *_args, **_kwargs):
        return self.response

    def locator(self, _selector):
        return self

    def inner_text(self):
        return self._body

    def title(self):
        return self._title

    def close(self):
        pass


class FakeDarazContext:
    def __init__(self, page):
        self.page = page

    def new_page(self):
        return self.page


class DarazUnavailablePageTests(unittest.TestCase):
    @patch("scraper.extract_daraz_product_price")
    def test_http_404_returns_unavailable_without_parsing_prices(self, extract_price):
        result = parse_daraz(FakeDarazContext(FakeDarazPage(status=404)), "https://example.test")

        self.assertEqual(result["error_message"], "Daraz PDP unavailable / 404")
        self.assertEqual(result["product_price"], "")
        extract_price.assert_not_called()

    @patch("scraper.extract_daraz_product_price")
    def test_daraz_error_body_returns_unavailable_without_parsing_prices(self, extract_price):
        page = FakeDarazPage(body="We're Sorry, an error has occurred. Recommended ৳3,156")

        result = parse_daraz(FakeDarazContext(page), "https://example.test")

        self.assertEqual(result["error_message"], "Daraz PDP unavailable / 404")
        extract_price.assert_not_called()


if __name__ == "__main__":
    unittest.main()
