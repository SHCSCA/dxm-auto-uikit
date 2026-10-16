from __future__ import annotations

from typing import Any, Mapping

from src.execution.action_boundary import configured_action
from src.execution.browser_agent_protocol import CONTENT_MUTATION_COMMANDS, canonical_frozen_target_identity

_FROZEN_TARGET_REQUIRED_ACTIONS = frozenset(
    {
        *(action for action, _ in CONTENT_MUTATION_COMMANDS.values()),
        "open_editor",
        "verify_edit_ownership",
        "prepare_rollback",
        "validate_editor_wholesale",
        "observe_content_finalize",
        "observe_native_video_inputs",
        "fill_editor_required_defaults",
        "fill_editor_variants",
        "fill_media_assets",
        "fill_compliance_defaults",
        "enable_semi_managed",
        "open_semi_managed_page",
        "fill_semi_managed_defaults",
        "save_only",
        "first_save_intent",
        "verify_not_published",
    }
)

@configured_action
def execute_browser_agent_action(adapter: Any, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params if isinstance(params, dict) else {}
    raw_target_identity = params.get("target_identity")
    target_identity_kwargs: dict[str, Any] = {}
    if action in _FROZEN_TARGET_REQUIRED_ACTIONS and raw_target_identity is None:
        raise ValueError(f"{action} requires a frozen exact target_identity")
    if raw_target_identity is not None:
        if not isinstance(raw_target_identity, Mapping):
            raise ValueError("target_identity must be a structured mapping")
        raw_store_name = params.get("store_name")
        if not isinstance(raw_store_name, str):
            raise ValueError("frozen target commands require an exact string store_name")
        store_name = " ".join(raw_store_name.split())
        if not store_name or raw_store_name != store_name:
            raise ValueError("frozen target commands require a canonical store_name")
        normalized_target = canonical_frozen_target_identity(
            dict(raw_target_identity),
            store_name=store_name,
        )
        if normalized_target is None:
            raise ValueError("target_identity validation unexpectedly returned empty")
        target_identity_kwargs = {"target_identity": normalized_target}
    if action == "update_live_hud":
        updater = getattr(adapter, "update_live_hud", None)
        if not callable(updater):
            return {"ok": True, "updated": False, "reason": "live_hud_unavailable"}
        hud = params.get("hud") if isinstance(params.get("hud"), dict) else {}
        return updater(hud)
    if action == "check_login_state":
        return adapter.check_login_state()
    if action == "open_draft_box":
        return adapter.open_draft_box()
    if action == "open_editor":
        return adapter.open_editor(
            product_query=_optional_str(params.get("product_query")),
            store_name=_optional_str(params.get("store_name")),
            note_text=_optional_str(params.get("note_text")),
            target_source_urls=_optional_str_list(params.get("target_source_urls")),
            **target_identity_kwargs,
        )
    if action == "verify_edit_ownership":
        return adapter.verify_edit_ownership(
            product_query=_optional_str(params.get("product_query")),
            store_name=_optional_str(params.get("store_name")),
            target_source_urls=_optional_str_list(params.get("target_source_urls")),
            **target_identity_kwargs,
        )
    if action == 'prepare_rollback':
        return adapter.prepare_rollback(defaults=params.get('defaults'),
            product_query=_optional_str(params.get('product_query')), store_name=_optional_str(params.get('store_name')),
            shop_id=params.get('shop_id'), **target_identity_kwargs)
    if action == 'validate_editor_wholesale':
        return adapter.validate_editor_wholesale(defaults=params.get('defaults'),
            product_query=_optional_str(params.get('product_query')), store_name=_optional_str(params.get('store_name')),
            shop_id=params.get('shop_id'), **target_identity_kwargs)
    if action == 'translate_editor_content':
        return adapter.translate_editor_content(defaults=params.get('defaults'),
            product_query=_optional_str(params.get('product_query')), store_name=_optional_str(params.get('store_name')),
            shop_id=params.get('shop_id'), **target_identity_kwargs)
    if action == 'observe_content_finalize':
        return adapter.observe_content_finalize(defaults=params.get('defaults'),
            product_query=_optional_str(params.get('product_query')), store_name=_optional_str(params.get('store_name')),
            shop_id=params.get('shop_id'), **target_identity_kwargs)
    if action == 'observe_native_video_inputs':
        return adapter.observe_native_video_inputs(defaults=params.get('defaults'),
            product_query=_optional_str(params.get('product_query')), store_name=_optional_str(params.get('store_name')),
            shop_id=params.get('shop_id'), **target_identity_kwargs)
    if action in {
        "fill_editor_required_defaults",
        "fill_editor_variants",
        "fill_media_assets",
        "fill_compliance_defaults",
        "open_semi_managed_page",
        "fill_semi_managed_defaults",
        "save_only",
        "first_save_intent",
    }:
        method = getattr(adapter, action)
        return method(
            defaults=params.get("defaults") if isinstance(params.get("defaults"), dict) else {},
            product_query=_optional_str(params.get("product_query")),
            store_name=_optional_str(params.get("store_name")),
            **target_identity_kwargs,
        )
    if action == "enable_semi_managed":
        return adapter.enable_semi_managed(
            product_query=_optional_str(params.get("product_query")),
            store_name=_optional_str(params.get("store_name")),
            **target_identity_kwargs,
        )
    if action == "verify_not_published":
        return adapter.verify_not_published(
            product_query=_optional_str(params.get("product_query")),
            store_name=_optional_str(params.get("store_name")),
            **target_identity_kwargs,
        )
    raise ValueError(f"Unsupported Browser Agent action: {action}")

def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None

def _optional_str_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() or item != item.strip()
        for item in value
    ):
        raise ValueError("target_source_urls must be a canonical string list")
    result = list(value)
    return result or None
