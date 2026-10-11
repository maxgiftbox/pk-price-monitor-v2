import unittest
from unittest.mock import MagicMock, patch

from scraper import crawl_pickaboo_page, extract_pickaboo_product_price


class FakeLocator:
    def __init__(self, text):
        self.text = text

    def inner_text(self):
        return self.text


class FakePage:
    def __init__(self, status=200, body="", candidates=None, title="Product"):
        self.response = type("Response", (), {"status": status})()
        self.body = body
        self.candidates = candidates or []
        self._title = title
        self.url = "https://www.pickaboo.com/product-detail/example"

    def set_default_navigation_timeout(self, _timeout):
        pass

    def set_default_timeout(self, _timeout):
        pass

    def goto(self, *_args, **_kwargs):
        return self.response

    def wait_for_timeout(self, _timeout):
        pass

    def locator(self, _selector):
        return FakeLocator(self.body)

    def evaluate(self, script):
        if "querySelectorAll('img')" in script:
            return []
        return self.candidates

    def title(self):
        return self._title

    def close(self):
        pass


class FakeContext:
    def __init__(self, page):
        self.page = page

    def new_page(self):
        return self.page


class PickabooCrawlerTests(unittest.TestCase):
    @patch("scraper.save_pickaboo_failure_artifacts")
    def test_http_403_is_reported_as_blocked(self, save_artifacts):
        page = FakePage(status=403, body="403 Forbidden")

        result = crawl_pickaboo_page(FakeContext(page), "https://example.test")

        self.assertEqual(result["error_message"], "Pickaboo HTTP 403 blocked")
        self.assertEqual(result["product_price"], "")
        save_artifacts.assert_called_once()

    def test_current_price_selector_is_preferred_even_with_discount_context(self):
        page = FakePage(
            candidates=[
                {
                    "text": "৳19,999",
                    "context": "৳19,999 ৳20,999 5% discount",
                    "isPrimary": True,
                }
            ]
        )

        self.assertEqual(extract_pickaboo_product_price(page, ""), 19999)

    @patch("scraper.extract_pickaboo_product_price")
    def test_out_of_stock_page_does_not_parse_addon_price(self, extract_price):
        page = FakePage(body="realme C85 Pro\nOut of Stock\nDevice Insurance\n৳280")

        result = crawl_pickaboo_page(FakeContext(page), "https://example.test")

        self.assertEqual(result["stock_status"], "out_of_stock")
        self.assertEqual(result["product_price"], "")
        self.assertEqual(result["error_message"], "Product out of stock")
        extract_price.assert_not_called()

    def test_active_product_uses_current_and_regular_prices(self):
        page = FakePage(body="Phone\n৳19,999\n৳20,999\nAdd to Cart")
        page.candidates = [
            {"text": "৳19,999", "context": "৳19,999 5% discount", "isPrimary": True}
        ]
        original_evaluate = page.evaluate

        def evaluate(script):
            if "del, s, .old-price, .regular-price" in script:
                return ["৳20,999"]
            return original_evaluate(script)

        page.evaluate = MagicMock(side_effect=evaluate)

        result = crawl_pickaboo_page(FakeContext(page), "https://example.test")

        self.assertEqual(result["product_price"], 19999)
        self.assertEqual(result["original_price"], 20999)
        self.assertEqual(result["effective_price"], 19999)
        self.assertEqual(result["stock_status"], "active")


if __name__ == "__main__":
    unittest.main()

