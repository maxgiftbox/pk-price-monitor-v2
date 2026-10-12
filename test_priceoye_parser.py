import unittest

from scraper import (
    extract_priceoye_variant_from_product_data,
    parse_memory_to_ram_storage,
    priceoye_memory_matches,
    priceoye_product_title_matches,
)


class PriceOyeParserTests(unittest.TestCase):
    def test_memory_parser_supports_storage_only_and_tb(self):
        self.assertEqual(parse_memory_to_ram_storage("256GB"), (None, "256"))
        self.assertEqual(parse_memory_to_ram_storage("1TB"), (None, "1024"))
        self.assertEqual(parse_memory_to_ram_storage("12/1TB"), ("12", "1024"))
        self.assertEqual(parse_memory_to_ram_storage("256GB - 8GB RAM"), ("8", "256"))

    def test_storage_only_apple_variant_matches_requested_sku(self):
        self.assertTrue(priceoye_memory_matches("12/1TB", "1TB"))
        self.assertTrue(priceoye_memory_matches("8/256", "256GB"))
        self.assertFalse(priceoye_memory_matches("8/512", "256GB"))

    def test_android_variant_requires_both_ram_and_storage(self):
        self.assertTrue(priceoye_memory_matches("4/128", "128GB - 4GB RAM"))
        self.assertFalse(priceoye_memory_matches("6/128", "128GB - 4GB RAM"))

    def test_product_title_validation_allows_network_suffix_but_rejects_wrong_model(self):
        self.assertTrue(
            priceoye_product_title_matches("Samsung Galaxy A57 5G", "Samsung Galaxy A57")
        )
        self.assertFalse(
            priceoye_product_title_matches("Samsung Galaxy A57 5G", "Samsung Galaxy S26+")
        )

    def test_catalog_extracts_exact_android_variant(self):
        product_data = {
            "product_config": {
                "selectedColor": "black",
                "dataPrices": {
                    "black": {
                        "64gb - 4gb ram": [
                            {
                                "product_price": "37,295",
                                "retail_price": "45,999",
                                "product_availability": "In Stock",
                                "stock_qty": 10,
                                "product_size": "64gb - 4gb ram",
                            }
                        ],
                        "128gb - 6gb ram": [
                            {
                                "product_price": "56,195",
                                "retail_price": "68,500",
                                "product_availability": "In Stock",
                                "stock_qty": 2,
                                "product_size": "128gb - 6gb ram",
                            }
                        ],
                    }
                },
            }
        }
        result = extract_priceoye_variant_from_product_data(product_data, "6/128")
        self.assertEqual(result["product_price"], "56195")
        self.assertEqual(result["original_price"], "68500")
        self.assertEqual(result["stock_status"], "active")

    def test_catalog_extracts_storage_only_apple_variant(self):
        product_data = {
            "product_config": {
                "selectedColor": "natural",
                "dataPrices": {
                    "natural": {
                        "256gb": [
                            {
                                "product_price": "473,999",
                                "retail_price": "491,100",
                                "product_availability": "In Stock",
                                "stock_qty": 3,
                                "product_size": "256gb",
                            }
                        ],
                        "1tb": [
                            {
                                "product_price": "662,999",
                                "retail_price": "657,100",
                                "product_availability": "Sold Out",
                                "stock_qty": 0,
                                "product_size": "1tb",
                            }
                        ],
                    }
                },
            }
        }
        result = extract_priceoye_variant_from_product_data(product_data, "12/1TB")
        self.assertEqual(result["product_price"], "662999")
        self.assertEqual(result["original_price"], "662999")
        self.assertEqual(result["stock_status"], "out_of_stock")

    def test_missing_variant_returns_no_default_price(self):
        product_data = {
            "product_config": {
                "dataPrices": {
                    "black": {
                        "256gb": [{"product_price": "100,000", "retail_price": "110,000"}]
                    }
                }
            }
        }
        self.assertEqual(extract_priceoye_variant_from_product_data(product_data, "8/512"), {})


if __name__ == "__main__":
    unittest.main()
