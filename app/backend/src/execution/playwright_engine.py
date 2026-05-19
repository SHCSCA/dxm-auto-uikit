class PlaywrightEngine:
    def describe(self) -> dict:
        return {
            "engine": "playwright",
            "mode": "skeleton",
            "capabilities": [
                "check_login",
                "open_create_product_page",
                "fill_title",
                "fill_category",
                "upload_images",
                "fill_sku_price",
                "select_shipping_template",
                "save_draft",
            ],
        }
