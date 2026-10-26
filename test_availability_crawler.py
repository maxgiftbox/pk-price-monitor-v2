import unittest

from availability_crawler import (
    build_row,
    classify_availability,
    classify_purchase_signals,
    extract_memory,
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
