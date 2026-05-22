import pytest

from src.services.selector_profile import SelectorProfileService


def test_lists_default_profiles():
    service = SelectorProfileService()

    profiles = service.list_profiles()

    assert [profile["page_key"] for profile in profiles] == [
        "smt_draft_list",
        "smt_edit",
        "smt_semi_edit",
    ]
    assert service.get_profile("smt_edit")["semi_managed_button_text"] == "编辑半托管信息"
    assert service.get_profile("smt_semi_edit")["save_button_text"] == "保存"


def test_get_profile_rejects_unknown_key():
    service = SelectorProfileService()

    with pytest.raises(KeyError):
        service.get_profile("missing_page")


def test_validate_page_accepts_matching_url_text_and_buttons():
    service = SelectorProfileService()

    result = service.validate_page(
        page_key="smt_edit",
        url="https://seller.example.com/products/edit/123",
        body_text="商品信息 半托管服务 编辑半托管信息",
        visible_buttons=["保存", "编辑半托管信息"],
    )

    assert result == {
        "ok": True,
        "missing": [],
        "forbidden_hits": [],
        "page_key": "smt_edit",
    }


def test_validate_page_reports_missing_url_and_text_requirements():
    service = SelectorProfileService()

    result = service.validate_page(
        page_key="smt_semi_edit",
        url="https://seller.example.com/products/edit/123",
        body_text="商品信息",
        visible_buttons=["保存"],
    )

    assert result["ok"] is False
    assert result["missing"] == [
        "url_contains:editFromSmt",
        "required_text:半托管信息",
    ]
    assert result["forbidden_hits"] == []
    assert result["page_key"] == "smt_semi_edit"


def test_validate_page_reports_publish_button_forbidden_hits():
    service = SelectorProfileService()

    result = service.validate_page(
        page_key="smt_edit",
        url="https://seller.example.com/products/edit/123",
        body_text="商品信息 半托管服务 编辑半托管信息",
        visible_buttons=["保存", "发布"],
    )

    assert result["ok"] is False
    assert result["missing"] == []
    assert result["forbidden_hits"] == ["发布"]


def test_validate_page_reports_continue_publish_button_forbidden_hits():
    service = SelectorProfileService()

    result = service.validate_page(
        page_key="smt_semi_edit",
        url="https://seller.example.com/products/editFromSmt/123",
        body_text="半托管信息",
        visible_buttons=["保存", "继续发布"],
    )

    assert result["ok"] is False
    assert result["forbidden_hits"] == ["继续发布"]
