import unittest

from availability_crawler import (
    build_row,
    classify_availability,
    classify_purchase_signals,
    crawl_daraz_availability,
    extract_memory,
    inspect_purchase_controls,
)


class AvailabilityCrawlerTests(unittest.TestCase):
    def test_extract_memory_uses_last_capacity_token(self):
        self.assertEqual(extract_memory("Phone 12GB + 256GB"), "256GB")
        self.assertEqual(extract_memory("Laptop 1 TB"), "1TB")
        self.assertEqual(extract_memory("Charger"), "")

    def test_classification_keeps_failures_unknown(self):
        self.assertEqual(classify_availability({"stock_status": "active"})[0], "available")
        self.assertEqual(classify_availability({"stock_status": "out_of_stock"})[0], "unavailable")
        self.assertEqual(classify_availability({"error_message": "Daraz PDP unavailable / 404"})[0], "unavailable")
        self.assertEqual(classify_availability({"error_message": "CAPTCHA detected"})[0], "unknown")

    def test_purchase_controls_define_availability_without_price(self):
        self.assertEqual(
            classify_purchase_signals({"purchase_action_enabled": True}),
            ("active", "purchase_action_enabled"),
        )
        self.assertEqual(
            classify_purchase_signals({
                "purchase_action_enabled": False,
                "wishlist_visible": True,
                "out_of_stock_visible": True,
            }),
            ("out_of_stock", "out_of_stock_visible"),
        )
        self.assertEqual(
            classify_purchase_signals({
                "purchase_action_enabled": False,
                "wishlist_visible": True,
            }),
            ("out_of_stock", "wishlist_only"),
        )
        self.assertEqual(
            classify_purchase_signals({
                "purchase_action_enabled": False,
                "purchase_action_visible": True,
            }),
            ("out_of_stock", "purchase_action_disabled"),
        )

    def test_wishlist_does_not_stop_waiting_for_late_purchase_actions(self):
        class FakeResponse:
            status = 200

        class FakeLocator:
            def inner_text(self, timeout=None):
                return "Product detail"

        class FakePage:
            url = "https://daraz.pk/i100-s999.html"

            def __init__(self):
                self.signals = [
                    {
                        "purchase_action_visible": False,
                        "purchase_action_enabled": False,
                        "wishlist_visible": True,
                        "out_of_stock_visible": False,
                    },
                    {
                        "purchase_action_visible": True,
                        "purchase_action_enabled": True,
                        "wishlist_visible": True,
                        "out_of_stock_visible": False,
                    },
                ]
                self.evaluate_calls = 0

            def goto(self, *args, **kwargs):
                return FakeResponse()

            def wait_for_timeout(self, _milliseconds):
                return None

            def locator(self, _selector):
                return FakeLocator()

            def title(self):
                return "Product"

            def evaluate(self, _script):
                value = self.signals[min(self.evaluate_calls, len(self.signals) - 1)]
                self.evaluate_calls += 1
                return value

            def close(self):
                return None

        class FakeContext:
            def __init__(self):
                self.page = FakePage()

            def new_page(self):
                return self.page

        context = FakeContext()
        result, _ = crawl_daraz_availability(
            context,
            "https://daraz.pk/i100-s999.html",
            {},
        )
        self.assertEqual(result["stock_status"], "active")
        self.assertEqual(context.page.evaluate_calls, 2)

    def test_purchase_inspection_is_scoped_to_current_pdp(self):
        class ScriptCapturingPage:
            def __init__(self):
                self.script = ""

            def evaluate(self, script):
                self.script = script
                return {}

        page = ScriptCapturingPage()
        inspect_purchase_controls(page)
        self.assertIn("const scope = document.querySelector", page.script)
        self.assertIn("scope.querySelectorAll", page.script)
        self.assertIn("const body = normalize(scope.innerText)", page.script)

    def test_available_variant_must_match_final_url(self):
        source = {
            "venture": "PK", "brand_name": "Apple", "product_id": "100",
            "daraz_sku": "100_PK-999", "short_item_eng_name": "Phone 256GB",
            "color": "Blue", "Category": "Mobile", "url_daraz": "https://daraz.pk/i100-s999.html",
            "L90 Product Transaction Flag": "Yes",
        }
        verified = build_row(source, {"stock_status": "active", "final_url": "https://daraz.pk/i100-s999.html"}, "run", "now")
        redirected = build_row(source, {"stock_status": "active", "final_url": "https://daraz.pk/i100-s888.html"}, "run", "now")
        self.assertEqual(verified["availability_status"], "available")
        self.assertTrue(verified["selected_sku_verified"])
        self.assertEqual(redirected["availability_status"], "unknown")
        self.assertEqual(redirected["status_reason"], "variant_not_verified")


if __name__ == "__main__":
    unittest.main()
