import unittest

from availability_crawler import (
    build_row,
    classify_availability,
    classify_purchase_signals,
    classify_sku_info,
    extract_memory,
    group_source_rows,
    inspect_purchase_controls,
    product_results_from_payload,
    resolve_single_sku_result,
    result_requires_fallback,
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

    def test_groups_source_rows_by_country_and_product(self):
        rows = [
            {"venture": "PK", "product_id": "1", "daraz_sku": "1_PK-10"},
            {"venture": "PK", "product_id": "1", "daraz_sku": "1_PK-11"},
            {"venture": "BD", "product_id": "1", "daraz_sku": "1_BD-20"},
        ]
        groups = group_source_rows(rows)
        self.assertEqual([len(group) for group in groups], [2, 1])

    def test_classifies_quantity_and_wishlist_states(self):
        self.assertEqual(
            classify_sku_info({"quantity": {"limit": {"max": 5}}, "operation": {"type": "default"}}),
            ("active", "sku_quantity_available"),
        )
        self.assertEqual(
            classify_sku_info({"quantity": {"limit": {"max": 0}, "text": "Out of stock"}}),
            ("out_of_stock", "sku_quantity_unavailable"),
        )
        self.assertEqual(
            classify_sku_info({"operation": {"type": "wishlist", "text": "Add to Wishlist"}}),
            ("out_of_stock", "sku_wishlist_only"),
        )

    def test_maps_all_product_variants_and_cross_checks_primary_dom(self):
        payload = {
            "primarySkuId": "10",
            "loadedSkuIds": ["10", "11"],
            "skuInfos": {
                "10": {"quantity": {"limit": {"max": 5}}, "operation": {"type": "default"}},
                "11": {"quantity": {"limit": {"max": 0}, "text": "Out of stock"}},
            },
        }
        signals = {
            "purchase_action_enabled": True,
            "purchase_action_visible": True,
            "wishlist_visible": False,
            "out_of_stock_visible": False,
            "purchase_action_labels": ["buy now", "add to cart"],
        }
        results = product_results_from_payload(payload, signals, "https://daraz/i1-s10.html")
        self.assertEqual(results["10"]["stock_status"], "active")
        self.assertEqual(results["11"]["stock_status"], "out_of_stock")
        self.assertEqual(results["11"]["verified_sku_id"], "11")
        self.assertTrue(result_requires_fallback(results["11"]))

    def test_loaded_available_sibling_does_not_require_fallback(self):
        payload = {
            "primarySkuId": "10",
            "loadedSkuIds": ["10", "11"],
            "skuInfos": {
                "10": {"quantity": {"limit": {"max": 5}}, "operation": {"type": "default"}},
                "11": {"quantity": {"limit": {"max": 2}}, "operation": {"type": "default"}},
            },
        }
        signals = {
            "purchase_action_enabled": True,
            "purchase_action_visible": True,
            "wishlist_visible": False,
            "out_of_stock_visible": False,
            "purchase_action_labels": ["buy now", "add to cart"],
        }
        results = product_results_from_payload(payload, signals, "https://daraz/i1-s10.html")
        self.assertEqual(results["11"]["stock_status"], "active")
        self.assertFalse(result_requires_fallback(results["11"]))

    def test_primary_quantity_unavailable_without_dom_confirmation_requires_fallback(self):
        payload = {
            "primarySkuId": "10",
            "loadedSkuIds": ["10"],
            "skuInfos": {
                "10": {"quantity": {"limit": {"max": 0}, "text": "Out of stock"}},
            },
        }
        result = product_results_from_payload(
            payload,
            {},
            "https://daraz/i1-s10.html",
        )["10"]
        self.assertEqual(result["stock_status"], "out_of_stock")
        self.assertEqual(result["availability_signal"], "sku_quantity_unavailable")
        self.assertTrue(result_requires_fallback(result))

    def test_primary_dom_can_confirm_quantity_unavailable(self):
        payload = {
            "primarySkuId": "10",
            "loadedSkuIds": ["10"],
            "skuInfos": {
                "10": {"quantity": {"limit": {"max": 0}, "text": "Out of stock"}},
            },
        }
        signals = {
            "purchase_action_enabled": False,
            "purchase_action_visible": False,
            "wishlist_visible": True,
            "out_of_stock_visible": True,
            "purchase_action_labels": [],
        }
        result = product_results_from_payload(payload, signals, "https://daraz/i1-s10.html")["10"]
        self.assertEqual(result["stock_status"], "out_of_stock")
        self.assertEqual(result["availability_signal"], "out_of_stock_visible")
        self.assertFalse(result_requires_fallback(result))

    def test_marks_primary_conflict_unknown(self):
        payload = {
            "primarySkuId": "10",
            "loadedSkuIds": ["10"],
            "skuInfos": {
                "10": {"quantity": {"limit": {"max": 5}}, "operation": {"type": "default"}},
            },
        }
        signals = {
            "purchase_action_enabled": False,
            "purchase_action_visible": False,
            "wishlist_visible": True,
            "out_of_stock_visible": True,
            "purchase_action_labels": [],
        }
        result = product_results_from_payload(payload, signals, "https://daraz/i1-s10.html")["10"]
        self.assertEqual(result["stock_status"], "unknown")
        self.assertTrue(result["availability_signal"].startswith("state_conflict:"))
        self.assertTrue(result_requires_fallback(result))

    def test_unloaded_sibling_requires_single_sku_fallback(self):
        payload = {
            "primarySkuId": "10",
            "loadedSkuIds": ["10"],
            "skuInfos": {
                "10": {"quantity": {"limit": {"max": 5}}, "operation": {"type": "default"}},
                "11": {"quantity": {"limit": {"max": 0}, "text": "Out of stock"}},
            },
        }
        signals = {
            "purchase_action_enabled": True,
            "purchase_action_visible": True,
            "wishlist_visible": False,
            "out_of_stock_visible": False,
            "purchase_action_labels": ["buy now", "add to cart"],
        }
        results = product_results_from_payload(payload, signals, "https://daraz/i1-s10.html")
        self.assertEqual(results["10"]["stock_status"], "active")
        self.assertFalse(result_requires_fallback(results["10"]))
        self.assertEqual(results["11"]["stock_status"], "unknown")
        self.assertEqual(results["11"]["availability_signal"], "sku_not_loaded")
        self.assertTrue(result_requires_fallback(results["11"]))

    def test_unknown_classification_preserves_specific_signal(self):
        self.assertEqual(
            classify_availability({
                "stock_status": "unknown",
                "availability_signal": "sku_state_not_found",
            }),
            ("unknown", "sku_state_not_found"),
        )

    def test_single_sku_fallback_uses_visible_purchase_controls_without_payload(self):
        result = resolve_single_sku_result(None, {
            "purchase_action_enabled": True,
            "purchase_action_visible": True,
            "wishlist_visible": False,
            "out_of_stock_visible": False,
            "purchase_action_labels": ["buy now", "add to cart"],
        }, "https://daraz/i1-s11.html")
        self.assertEqual(result["stock_status"], "active")
        self.assertEqual(result["availability_signal"], "purchase_action_enabled")
        self.assertFalse(result_requires_fallback(result))

    def test_single_sku_fallback_preserves_unknown_reason(self):
        result = resolve_single_sku_result({
            "stock_status": "unknown",
            "availability_signal": "state_conflict:quantity:dom",
            "requires_fallback": True,
        }, {}, "https://daraz/i1-s11.html")
        self.assertEqual(result["stock_status"], "unknown")
        self.assertEqual(result["availability_signal"], "state_conflict:quantity:dom")
        self.assertFalse(result_requires_fallback(result))

    def test_sibling_variant_is_verified_by_payload_sku(self):
        source = {
            "venture": "PK",
            "product_id": "1",
            "daraz_sku": "1_PK-11",
            "short_item_eng_name": "Phone 256GB",
            "url_daraz": "https://daraz/i1-s11.html",
        }
        result = {
            "stock_status": "out_of_stock",
            "final_url": "https://daraz/i1-s10.html",
            "verified_sku_id": "11",
        }
        row = build_row(source, result, "run", "now")
        self.assertEqual(row["availability_status"], "unavailable")
        self.assertTrue(row["selected_sku_verified"])

    def test_purchase_inspection_is_scoped_to_add_to_cart_module(self):
        class ScriptCapturingPage:
            def __init__(self):
                self.script = ""

            def evaluate(self, script):
                self.script = script
                return {}

        page = ScriptCapturingPage()
        inspect_purchase_controls(page)
        self.assertIn("document.querySelector('#module_add_to_cart')", page.script)
        self.assertIn("scope.querySelectorAll", page.script)
        self.assertIn("const body = normalize(scope.innerText)", page.script)

    def test_available_variant_must_match_final_url_without_payload_verification(self):
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
