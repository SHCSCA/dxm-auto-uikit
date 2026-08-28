from __future__ import annotations

from dataclasses import dataclass
import json
import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.execution.account_identity import account_context_hash
from src.execution.dxm_adapter import DxmWorkflowAdapter
from src.execution.dxm_login_flow import (
    DXM_DRAFT_PAGE_FORM_KEYS,
    DXM_DRAFT_READ_ALLOWLIST,
    DXM_E2_PLAN_READ_ALLOWLIST,
    DxmLoginFlow,
)
from src.main import app
from src.services.dxm_draft_reader import DxmDraftReader, DxmDraftReaderError
from src.services.dxm_plan_reader import DxmPlanReader, DxmPlanReaderError


def _shop_response() -> dict[str, Any]:
    return {
        "code": 0,
        "data": {
            "userId": "42",
            "shopMap": {
                "101": {"idStr": "101", "name": "店铺甲", "platform": "smt"},
                "202": {"id": 202, "name": "店铺乙", "platform": "smt"},
            },
            "shopSmtTypeMap": {
                "101": "POP",
                "202": "aliChoice",
            },
        },
    }


def _page_response(
    *,
    page_no: int = 1,
    page_size: int = 2,
    total_page: int = 1,
    total_size: int = 2,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "code": 0,
        "data": {
            "page": {
                "pageNo": page_no,
                "pageSize": page_size,
                "totalPage": total_page,
                "totalSize": total_size,
                "list": items
                if items is not None
                else [
                    {
                        "idStr": "9001",
                        "shopId": "101",
                        "subject": "Draft one",
                        "dxmState": "draft",
                        "categoryId": "301",
                    },
                    {
                        "id": 9002,
                        "shopId": 101,
                        "subject": "Draft two",
                        "dxmState": "draft",
                        "categoryId": 302,
                    },
                ],
            },
        },
    }


@dataclass
class FakeDraftSource:
    shop_payload: dict[str, Any]
    page_payload: dict[str, Any]
    shop_session_id: str = "visible-session-1"
    page_session_id: str = "visible-session-1"
    shop_account_ref: str = "account-proof-1"
    page_account_ref: str = "account-proof-1"

    def __post_init__(self) -> None:
        self.page_calls: list[dict[str, Any]] = []

    def read_draft_shops(self) -> dict[str, Any]:
        return {
            "browser_session_id": self.shop_session_id,
            "account_ref": self.shop_account_ref,
            "payload": self.shop_payload,
        }

    def read_draft_page(
        self,
        *,
        shop_id: str,
        page_no: int,
        page_size: int,
    ) -> dict[str, Any]:
        self.page_calls.append(
            {
                "shop_id": shop_id,
                "page_no": page_no,
                "page_size": page_size,
            }
        )
        return {
            "browser_session_id": self.page_session_id,
            "account_ref": self.page_account_ref,
            "payload": self.page_payload,
        }


def test_shopmap_is_normalized_as_api_source_without_mock_fallback() -> None:
    reader = DxmDraftReader(FakeDraftSource(_shop_response(), _page_response()))

    result = reader.list_shops()

    assert result == {
        "source": "api",
        "session_bound": True,
        "session_ref": result["session_ref"],
        "shops": [
            {
                "id": "101",
                "name": "店铺甲",
                "platform": "smt",
                "shop_type": "POP",
            },
            {
                "id": "202",
                "name": "店铺乙",
                "platform": "smt",
                "shop_type": "aliChoice",
            },
        ],
    }
    assert len(result["session_ref"]) == 16


def test_session_ref_changes_when_authenticated_account_changes() -> None:
    first = DxmDraftReader(
        FakeDraftSource(
            _shop_response(),
            _page_response(),
            shop_account_ref="account-proof-1",
        )
    ).list_shops()
    second = DxmDraftReader(
        FakeDraftSource(
            _shop_response(),
            _page_response(),
            shop_account_ref="account-proof-2",
        )
    ).list_shops()

    assert first["session_ref"] != second["session_ref"]


def test_product_reader_rejects_authenticated_account_change_between_reads() -> None:
    reader = DxmDraftReader(
        FakeDraftSource(
            _shop_response(),
            _page_response(),
            shop_account_ref="account-proof-1",
            page_account_ref="account-proof-2",
        )
    )

    with pytest.raises(DxmDraftReaderError) as caught:
        reader.list_products(shop_id="101", page_no=1, page_size=2)

    assert caught.value.reason_code == "AUTH_ACCOUNT_MISMATCH"


@pytest.mark.parametrize("ambiguous_zero", [False, 0.0])
def test_reader_rejects_non_integer_non_string_success_codes(
    ambiguous_zero: bool | float,
) -> None:
    payload = _shop_response()
    payload["code"] = ambiguous_zero
    reader = DxmDraftReader(FakeDraftSource(payload, _page_response()))

    with pytest.raises(DxmDraftReaderError) as caught:
        reader.list_shops()

    assert caught.value.reason_code == "DXM_READ_REJECTED"


def test_shopmap_identity_drift_fails_closed() -> None:
    payload = _shop_response()
    payload["data"]["shopMap"]["101"]["idStr"] = "999"
    reader = DxmDraftReader(FakeDraftSource(payload, _page_response()))

    with pytest.raises(DxmDraftReaderError, match="店铺身份"):
        reader.list_shops()


def test_page_list_is_bound_to_requested_shop_and_draft_state() -> None:
    source = FakeDraftSource(_shop_response(), _page_response())
    reader = DxmDraftReader(source)

    result = reader.list_products(shop_id="101", page_no=1, page_size=2)

    assert source.page_calls == [{"shop_id": "101", "page_no": 1, "page_size": 2}]
    assert result["source"] == "api"
    assert result["session_bound"] is True
    assert len(result["session_ref"]) == 16
    assert result["session_ref"] == reader.list_shops()["session_ref"]
    assert result["filter"] == {"shop_id": "101", "dxm_state": "draft"}
    assert result["pagination"] == {
        "page_no": 1,
        "page_size": 2,
        "total_pages": 1,
        "total_items": 2,
        "has_previous": False,
        "has_next": False,
    }
    assert result["items"] == [
        {
            "id": "9001",
            "shop_id": "101",
            "subject": "Draft one",
            "category_id": "301",
            "dxm_state": "draft",
        },
        {
            "id": "9002",
            "shop_id": "101",
            "subject": "Draft two",
            "category_id": "302",
            "dxm_state": "draft",
        },
    ]


def test_page_list_accepts_the_console_maximum_of_200_rows() -> None:
    page = _page_response(page_size=200, total_page=0, total_size=0, items=[])
    source = FakeDraftSource(_shop_response(), page)

    result = DxmDraftReader(source).list_products(shop_id="101", page_no=1, page_size=200)

    assert source.page_calls == [{"shop_id": "101", "page_no": 1, "page_size": 200}]
    assert result["pagination"]["page_size"] == 200


def test_page_list_accepts_pdd_goods1_source_url() -> None:
    page = _page_response(
        page_size=1,
        total_size=1,
        items=[
            {
                "idStr": "9001",
                "shopId": "101",
                "subject": "PDD draft",
                "dxmState": "draft",
                "categoryId": "301",
                "sourceUrl": "https://mobile.yangkeduo.com/goods1.html?goods_id=953148740292",
            },
        ],
    )
    reader = DxmDraftReader(FakeDraftSource(_shop_response(), page))

    result = reader.list_products(shop_id="101", page_no=1, page_size=1)

    assert result["items"][0]["source_urls"] == [
        "https://mobile.yangkeduo.com/goods1.html?goods_id=953148740292",
    ]


