class PlaywrightEngine:
    def describe(self) -> dict:
        return {
            "engine": "playwright",
            "mode": "skeleton",
            "capabilities": [
                "probe",
                "dry_run",
                "single_save",
                "batch_save",
                "check_login",
                "open_smt_draft_list",
                "verify_ownership",
                "fill_base_info",
                "fill_variants",
                "fill_media",
                "fill_compliance",
                "enable_semi_managed",
                "fill_semi_managed",
                "publish_guard_check",
                "upload_images",
                "save_only",
                "verify_not_published",
                "write_report",
            ],
        }
