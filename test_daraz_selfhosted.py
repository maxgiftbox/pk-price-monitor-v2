import unittest
from unittest.mock import patch

from daraz_selfhosted import PRICE_DAILY_COLUMNS, normalized_key, upsert_daraz_rows


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


if __name__ == "__main__":
    unittest.main()