def test_page_list_exposes_thumbnail_remark_shop_and_platform() -> None:
    page = _page_response(
        page_size=1,
        total_size=1,
        items=[
            {
                "idStr": "9001",
                "shopId": "101",
                "subject": "Draft one",
                "dxmState": "draft",
                "categoryId": "301",
                "imageURLs": (
                    "https://wxalbum-10001658-file.dianxiaomi.com/a.jpg;"
                    "https://cbu01.alicdn.com/b.jpg"
                ),
                "comment": "  宋 积木 资质没做  ",
                "sourceName": "1688",
            },
        ],
    )
    reader = DxmDraftReader(FakeDraftSource(_shop_response(), page))

    result = reader.list_products(shop_id="101", page_no=1, page_size=1)

    assert result["items"][0]["thumbnail_url"] == (
        "https://wxalbum-10001658-file.dianxiaomi.com/a.jpg"
    )
    assert result["items"][0]["remark"] == "宋 积木 资质没做"
    assert result["items"][0]["source_platform"] == "1688"
    assert result["items"][0]["shop_id"] == "101"


def test_page_list_omits_unsupported_source_url_without_stopping() -> None:
    page = _page_response(
        page_size=2,
        total_size=2,
        items=[
            {
                "idStr": "9001",
                "shopId": "101",
                "subject": "XHS draft",
                "dxmState": "draft",
                "categoryId": "301",
                "sourceUrl": "https://www.xiaohongshu.com/goods-detail/6986d3db4937e700017482a8",
            },
            {
                "idStr": "9002",
                "shopId": "101",
                "subject": "1688 draft",
                "dxmState": "draft",
                "categoryId": "302",
                "sourceUrl": "https://detail.1688.com/offer/1067786157619.html",
            },
        ],
    )
    reader = DxmDraftReader(FakeDraftSource(_shop_response(), page))

    result = reader.list_products(shop_id="101", page_no=1, page_size=2)

    assert [item["id"] for item in result["items"]] == ["9001", "9002"]
    assert "source_urls" not in result["items"][0]
    assert result["items"][1]["source_urls"] == [
        "https://detail.1688.com/offer/1067786157619.html",
    ]


def test_page_list_deduplicates_identical_product_identity() -> None:
    duplicate = {
        "idStr": "9001",
        "shopId": "101",
        "subject": "Same draft",
        "dxmState": "draft",
        "categoryId": "301",
    }
    page = _page_response(
        page_size=2,
        total_size=2,
        items=[duplicate, dict(duplicate)],
    )
    reader = DxmDraftReader(FakeDraftSource(_shop_response(), page))

    result = reader.list_products(shop_id="101", page_no=1, page_size=2)

    assert [item["id"] for item in result["items"]] == ["9001"]
    assert result["deduplicated_count"] == 1


def test_page_list_rejects_conflicting_duplicate_product_identity() -> None:
    page = _page_response(
        page_size=2,
        total_size=2,
        items=[
            {
                "id": 9001,
                "shopId": 101,
                "subject": "First",
                "dxmState": "draft",
            },
            {
                "idStr": "9001",
                "shopId": "101",
                "subject": "Changed",
                "dxmState": "draft",
            },
        ],
    )
    reader = DxmDraftReader(FakeDraftSource(_shop_response(), page))

    with pytest.raises(DxmDraftReaderError, match="重复商品"):
        reader.list_products(shop_id="101", page_no=1, page_size=2)


@pytest.mark.parametrize(
    ("page", "reason_code"),
    [
        (
            _page_response(
                items=[
                    {
                        "id": 9001,
                        "shopId": 202,
                        "subject": "Wrong store",
                        "dxmState": "draft",
                    },
                    {
                        "id": 9002,
                        "shopId": 202,
                        "subject": "Wrong store",
                        "dxmState": "draft",
                    },
                ]
            ),
            "PRODUCT_SHOP_MISMATCH",
        ),
        (
            _page_response(
                items=[
                    {
                        "id": 9001,
                        "shopId": 101,
                        "subject": "Wrong state",
                        "dxmState": "online",
                    },
                    {
                        "id": 9002,
                        "shopId": 101,
                        "subject": "Wrong state",
                        "dxmState": "online",
                    },
                ]
            ),
            "PRODUCT_STATE_MISMATCH",
        ),
        (
            _page_response(total_page=2, total_size=2),
            "PAGINATION_INCONSISTENT",
        ),
    ],
)
def test_page_list_schema_or_binding_drift_fails_closed(
    page: dict[str, Any],
    reason_code: str,
) -> None:
    reader = DxmDraftReader(FakeDraftSource(_shop_response(), page))

    with pytest.raises(DxmDraftReaderError) as caught:
        reader.list_products(shop_id="101", page_no=1, page_size=2)
    assert caught.value.reason_code == reason_code


def test_empty_page_is_a_valid_closed_pagination_result() -> None:
    reader = DxmDraftReader(
        FakeDraftSource(
            _shop_response(),
            _page_response(
                page_size=20,
                total_page=0,
                total_size=0,
                items=[],
            ),
        )
    )

    result = reader.list_products(shop_id="-1", page_no=1, page_size=20)

    assert result["items"] == []
    assert result["pagination"]["total_items"] == 0
    assert result["pagination"]["has_next"] is False


def test_shop_and_page_must_share_the_same_visible_browser_session() -> None:
    reader = DxmDraftReader(
        FakeDraftSource(
            _shop_response(),
            _page_response(),
            shop_session_id="visible-session-1",
            page_session_id="visible-session-2",
        )
    )

    with pytest.raises(DxmDraftReaderError, match="会话"):
        reader.list_products(shop_id="101", page_no=1, page_size=2)


def test_unknown_shop_filter_fails_before_page_list_call() -> None:
    source = FakeDraftSource(_shop_response(), _page_response())
    reader = DxmDraftReader(source)

    with pytest.raises(DxmDraftReaderError, match="店铺"):
        reader.list_products(shop_id="303", page_no=1, page_size=2)

    assert source.page_calls == []


def test_reader_routes_return_safe_409_for_schema_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    source = FakeDraftSource(_shop_response(), _page_response(total_page=2, total_size=2))
    monkeypatch.setattr("src.main.workflow_adapter", source)
    monkeypatch.setattr("src.main._assert_batch_browser_available", lambda: None)

    response = TestClient(app).get(
        "/api/dxm/draft-reader/products",
        params={"shop_id": "101", "page_no": 1, "page_size": 2},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "PAGINATION_INCONSISTENT"
    assert response.json()["detail"]["message"]
    assert "Traceback" not in response.json()["detail"]["message"]


def test_reader_routes_expose_shopmap_with_real_source_label(monkeypatch: pytest.MonkeyPatch) -> None:
    source = FakeDraftSource(_shop_response(), _page_response())
    dispatched: list[str] = []
    fail_fast_flags: list[bool] = []

    def run_on_login_owner(func: Any, *args: Any, **kwargs: Any) -> Any:
        dispatched.append(func.__name__)
        fail_fast_flags.append(kwargs.pop("fail_if_busy", False))
        return func(*args, **kwargs)

    monkeypatch.setattr("src.main.workflow_adapter", source)
    monkeypatch.setattr("src.main._assert_batch_browser_available", lambda: None)
    monkeypatch.setattr("src.main._run_login_flow", run_on_login_owner)

    response = TestClient(app).get("/api/dxm/draft-reader/shops")

    assert response.status_code == 200
    assert response.json()["source"] == "api"
    assert [shop["id"] for shop in response.json()["shops"]] == ["101", "202"]
    assert dispatched == ["list_shops"]
    assert fail_fast_flags == [True]


class FakeApiResponse:
    def __init__(
        self,
        payload: dict[str, Any],
        *,
        ok: bool = True,
        status: int = 200,
    ) -> None:
        self._payload = payload
        self.ok = ok
        self.status = status

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeApiRequestContext:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.shop_payload = _shop_response()
        self.page_payload = _page_response()

    def get(self, url: str, *, timeout: int) -> FakeApiResponse:
        self.calls.append(("GET", url, timeout))
        return FakeApiResponse(self.shop_payload)

    def post(
        self,
        url: str,
        *,
        form: dict[str, str],
        timeout: int,
    ) -> FakeApiResponse:
        self.calls.append(("POST", url, dict(form), timeout))
        return FakeApiResponse(self.page_payload)


class FakeBrowserContext:
    def __init__(self, request: FakeApiRequestContext) -> None:
        self.request = request

    def is_closed(self) -> bool:
        return False


class FakePage:
    def __init__(self, context: FakeBrowserContext) -> None:
        self.context = context
        self.url = "https://www.dianxiaomi.com/web/home"

    def is_closed(self) -> bool:
        return False

    def title(self) -> str:
        return "店小秘后台"


class FakeBrowser:
    def is_connected(self) -> bool:
        return True


class FakeLiveClient:
    pass


def _visible_flow(monkeypatch: pytest.MonkeyPatch) -> tuple[DxmLoginFlow, FakeApiRequestContext]:
    api_request = FakeApiRequestContext()
    context = FakeBrowserContext(api_request)
    browser = FakeBrowser()
    flow = DxmLoginFlow(FakeLiveClient())
    flow._context = context
    flow._browser = browser
    flow._page = FakePage(context)
    flow._browser_session_generation = "visible-session-1"
    flow._browser_session_context_id = id(context)
    flow._browser_session_browser_id = id(browser)
    flow._browser_session_thread_id = threading.get_ident()
    monkeypatch.setattr(flow, "_is_headless", lambda: False)
    return flow, api_request


def test_visible_session_shop_reader_uses_only_allowlisted_userinfo_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow, api_request = _visible_flow(monkeypatch)

    result = flow.read_draft_shops()

    assert result == {
        "browser_session_id": "visible-session-1",
        "account_ref": result["account_ref"],
        "payload": _shop_response(),
    }
    assert len(result["account_ref"]) == 32
    assert api_request.calls == [
        ("GET", "https://www.dianxiaomi.com/api/userInfo.json", 15_000)
    ]


def test_visible_session_reader_fails_closed_without_stable_account_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow, api_request = _visible_flow(monkeypatch)
    api_request.shop_payload["data"].pop("userId")

    with pytest.raises(DxmDraftReaderError) as caught:
        flow.read_draft_shops()

    assert caught.value.reason_code == "AUTH_ACCOUNT_UNPROVEN"
    assert api_request.calls == [
        ("GET", "https://www.dianxiaomi.com/api/userInfo.json", 15_000)
    ]


def test_visible_account_reference_changes_with_authenticated_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow, _api_request = _visible_flow(monkeypatch)
    first = flow._authenticated_account_ref(_shop_response())
    changed = _shop_response()
    changed["data"]["userId"] = "84"

    assert first != flow._authenticated_account_ref(changed)


def test_owner_thread_account_refresh_reproves_userinfo_and_updates_context_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow, api_request = _visible_flow(monkeypatch)
    first_ref = flow._authenticated_account_ref(_shop_response())

    first_hash = flow.refresh_account_context_hash()

    assert first_hash == account_context_hash(first_ref)
    assert flow.current_account_context_hash() == first_hash
    assert api_request.calls == [
        ("GET", "https://www.dianxiaomi.com/api/userInfo.json", 15_000)
    ]

    api_request.shop_payload["data"]["userId"] = "84"
    changed_ref = flow._authenticated_account_ref(api_request.shop_payload)
    second_hash = flow.refresh_account_context_hash()

    assert second_hash == account_context_hash(changed_ref)
    assert second_hash != first_hash
    assert flow.current_account_context_hash() == second_hash
    assert flow.browser_session_id() == "visible-session-1"


def test_account_refresh_rejects_non_owner_thread_even_when_cache_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow, _api_request = _visible_flow(monkeypatch)
    cached = flow.refresh_account_context_hash()
    flow._browser_session_thread_id = -1

    with pytest.raises(DxmDraftReaderError) as caught:
        flow.refresh_account_context_hash()

    assert caught.value.reason_code == "BROWSER_SESSION_THREAD_MISMATCH"
    assert flow.current_account_context_hash() == cached


def test_visible_account_reference_accepts_current_userinfo_identity_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow, _api_request = _visible_flow(monkeypatch)
    current_schema = {
        "code": 0,
        "data": {
            "id": 42,
            "puid": 84,
            "account": "operator-account",
            "shopMap": {},
        },
    }

    first = flow._authenticated_account_ref(current_schema)
    changed = {
        **current_schema,
        "data": {
            **current_schema["data"],
            "id": 43,
        },
    }

    assert len(first) == 32
    assert first != flow._authenticated_account_ref(changed)


def test_reader_allowlist_has_only_two_read_contracts() -> None:
    assert DXM_DRAFT_READ_ALLOWLIST == {
        ("GET", "https://www.dianxiaomi.com/api/userInfo.json"),
        ("POST", "https://www.dianxiaomi.com/api/smtProduct/pageList.json"),
    }
    assert DXM_DRAFT_PAGE_FORM_KEYS == {
        "pageNo",
        "pageSize",
        "total",
        "searchType",
        "searchValue",
        "shopId",
        "dxmState",
        "dxmOfflineState",
    }


def test_e2_plan_reader_allowlist_contains_only_documented_read_contracts() -> None:
    assert DXM_E2_PLAN_READ_ALLOWLIST == {
        ("GET", "https://www.dianxiaomi.com/api/smtProduct/edit.json"),
        ("GET", "https://www.dianxiaomi.com/api/smtCommLogisticAttribute/getLogisticAttributeList.json"),
        ("GET", "https://www.dianxiaomi.com/api/smtCommProduct/supportNewSizeAttribute.json"),
        ("POST", "https://www.dianxiaomi.com/api/userTemplate/pageList.json"),
        ("POST", "https://www.dianxiaomi.com/api/smtAttributeTemplate/pageList.json"),
        (
            "POST",
            "https://www.dianxiaomi.com/api/smtAttributeTemplate/getTemplateListByCategory.json",
        ),
        ("POST", "https://www.dianxiaomi.com/api/variationTemplate/com/smt/pageList.json"),
        ("POST", "https://www.dianxiaomi.com/api/smtShopInfoSync/list.json"),
        (
            "POST",
            "https://www.dianxiaomi.com/api/variationTemplate/com/smt/getNameListByCategory.json",
        ),
        ("POST", "https://www.dianxiaomi.com/api/smtShopInfoSync/sizeChartList.json"),
        ("POST", "https://www.dianxiaomi.com/api/smtCategory/attributeList.json"),
        (
            "POST",
            "https://www.dianxiaomi.com/api/smtCategory/childAttributeList.json",
        ),
        ("POST", "https://www.dianxiaomi.com/api/smtCategory/list.json"),
        ("POST", "https://www.dianxiaomi.com/api/smtCategory/searchCategory.json"),
        ("POST", "https://www.dianxiaomi.com/api/smtCategory/getByCategoryId.json"),
        ("POST", "https://www.dianxiaomi.com/api/userTemplate/templateListForModule.json"),
        ("POST", "https://www.dianxiaomi.com/api/smtAdjustPrice/pageList.json"),
        ("POST", "https://www.dianxiaomi.com/api/smtCommMsr/list.json"),
        ("POST", "https://www.dianxiaomi.com/api/smtCommManufacture/list.json"),
        ("POST", "https://www.dianxiaomi.com/api/smtCategory/syncQualification.json"),
        ("POST", "https://www.dianxiaomi.com/api/smtProduct/getSmtCommission.json"),
        ("POST", "https://www.dianxiaomi.com/api/smtProduct/verifyPopChoiceShop.json"),
    }
    assert all("save" not in url.casefold() and "publish" not in url.casefold() for _method, url in DXM_E2_PLAN_READ_ALLOWLIST)


def test_visible_session_e2_product_details_read_current_editor_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow, api_request = _visible_flow(monkeypatch)
    api_request.calls = []

    def get(
        url: str,
        *,
        timeout: int,
        params: dict[str, str] | None = None,
    ) -> FakeApiResponse:
        if url.endswith("/api/userInfo.json"):
            api_request.calls.append(("GET", url, timeout))
            return FakeApiResponse(_shop_response())
        product_id = str((params or {}).get("id") or "")
        api_request.calls.append(("GET", url, dict(params or {}), timeout))
        return FakeApiResponse(
            {
                "code": 0,
                "data": {
                    "product": {
                        "idStr": product_id,
                        "shopId": "101",
                        "categoryId": "301",
                        "dxmState": "draft",
                        "subject": f"Current title {product_id}",
                        "grossWeight": 1.25,
                        "aeopAeProductPropertys": json.dumps(
                            [{"attrNameId": 5301, "attrValueId": 7301}]
                        ),
                    }
                },
            }
        )

    monkeypatch.setattr(api_request, "get", get)

    result = flow.read_e2_product_details(
        shop_id="101",
        product_ids=["70001", "70002", "70003"],
    )

    assert result["browser_session_id"] == "visible-session-1"
    assert len(result["account_ref"]) == 32
    assert [
        item["idStr"]
        for item in result["payload"]["products"]
    ] == ["70001", "70002", "70003"]
    assert api_request.calls == [
        ("GET", "https://www.dianxiaomi.com/api/userInfo.json", 15_000),
        (
            "GET",
            "https://www.dianxiaomi.com/api/smtProduct/edit.json",
            {"id": "70001"},
            15_000,
        ),
        (
            "GET",
            "https://www.dianxiaomi.com/api/smtProduct/edit.json",
            {"id": "70002"},
            15_000,
        ),
        (
            "GET",
            "https://www.dianxiaomi.com/api/smtProduct/edit.json",
            {"id": "70003"},
            15_000,
        ),
        ("GET", "https://www.dianxiaomi.com/api/userInfo.json", 15_000),
    ]


def test_visible_session_e2_product_details_accepts_one_confirmed_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The operator may preview/save a confirmed batch containing one draft."""

    flow, api_request = _visible_flow(monkeypatch)
    api_request.calls = []

    def get(
        url: str,
        *,
        timeout: int,
        params: dict[str, str] | None = None,
    ) -> FakeApiResponse:
        if url.endswith("/api/userInfo.json"):
            api_request.calls.append(("GET", url, timeout))
            return FakeApiResponse(_shop_response())
        product_id = str((params or {}).get("id") or "")
        api_request.calls.append(("GET", url, dict(params or {}), timeout))
        return FakeApiResponse(
            {
                "code": 0,
                "data": {
                    "product": {
                        "idStr": product_id,
                        "shopId": "101",
                        "categoryId": "301",
                        "dxmState": "draft",
                        "subject": f"Current title {product_id}",
                    }
                },
            }
        )

    monkeypatch.setattr(api_request, "get", get)

    result = flow.read_e2_product_details(
        shop_id="101",
        product_ids=["70001"],
    )

    assert [item["idStr"] for item in result["payload"]["products"]] == ["70001"]
    assert api_request.calls == [
        ("GET", "https://www.dianxiaomi.com/api/userInfo.json", 15_000),
        (
            "GET",
            "https://www.dianxiaomi.com/api/smtProduct/edit.json",
            {"id": "70001"},
            15_000,
        ),
        ("GET", "https://www.dianxiaomi.com/api/userInfo.json", 15_000),
    ]


def test_e2_product_detail_current_attribute_ids_are_normalized() -> None:
    current_values = DxmPlanReader._current_values_from_detail(
        {
            "aeopAeProductPropertys": json.dumps(
                [{"attrNameId": 5301, "attrValueId": 7301}]
            ),
        },
        schema={
            "properties": {
                "attr_5301": {"type": "string"},
            },
        },
    )

    assert current_values == {"attr_5301": "7301"}


@pytest.mark.parametrize("wire_sentinel", [0, "0"])
def test_e2_product_detail_zero_value_id_uses_auditable_wire_value(
    wire_sentinel,
) -> None:
    current_values = DxmPlanReader._current_values_from_detail(
        {
            "aeopAeProductPropertys": json.dumps(
                [{
                    "attrNameId": 5301,
                    "attrValueId": wire_sentinel,
                    "attrValue": "Acrylic",
                }]
            ),
        },
        schema={
            "properties": {
                "attr_5301": {"type": "string"},
            },
        },
    )

    assert current_values == {"attr_5301": "Acrylic"}


@pytest.mark.parametrize("wire_sentinel", [-1, "-1"])
def test_e2_product_detail_negative_one_value_id_uses_known_attribute_custom_text(
    wire_sentinel,
) -> None:
    current_values = DxmPlanReader._current_values_from_detail(
        {
            "aeopAeProductPropertys": json.dumps(
                [{
                    "attrNameId": 5301,
                    "attrValueId": wire_sentinel,
                    "attrValue": "Acrylic",
                }]
            ),
        },
        schema={
            "properties": {
                "attr_5301": {"type": "string"},
            },
        },
    )

    assert current_values == {"attr_5301": "Acrylic"}


@pytest.mark.parametrize(
    ("raw_value_id", "wire_shape"),
    [
        (True, "boolean"),
        (0.0, "float_zero"),
        (1.5, "float_positive"),
        (" 0 ", "whitespace_numeric"),
        (-7, "negative"),
        ([], "container"),
        ("not-an-id", "text"),
    ],
)
def test_e2_product_detail_rejects_invalid_attr_value_id_by_wire_shape(
    raw_value_id,
    wire_shape: str,
) -> None:
    with pytest.raises(DxmPlanReaderError) as captured:
        DxmPlanReader._current_values_from_detail(
            {
                "aeopAeProductPropertys": json.dumps(
                    [
                        {"attrNameId": 5301, "attrValueId": 7301},
                        {"attrNameId": 5302, "attrValueId": raw_value_id},
                    ]
                ),
            },
            schema={
                "properties": {
                    "attr_5301": {"type": "string"},
                    "attr_5302": {"type": "string"},
                },
            },
        )

    assert captured.value.reason_code == "DXM_PLAN_IDENTITY_INVALID"
    assert str(captured.value) == (
        "编辑页 attrValueId 非法："
        f"property_index=1 wire_shape={wire_shape}。"
    )


def test_visible_session_page_reader_forces_allowlisted_draft_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow, api_request = _visible_flow(monkeypatch)

    result = flow.read_draft_page(shop_id="101", page_no=2, page_size=20)

    assert result["browser_session_id"] == "visible-session-1"
    assert len(result["account_ref"]) == 32
    assert result["payload"] == _page_response()
    assert api_request.calls == [
        ("GET", "https://www.dianxiaomi.com/api/userInfo.json", 15_000),
        (
            "POST",
            "https://www.dianxiaomi.com/api/smtProduct/pageList.json",
            {
                "pageNo": "2",
                "pageSize": "20",
                "total": "0",
                "searchType": "0",
                "searchValue": "",
                "shopId": "101",
                "dxmState": "draft",
                "dxmOfflineState": "",
            },
            15_000,
        )
    ]


def test_visible_session_e2_reader_uses_only_documented_read_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow, api_request = _visible_flow(monkeypatch)
    api_request.calls = []

    def get(
        url: str,
        *,
        timeout: int,
        params: dict[str, str] | None = None,
    ) -> FakeApiResponse:
        if url.endswith("/api/userInfo.json"):
            api_request.calls.append(("GET", url, timeout))
            return FakeApiResponse(_shop_response())
        api_request.calls.append(("GET", url, dict(params or {}), timeout))
        category_id = str((params or {}).get("categoryId") or "")
        if url.endswith("/api/smtCommLogisticAttribute/getLogisticAttributeList.json"):
            return FakeApiResponse({
                "code": 0,
                "data": {
                    "categoryId": category_id,
                    "dataSourceJson": json.dumps([
                        {"value_id": "1983471271", "label": "普货", "children": None},
                        {
                            "value_id": "1983471275",
                            "label": "纯电",
                            "children": [
                                {"value_id": "796", "label": "干电池"},
                            ],
                        },
                    ]),
                },
            })
        if url.endswith("/api/smtCommProduct/supportNewSizeAttribute.json"):
            return FakeApiResponse({"code": 0, "data": 1 if category_id == "301" else 0})
        raise AssertionError(f"unexpected E2 GET endpoint: {url}")

    def post(url: str, *, form: dict[str, str], timeout: int) -> FakeApiResponse:
        api_request.calls.append(("POST", url, dict(form), timeout))
        if url.endswith("/api/userTemplate/templateListForModule.json"):
            return FakeApiResponse({"code": 0, "data": {"propertyList": [], "templateList": [], "packageList": []}})
        if url.endswith("/api/smtCommMsr/list.json"):
            return FakeApiResponse({"code": 0, "data": {"101": []}})
        if url.endswith("/api/smtCommManufacture/list.json"):
            return FakeApiResponse({"code": 0, "data": {"101": []}})
        if url.endswith("/api/smtAdjustPrice/pageList.json"):
            return FakeApiResponse({"code": 0, "data": ""})
        if url.endswith("/api/smtProduct/getSmtCommission.json"):
            return FakeApiResponse({"code": 0, "data": 5.0})
        if url.endswith("/api/smtProduct/verifyPopChoiceShop.json"):
            return FakeApiResponse({
                "code": 0,
                "data": [{"shopId": "101", "isPopChoice": True, "popChoiceShopId": "901"}],
            })
        if url.endswith("/api/smtCategory/getByCategoryId.json"):
            return FakeApiResponse({"code": 0, "data": {"categoryId": form["categoryId"]}})
        if url.endswith("/api/smtCategory/syncQualification.json"):
            return FakeApiResponse({"code": 0, "data": []})
        if url.endswith("/api/smtAttributeTemplate/getTemplateListByCategory.json"):
            category_id = form["categoryId"]
            return FakeApiResponse({
                "code": 0,
                "data": {
                    "attributeTemplateList": [{
                        "id": f"9{category_id}",
                        "templateName": f"属性模板 {category_id}",
                        "shopId": "101",
                        "categoryId": category_id,
                        "productPropertys": json.dumps(
                            [
                                {
                                    "attrNameId": f"5{category_id}",
                                    "attrValueId": (
                                        "7303" if category_id == "302" else f"7{category_id}"
                                    ),
                                },
                                *(
                                    [
                                        {
                                            "attrNameId": "5301",
                                            "attrValueId": "7302",
                                        },
                                        {
                                            "attrNameId": "",
                                            "attrValueId": "",
                                            "attrName": "自定义表面处理",
                                            "attrValue": "Brushed",
                                        },
                                    ]
                                    if category_id == "301"
                                    else []
                                ),
                            ]
                        ),
                    }],
                },
            })
        if url.endswith("/api/userTemplate/pageList.json"):
            return FakeApiResponse(
                {
                    "code": 0,
                    "data": {
                        "page": {
                            "pageNo": 1,
                            "pageSize": 50,
                            "totalPage": 1,
                            "totalSize": 1,
                            "list": [
                                {
                                    "idStr": "701",
                                    "name": "产品模板甲",
                                    "shopId": "101",
                                    "categoryId": "301",
                                    "moduleList": [
                                        {
                                            "moduleType": "package",
                                            "data": json.dumps(
                                                {
                                                    "grossWeight": "1.25",
                                                    "packageLength": "20",
                                                    "originalBox": "1",
                                                    "productPrice": "9.99",
                                                    "freightTemplateId": "801",
                                                    "imageURLs": (
                                                        "https://img.example.test/a.jpg;"
                                                        "https://img.example.test/b.jpg"
                                                    ),
                                                    "aeopAeProductSKUs": json.dumps(
                                                        [
                                                            {
                                                                "skuCode": "SKU-301",
                                                                "skuPrice": "9.99",
                                                                "ipmSkuStock": "8",
                                                            }
                                                        ]
                                                    ),
                                                }
                                            ),
                                        }
                                    ],
                                }
                            ],
                        }
                    },
                }
            )
        if url.endswith("/api/smtShopInfoSync/list.json"):
            return FakeApiResponse(
                {
                    "code": 0,
                    "data": {
                        "freightTemplateList": [
                            {"templateId": "801", "templateName": "运费模板甲", "shopId": "101"}
                        ],
                        "promiseTemplateList": [
                            {"templateId": "802", "templateName": "服务模板甲"}
                        ],
                    },
                }
            )
        if url.endswith("/api/smtAttributeTemplate/pageList.json"):
            return FakeApiResponse(
                {
                    "code": 0,
                    "data": {
                        "page": {
                            "pageNo": 1,
                            "pageSize": 50,
                            "totalPage": 1,
                            "totalSize": 2,
                            "list": [
                                {
                                    "id": "9301",
                                    "templateName": "属性模板 301",
                                    "shopId": "101",
                                    "categoryId": "301",
                                    "productPropertys": json.dumps(
                                        [
                                            {"attrNameId": 5301, "attrValueId": 7301},
                                            {"attrNameId": "5301", "attrValueId": "7302"},
                                            {
                                                "attrNameId": "",
                                                "attrValueId": "",
                                                "attrName": "自定义表面处理",
                                                "attrValue": "Brushed",
                                            },
                                        ]
                                    ),
                                },
                                {
                                    "id": "9302",
                                    "templateName": "属性模板 302",
                                    "shopId": "101",
                                    "categoryId": "302",
                                    "productPropertys": json.dumps(
                                        [
                                            {
                                                "attrNameId": "5302",
                                                "attrValueId": "7303",
                                            }
                                        ]
                                    ),
                                },
                            ],
                        }
                    },
                }
            )
        if url.endswith("/api/variationTemplate/com/smt/getNameListByCategory.json"):
            return FakeApiResponse({"code": 0, "data": None})
        if url.endswith("/api/smtShopInfoSync/sizeChartList.json"):
            return FakeApiResponse({"code": 0, "data": {"sizeList": []}})
        if url.endswith("/api/smtCategory/attributeList.json"):
            category_id = form["categoryId"]
            return FakeApiResponse(
                {
                    "code": 0,
                    "data": [
                        {
                            "arrtNameId": 3,
                            "nameZh": "型号",
                            "nameEn": "Model",
                            "inputType": "INPUT",
                            "required": False,
                            "sku": False,
                            "values": "[]",
                            "units": "[]",
                        },
                        {
                            "arrtNameId": f"5{category_id}",
                            "nameZh": f"类目 {category_id} 材质",
                            "nameEn": "Material",
                            "inputType": "STRING",
                            "attributeShowTypeValue": "check_box",
                            "required": True,
                            "sku": False,
                            "values": json.dumps(
                                [
                                    {
                                        "id": int(category_id),
                                        "name": "Metal",
                                        "hasSubAttr": (
                                            "1"
                                            if category_id == "301"
                                            else "0"
                                        ),
                                    }
                                ]
                            ),
                            "units": json.dumps([{"id": "1", "name": "g"}]),
                        }
                    ],
                }
            )
        if url.endswith("/api/smtCategory/childAttributeList.json"):
            assert form == {
                "categoryId": "301",
                "arrtNameId": "5301",
                "arrtValueId": "301",
            }
            return FakeApiResponse(
                {
                    "code": 0,
                    "data": [
                        {
                            "arrtNameId": 6301,
                            "nameZh": "材质等级",
                            "nameEn": "Material grade",
                            "inputType": "STRING",
                            "required": "1",
                            "sku": "0",
                            "values": json.dumps(
                                [{"id": 8301, "name": "Grade A"}]
                            ),
                            "units": "[]",
                        }
                    ],
                }
            )
        raise AssertionError(f"unexpected E2 read endpoint: {url}")

    monkeypatch.setattr(api_request, "get", get)
    monkeypatch.setattr(api_request, "post", post)

    result = flow.read_e2_plan_scope(
        shop_id="101",
        category_ids=["301", "302"],
    )

    assert result["browser_session_id"] == "visible-session-1"
    assert len(result["account_ref"]) == 32
    records = result["payload"]["template_records"]
    assert {
        (
            record["ref_type"],
            record["dxm_template_id"],
            record["shop_id"],
            record["category_id"],
        )
        for record in records
    } == {
        ("product", "701", "101", "301"),
        ("freight", "801", "101", None),
        ("service", "802", "101", None),
        ("attribute", "9301", "101", "301"),
        ("attribute", "9302", "101", "302"),
    }
    schemas = result["payload"]["category_schemas"]
    assert set(schemas) == {"301", "302"}
    # Shared plans do not require a product-specific title; the target
    # category is the immutable required scope value.
    assert schemas["301"]["required"] == ["attr_5301", "categoryId"]
    assert schemas["301"]["properties"]["title"]["natural_language"] is True
    assert schemas["301"]["properties"]["grossWeight"]["type"] == "number"
    assert schemas["301"]["properties"]["freightTemplateId"]["type"] == "string"
    assert schemas["301"]["properties"]["aeopAeProductSKUs"]["type"] == "array"
    assert schemas["301"]["properties"]["imageURLs"]["items"] == {
        "type": "string",
        "minLength": 1,
        "pattern": "^https?://",
    }
    assert schemas["301"]["properties"]["imageURLs"]["wire_format"] == (
        "semicolon_delimited"
    )
    assert schemas["301"]["properties"]["detail"]["natural_language"] is True
    assert schemas["301"]["properties"]["mobileDetail"]["natural_language"] is True
    identifier_schema = schemas["301"]["properties"]["attr_3"]
    assert identifier_schema["type"] == "string"
    assert identifier_schema["minLength"] == 1
    assert identifier_schema["natural_language"] is False
    assert identifier_schema["ui_binding"] == "dxm_attribute:3"
    sku_schema = schemas["301"]["properties"]["aeopAeProductSKUs"]["items"]
    assert sku_schema["properties"]["skuPrice"]["pattern"]
    assert sku_schema["properties"]["cargoPrice"]["pattern"]
    assert sku_schema["properties"]["ipmSkuStock"]["minimum"] == 0
    assert {
        field_key: definition["ui_label_zh"]
        for field_key, definition in sku_schema["properties"].items()
    } == {
        "skuCode": "SKU 编码",
        "skuPrice": "SKU 售价",
        "cargoPrice": "SKU 货值",
        "ipmSkuStock": "SKU 库存",
        "aeopSKUProperty": "SKU 属性组合",
        "logisticAttrList": "SKU 物流属性",
    }
    assert schemas["301"]["price_policy"] == {
        "sku_cargo_not_above_sale": True,
        "sku_prices_within_range": True,
    }
    assert sku_schema["properties"]["aeopSKUProperty"]["type"] == "array"
    assert sku_schema["properties"]["logisticAttrList"]["source_api"] == (
        "/api/smtCommLogisticAttribute/getLogisticAttributeList.json"
    )
    assert sku_schema["properties"]["logisticAttrList"]["items"]["properties"]["value"]["values"] == [
        {"id": "1983471271", "name": "普货"},
        {"id": "1983471275", "name": "纯电"},
        {"id": "796", "name": "干电池"},
    ]
    assert result["payload"]["category_capabilities"]["301"] == {
        "logistics_attribute_options": [
            {"value_id": "1983471271", "label": "普货", "children": None},
            {
                "value_id": "1983471275",
                "label": "纯电",
                "children": [{"value_id": "796", "label": "干电池"}],
            },
        ],
        "support_new_size_attribute": True,
        "commission_rate": 5.0,
        "pop_choice_shop": {
            "shopId": "101",
            "isPopChoice": True,
            "popChoiceShopId": "901",
        },
        "source_apis": [
            "/api/smtCommLogisticAttribute/getLogisticAttributeList.json",
            "/api/smtCommProduct/supportNewSizeAttribute.json",
            "/api/smtProduct/getSmtCommission.json",
            "/api/smtProduct/verifyPopChoiceShop.json",
        ],
    }
    assert schemas["301"]["properties"]["attr_5301"]["ui_label_zh"] == "类目 301 材质"
    assert schemas["301"]["properties"]["title"]["ui_binding"] == (
        "dxm_editor:title"
    )
    assert schemas["301"]["properties"]["attr_5301"]["ui_binding"] == (
        "dxm_attribute:5301"
    )
    assert schemas["301"]["properties"]["attr_5301"]["type"] == "array"
    assert schemas["301"]["properties"]["attr_6301"]["ui_label_zh"] == "材质等级"
    assert schemas["301"]["allOf"] == [
        {
            "if": {
                "properties": {
                    "attr_5301": {
                        "contains": {"const": "301"},
                    }
                },
                "required": ["attr_5301"],
            },
            "then": {"required": ["attr_6301"]},
        }
    ]
    assert schemas["301"]["properties"]["attr_5301"]["values"] == [
        {"id": 301, "name": "Metal", "hasSubAttr": "1"}
    ]
    assert schemas["301"]["properties"]["attr_5301"]["units"] == [
        {"id": "1", "name": "g"}
    ]
    product_ref = next(
        record
        for record in records
        if record["ref_type"] == "product" and record["category_id"] == "301"
    )
    assert product_ref["resolved_values"] == {
        "aeopAeProductSKUs": [
            {
                "ipmSkuStock": 8,
                "skuCode": "SKU-301",
                "skuPrice": "9.99",
            }
        ],
        "freightTemplateId": "801",
        "grossWeight": 1.25,
        "imageURLs": [
            "https://img.example.test/a.jpg",
            "https://img.example.test/b.jpg",
        ],
        "originalBox": True,
        "packageLength": 20,
        "productPrice": 9.99,
    }
    attribute_ref = next(
        record
        for record in records
        if record["ref_type"] == "attribute" and record["category_id"] == "301"
    )
    assert attribute_ref["source_api"] == (
        "/api/smtAttributeTemplate/getTemplateListByCategory.json"
    )
    assert attribute_ref["resolved_values"] == {
        "attr_5301": ["7301", "7302"]
    }
    assert attribute_ref["audit_items"] == [
        {
            "kind": "unmapped_custom_attribute",
            "executable": False,
            "source_index": 2,
            "attr_name": "自定义表面处理",
            "attr_value": "Brushed",
            "reason_code": "DXM_TEMPLATE_ATTRIBUTE_ID_UNMAPPED",
        }
    ]
    category_302_ref = next(
        record
        for record in records
        if record["ref_type"] == "attribute" and record["category_id"] == "302"
    )
    assert category_302_ref["resolved_values"] == {
        "attr_5302": ["7303"]
    }
    assert api_request.calls[0] == (
        "GET",
        "https://www.dianxiaomi.com/api/userInfo.json",
        15_000,
    )
    assert all(
        call[1].startswith("https://www.dianxiaomi.com/api/")
        for call in api_request.calls
    )
    assert api_request.calls[-1] == (
        "GET",
        "https://www.dianxiaomi.com/api/userInfo.json",
        15_000,
    )
    assert (
        "POST",
        "https://www.dianxiaomi.com/api/smtCategory/childAttributeList.json",
        {
            "categoryId": "301",
            "arrtNameId": "5301",
            "arrtValueId": "301",
        },
        15_000,
    ) in api_request.calls
    # The category availability response already carries productPropertys in
    # this fixture, so the account-wide management index is intentionally not
    # called for a normal one-scope plan sync.
    assert len(api_request.calls) == 27
    request_trace = result["payload"]["request_trace"]
    assert len(request_trace) == 25
    assert all(
        set(entry) >= {"label", "path", "status", "outcome", "elapsed_ms"}
        and entry["outcome"] == "ok"
        and entry["status"] == 200
        and isinstance(entry["elapsed_ms"], float)
        for entry in request_trace
    )


def test_e2_response_json_payload_decodes_gbk_template_names_without_replacement() -> None:
    class BytesResponse:
        ok = True
        status = 200
        headers = {"content-type": "application/json; charset=gbk"}

        def body(self) -> bytes:
            return json.dumps({"code": 0, "data": {"name": "撕膜"}}, ensure_ascii=False).encode("gbk")

        def json(self) -> dict[str, Any]:
            raise AssertionError("the byte decoder must run before response.json()")

    payload = DxmLoginFlow._response_json_payload(BytesResponse())
    assert payload["data"]["name"] == "撕膜"
    assert "\ufffd" not in payload["data"]["name"]


def test_e2_attribute_template_raw_wire_parses_all_fifty_multivalue_records() -> None:
    raw_records = [
        {
            "id": str(9300 + index),
            "templateName": f"脱敏属性模板 {index}",
            "shopId": "101",
            "categoryId": "301",
            "productPropertys": json.dumps([
                {"attrNameId": 5301, "attrValueId": 7301},
                {"attrNameId": "5301", "attrValueId": str(7301 + index)},
                *(
                    [
                        {
                            "attrNameId": "",
                            "attrValueId": "",
                            "attrName": "",
                            "attrValueName": "",
                        }
                    ]
                    if index <= 38
                    else []
                ),
            ]),
        }
        for index in range(1, 51)
    ]

    records = DxmLoginFlow._e2_named_template_records(
        raw_records,
        ref_type="attribute",
        id_keys=("id", "idStr"),
        name_keys=("templateName", "name"),
        shop_id="101",
        category_id="301",
        source_api="/api/smtAttributeTemplate/pageList.json",
    )

    assert len(records) == 50
    assert all(record["availability"] == "available" for record in records)
    assert records[0]["resolved_values"] == {
        "attr_5301": ["7301", "7302"]
    }
    assert records[-1]["resolved_values"] == {
        "attr_5301": ["7301", "7351"]
    }


def test_e2_product_templates_accept_unselected_promise_template_sentinel() -> None:
    records = DxmLoginFlow._e2_named_template_records(
        [
            {
                "idStr": str(700 + index),
                "name": f"脱敏产品模板 {index}",
                "shopId": "101",
                "categoryId": "301",
                "moduleList": [
                    {
                        "moduleType": "service",
                        "data": json.dumps({
                            "promiseTemplateId": 0,
                            "productPrice": str(9 + index),
                        }),
                    }
                ],
            }
            for index in range(1, 6)
        ],
        ref_type="product",
        id_keys=("id", "idStr"),
        name_keys=("templateName", "name"),
        shop_id="101",
        category_id="301",
        source_api="/api/userTemplate/pageList.json",
    )

    assert len(records) == 5
    assert all(
        "promiseTemplateId" not in record["resolved_values"]
        for record in records
    )
    assert [record["resolved_values"]["productPrice"] for record in records] == [
        10,
        11,
        12,
        13,
        14,
    ]


def test_e2_service_templates_drop_unselected_zero_identity_sentinel() -> None:
    records = DxmLoginFlow._e2_named_template_records(
        [
            {"templateId": 0, "templateName": "未选择服务模板"},
            {"templateId": "901", "templateName": "真实服务模板"},
        ],
        ref_type="service",
        id_keys=("templateId",),
        name_keys=("templateName",),
        shop_id="101",
        category_id=None,
        source_api="/api/smtShopInfoSync/list.json",
    )

    assert len(records) == 1
    assert records[0]["dxm_template_id"] == "901"


@pytest.mark.parametrize(
    ("wire_value", "expected"),
    [("0", False), ("1", True)],
)
def test_e2_product_template_accepts_wire_boolean_strings(
    wire_value: str,
    expected: bool,
) -> None:
    resolved = DxmLoginFlow._e2_template_resolved_values(
        {
            "moduleList": [
                {
                    "moduleType": "package",
                    "data": json.dumps({"originalBox": wire_value}),
                }
            ]
        },
        ref_type="product",
        template_id="701",
    )

    assert resolved["originalBox"] is expected


@pytest.mark.parametrize(
    ("field_key", "value"),
    [
        ("grossWeight", "not-a-number"),
        ("originalBox", "yes"),
        ("aeopAeProductSKUs", "{}"),
        ("freightTemplateId", "0"),
    ],
)
def test_e2_product_template_values_fail_closed_on_ambiguous_editor_types(
    field_key: str,
    value: Any,
) -> None:
    raw = {
        "moduleList": [
            {
                "moduleType": "package",
                "data": json.dumps({field_key: value}),
            }
        ]
    }

    with pytest.raises(DxmDraftReaderError) as caught:
        DxmLoginFlow._e2_template_resolved_values(
            raw,
            ref_type="product",
            template_id="701",
        )

    assert caught.value.reason_code == "DXM_TEMPLATE_RESPONSE_INVALID"


@pytest.mark.parametrize("bad_code", [False, 0.0])
def test_visible_session_e2_reader_rejects_bool_and_float_success_codes(
    monkeypatch: pytest.MonkeyPatch,
    bad_code: Any,
) -> None:
    flow, api_request = _visible_flow(monkeypatch)

    def post(url: str, *, form: dict[str, str], timeout: int) -> FakeApiResponse:
        api_request.calls.append(("POST", url, dict(form), timeout))
        return FakeApiResponse({"code": bad_code, "data": {}})

    monkeypatch.setattr(api_request, "post", post)

    with pytest.raises(DxmDraftReaderError) as caught:
        flow.read_e2_plan_scope(shop_id="101", category_ids=["301"])

    assert caught.value.reason_code == "DXM_PLAN_READ_REJECTED"
    assert api_request.calls[-1][1] == "https://www.dianxiaomi.com/api/userTemplate/pageList.json"


def test_visible_session_reader_does_not_open_or_recover_a_missing_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = DxmLoginFlow(FakeLiveClient())
    monkeypatch.setattr(
        flow,
        "_ensure_page",
        lambda: pytest.fail("reader must not open a browser"),
    )

    with pytest.raises(DxmDraftReaderError) as caught:
        flow.read_draft_shops()

    assert caught.value.reason_code == "BROWSER_SESSION_UNAVAILABLE"


@pytest.mark.parametrize(
    ("page_url", "headless", "reason_code"),
    [
        ("https://www.dianxiaomi.com/login.htm", False, "LOGIN_REQUIRED"),
        ("https://example.invalid/web/home", False, "DXM_PAGE_REQUIRED"),
        ("https://www.dianxiaomi.com/web/home", True, "VISIBLE_BROWSER_REQUIRED"),
    ],
)
def test_reader_rejects_login_foreign_or_headless_page(
    monkeypatch: pytest.MonkeyPatch,
    page_url: str,
    headless: bool,
    reason_code: str,
) -> None:
    flow, api_request = _visible_flow(monkeypatch)
    flow._page.url = page_url
    monkeypatch.setattr(flow, "_is_headless", lambda: headless)

    with pytest.raises(DxmDraftReaderError) as caught:
        flow.read_draft_shops()

    assert caught.value.reason_code == reason_code
    assert api_request.calls == []


def test_adapter_exposes_only_the_two_read_contracts() -> None:
    flow = FakeDraftSource(_shop_response(), _page_response())
    adapter = DxmWorkflowAdapter(flow)

    shops = adapter.read_draft_shops()
    page = adapter.read_draft_page(shop_id="101", page_no=1, page_size=2)

    assert shops["payload"] == _shop_response()
    assert page["payload"] == _page_response()
    assert flow.page_calls == [{"shop_id": "101", "page_no": 1, "page_size": 2}]


def test_category_tree_proxy_children_and_search_normalize_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow, api_request = _visible_flow(monkeypatch)

    def post(
        url: str,
        *,
        form: dict[str, str],
        timeout: int,
    ) -> FakeApiResponse:
        api_request.calls.append(("POST", url, dict(form), timeout))
        if url.endswith("/api/smtCategory/list.json"):
            if not form:
                return FakeApiResponse({"code": 0, "data": []})
            return FakeApiResponse(
                {
                    "code": 0,
                    "data": [
                        {
                            "categoryId": 200003937,
                            "nameZh": "手工艺品&缝纫用品（半成品）",
                            "nameEn": "Arts,Crafts & Sewing",
                            "nodePath": "家居用品(Home & Garden) > 手工艺品&缝纫用品（半成品）",
                            "nodePathId": "15/200003937",
                            "pcid": 15,
                            "isleaf": 0,
                            "level": 2,
                        },
                        {"categoryId": "bad", "nameZh": "脏记录"},
                        {"nameZh": "无 ID 记录"},
                    ],
                }
            )
        if url.endswith("/api/smtCategory/searchCategory.json"):
            return FakeApiResponse(
                {
                    "code": 0,
                    "data": [
                        {
                            "categoryId": "28191907",
                            "nameZh": "广告立牌",
                            "nodePath": "Industry & Business/Advertising Equipment/Advertising Screens(广告立牌)",
                        }
                    ],
                }
            )
        if url.endswith("/api/smtCategory/getByCategoryId.json"):
            return FakeApiResponse(
                {
                    "code": 0,
                    "data": {
                        "categoryId": "201393405",
                        "nameZh": "人形立牌",
                    },
                }
            )
        raise AssertionError(f"unexpected post url {url}")

    monkeypatch.setattr(api_request, "post", post)

    children = flow.read_category_children(pcid="200003937")
    assert children == [
        {
            "categoryId": "200003937",
            "nameZh": "手工艺品&缝纫用品（半成品）",
            "nameEn": "Arts,Crafts & Sewing",
            "nodePath": "家居用品(Home & Garden) > 手工艺品&缝纫用品（半成品）",
            "nodePathId": "15/200003937",
            "pcid": 15,
            "isleaf": 0,
            "level": 2,
        }
    ]

    top = flow.read_category_children(pcid="")
    assert top == []
    assert api_request.calls[1][2] == {}

    found = flow.search_categories(keyword="立牌")
    assert found[0]["categoryId"] == "28191907"
    assert api_request.calls[2][2] == {"category": "立牌"}

    by_id = flow.get_category_by_id(category_id="201393405")
    assert by_id == {
        "categoryId": "201393405",
        "nameZh": "人形立牌",
    }
    assert api_request.calls[-1][2] == {"categoryId": "201393405"}


def test_category_tree_proxy_rejects_off_contract_forms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow, api_request = _visible_flow(monkeypatch)

    def post(
        url: str,
        *,
        form: dict[str, str],
        timeout: int,
    ) -> FakeApiResponse:
        api_request.calls.append(("POST", url, dict(form), timeout))
        return FakeApiResponse({"code": 0, "data": []})

    monkeypatch.setattr(api_request, "post", post)

    with pytest.raises(DxmDraftReaderError) as caught:
        flow.read_category_children(pcid="-1")
    assert caught.value.reason_code == "DXM_PLAN_READ_ALLOWLIST_VIOLATION"

    with pytest.raises(DxmDraftReaderError) as caught:
        flow.search_categories(keyword="")
    assert caught.value.reason_code == "DXM_PLAN_READ_ALLOWLIST_VIOLATION"

    with pytest.raises(DxmDraftReaderError) as caught:
        flow.search_categories(keyword="x" * 65)
    assert caught.value.reason_code == "DXM_PLAN_READ_ALLOWLIST_VIOLATION"

    with pytest.raises(DxmDraftReaderError) as caught:
        flow.get_category_by_id(category_id="abc")
    assert caught.value.reason_code == "DXM_PLAN_READ_ALLOWLIST_VIOLATION"

    assert api_request.calls == []
