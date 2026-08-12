from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Any

from src.execution.batch_command_contract import (
    BatchCommandContractError,
    canonical_contract_sha256,
    validate_batch_queue_guard_shape,
    validate_save_verification_context,
)

from src.execution.product_identity import is_stable_product_id


MUTATION_COMMAND_PLANS: dict[tuple[str, str], dict[str, int]] = {
    (
        "CLAIM_TO_DRAFT_BOX",
        "claim_from_data_acquisition",
    ): {
        "claim_open_dialog_click": 1,
        "claim_confirm_click": 2,
    },
    ("SAVE_ONLY", "save_only"): {
        "save_only_click": 1,
    },
}

_MUTATION_STATES = frozenset(state for state, _action in MUTATION_COMMAND_PLANS)
_MUTATION_COMMAND_ACTIONS = frozenset(action for _state, action in MUTATION_COMMAND_PLANS)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


class MutationCommandContractError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _positive_mutation_id(value: int | str | None, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise MutationCommandContractError(
            "MUTATION_SCOPE_IDENTITY_INVALID",
            f"{field_name} must be a positive integer",
        )
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise MutationCommandContractError(
            "MUTATION_SCOPE_IDENTITY_INVALID",
            f"{field_name} must be a positive integer",
        ) from exc
    if result <= 0 or str(value).strip() != str(result):
        raise MutationCommandContractError(
            "MUTATION_SCOPE_IDENTITY_INVALID",
            f"{field_name} must be a canonical positive integer",
        )
    return result


def _required_text(value: Any, *, reason_code: str, field_name: str) -> str:
    result = str(value or "").strip()
    if not result or result != value:
        raise MutationCommandContractError(reason_code, f"{field_name} is required and must be canonical")
    return result


def _required_sha256(value: Any, *, field_name: str) -> str:
    result = str(value or "")
    if _SHA256_RE.fullmatch(result) is None:
        raise MutationCommandContractError(
            "MUTATION_SCOPE_HASH_INVALID",
            f"{field_name} must be a sha256 digest",
        )
    return result


def build_mutation_scope_id(
    *,
    authorization_lease_id: str,
    task_id: int | str,
    job_id: int | str,
    state: str,
    action: str,
) -> str:
    """Build one durable logical mutation scope without an ephemeral runtime ID.

    Target and authorization digests are deliberately not inputs to the scope
    identity. They are immutable ledger bindings under this scope, so drift
    conflicts instead of creating a fresh scope that could dispatch again.
    """

    lease_id = _required_text(
        authorization_lease_id,
        reason_code="MUTATION_AUTHORIZATION_LEASE_REQUIRED",
        field_name="authorization_lease_id",
    )
    canonical_task_id = _positive_mutation_id(task_id, field_name="task_id")
    canonical_job_id = _positive_mutation_id(job_id, field_name="job_id")
    canonical_state = _required_text(
        state,
        reason_code="MUTATION_COMMAND_SCOPE_INVALID",
        field_name="state",
    )
    canonical_action = _required_text(
        action,
        reason_code="MUTATION_COMMAND_SCOPE_INVALID",
        field_name="action",
    )
    material = {
        "schema": "dxm.mutation-scope.v1",
        "authorization_lease_id": lease_id,
        "task_id": canonical_task_id,
        "job_id": canonical_job_id,
        "state": canonical_state,
        "action": canonical_action,
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_mutation_id(
    *,
    mutation_scope_id: str,
    state: str,
    ordinal: int,
    mutation_action: str,
) -> str:
    """Build the stable identity of one exact external dispatch attempt."""

    scope_id = _required_sha256(mutation_scope_id, field_name="mutation_scope_id")
    canonical_state = _required_text(
        state,
        reason_code="MUTATION_COMMAND_SCOPE_INVALID",
        field_name="state",
    )
    canonical_action = _required_text(
        mutation_action,
        reason_code="MUTATION_ACTION_OUTSIDE_COMMAND_SCOPE",
        field_name="mutation_action",
    )
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal <= 0:
        raise MutationCommandContractError(
            "MUTATION_ORDINAL_INVALID",
            "mutation ordinal must be a positive integer",
        )
    material = {
        "schema": "dxm.mutation-dispatch.v1",
        "mutation_scope_id": scope_id,
        "state": canonical_state,
        "ordinal": ordinal,
        "mutation_action": canonical_action,
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_optional_target_text(value: Any) -> str | None:
    if value is None:
        return None
    result = " ".join(str(value).split())
    return result or None


def _canonical_target_source_urls(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise MutationCommandContractError(
            "MUTATION_TARGET_INVALID",
            "target_source_urls must be a list or tuple",
        )
    candidates = [str(item).strip() for item in value if str(item).strip()]
    if not candidates:
        return []
    try:
        from src.state_machine.two_stage import canonical_source_identity

        identity = canonical_source_identity(candidates[0], candidates)
    except Exception as exc:
        raise MutationCommandContractError(
            "MUTATION_TARGET_INVALID",
            "target_source_urls do not form a canonical source identity",
        ) from exc
    urls = list(identity["urls"])
    if any(not _is_supported_frozen_source_url(item) for item in urls):
        raise MutationCommandContractError(
            "MUTATION_TARGET_INVALID",
            "target_source_urls must be supported external product detail pages",
        )
    return urls


def _is_supported_frozen_source_url(value: str) -> bool:
    try:
        from src.state_machine.two_stage import is_supported_product_detail_url

        return is_supported_product_detail_url(value)
    except Exception:
        return False


def _canonical_frozen_target_identity(value: Any, *, store_name: str) -> dict[str, Any] | None:
    """Validate the immutable identity captured from the visible DXM draft box.

    Every governed edit/save command carries this object and binds the mutation
    hash to both a structured product identity and canonical source URLs instead
    of trusting a display-title substring.
    """

    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "store_fingerprint",
        "stable_identity",
        "source_urls",
    }:
        raise MutationCommandContractError(
            "MUTATION_TARGET_INVALID",
            "target_identity must be an exact dxm draft-box target object",
        )
    if value.get("schema_version") != "dxm_draft_box_target.v1":
        raise MutationCommandContractError(
            "MUTATION_TARGET_INVALID",
            "target_identity schema is not supported",
        )
    stable = value.get("stable_identity")
    if not isinstance(stable, dict) or set(stable) != {"kind", "value", "fingerprint"}:
        raise MutationCommandContractError(
            "MUTATION_TARGET_INVALID",
            "target_identity stable identity is invalid",
        )
    kind = _required_text(
        stable.get("kind"),
        reason_code="MUTATION_TARGET_INVALID",
        field_name="target_identity.stable_identity.kind",
    )
    stable_value = _required_text(
        stable.get("value"),
        reason_code="MUTATION_TARGET_INVALID",
        field_name="target_identity.stable_identity.value",
    )
    raw_fingerprint = stable.get("fingerprint")
    fingerprint = _required_sha256(
        raw_fingerprint,
        field_name="target_identity.stable_identity.fingerprint",
    ).upper()
    raw_store_fingerprint = value.get("store_fingerprint")
    store_fingerprint = _required_sha256(
        raw_store_fingerprint,
        field_name="target_identity.store_fingerprint",
    ).upper()
    if raw_fingerprint != fingerprint or raw_store_fingerprint != store_fingerprint:
        raise MutationCommandContractError(
            "MUTATION_TARGET_INVALID",
            "target_identity digests must be canonical uppercase sha256 values",
        )
    expected_store_fingerprint = hashlib.sha256(
        json.dumps(
            {"source": "structured_store_cell", "store_name": store_name},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest().upper()
    if not hmac.compare_digest(store_fingerprint, expected_store_fingerprint):
        raise MutationCommandContractError(
            "MUTATION_TARGET_INVALID",
            "target_identity store binding does not match store_name",
        )
    raw_source_urls = value.get("source_urls")
    if not isinstance(raw_source_urls, list) or any(
        not isinstance(item, str) or not item.strip() or item != item.strip()
        for item in raw_source_urls
    ):
        raise MutationCommandContractError(
            "MUTATION_TARGET_INVALID",
            "target_identity.source_urls must be a canonical string list",
        )
    source_urls = _canonical_target_source_urls(raw_source_urls)
    if not source_urls or source_urls != raw_source_urls or any(
        not _is_supported_frozen_source_url(item) for item in source_urls
    ):
        raise MutationCommandContractError(
            "MUTATION_TARGET_INVALID",
            "target_identity requires non-empty canonical supported product source URLs",
        )
    if kind == "product_id":
        if not is_stable_product_id(stable_value):
            raise MutationCommandContractError(
                "MUTATION_TARGET_INVALID",
                "target_identity product_id is not a structured product identifier",
            )
        expected_fingerprint = hashlib.sha256(
            f"product_id:{stable_value}".encode("utf-8")
        ).hexdigest().upper()
    elif kind == "source_url":
        if not source_urls:
            raise MutationCommandContractError(
                "MUTATION_TARGET_INVALID",
                "source_url target identity requires canonical source URLs",
            )
        try:
            from src.state_machine.two_stage import canonical_source_identity

            source_identity = canonical_source_identity(source_urls[0], source_urls)
        except Exception as exc:
            raise MutationCommandContractError(
                "MUTATION_TARGET_INVALID",
                "source_url target identity is not canonical",
            ) from exc
        if stable_value != source_identity["primary_url"]:
            raise MutationCommandContractError(
                "MUTATION_TARGET_INVALID",
                "source_url target identity conflicts with its source URLs",
            )
        expected_fingerprint = str(source_identity["fingerprint"]).upper()
    else:
        raise MutationCommandContractError(
            "MUTATION_TARGET_INVALID",
            "target_identity stable identity kind is unsupported",
        )
    if not hmac.compare_digest(fingerprint, expected_fingerprint):
        raise MutationCommandContractError(
            "MUTATION_TARGET_INVALID",
            "target_identity fingerprint cannot be reproduced",
        )
    return {
        "schema_version": "dxm_draft_box_target.v1",
        "store_fingerprint": store_fingerprint,
        "stable_identity": {
            "kind": kind,
            "value": stable_value,
            "fingerprint": fingerprint,
        },
        "source_urls": source_urls,
    }


def canonical_frozen_target_identity(value: Any, *, store_name: str) -> dict[str, Any] | None:
    """Public strict validator used by every Browser Agent step carrying a frozen target."""

    return _canonical_frozen_target_identity(value, store_name=store_name)


def build_frozen_product_target_identity(
    *,
    product_id: str,
    store_name: str,
    source_urls: list[str],
) -> dict[str, Any]:
    """Build the one canonical product-id target accepted by save commands."""

    canonical_product_id = _required_text(
        product_id,
        reason_code="MUTATION_TARGET_INVALID",
        field_name="product_id",
    )
    if not is_stable_product_id(canonical_product_id):
        raise MutationCommandContractError(
            "MUTATION_TARGET_INVALID",
            "product_id is not a structured stable product identifier",
        )
    canonical_store_name = _required_text(
        store_name,
        reason_code="MUTATION_TARGET_INVALID",
        field_name="store_name",
    )
    canonical_source_urls = _canonical_target_source_urls(source_urls)
    if not canonical_source_urls:
        raise MutationCommandContractError(
            "MUTATION_TARGET_INVALID",
            "frozen product target requires canonical source URLs",
        )
    candidate = {
        "schema_version": "dxm_draft_box_target.v1",
        "store_fingerprint": hashlib.sha256(
            json.dumps(
                {
                    "source": "structured_store_cell",
                    "store_name": canonical_store_name,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest().upper(),
        "stable_identity": {
            "kind": "product_id",
            "value": canonical_product_id,
            "fingerprint": hashlib.sha256(
                f"product_id:{canonical_product_id}".encode("utf-8")
            ).hexdigest().upper(),
        },
        "source_urls": canonical_source_urls,
    }
    canonical = _canonical_frozen_target_identity(
        candidate,
        store_name=canonical_store_name,
    )
    if canonical is None:  # pragma: no cover - candidate is always non-null
        raise MutationCommandContractError(
            "MUTATION_TARGET_INVALID",
            "frozen product target could not be constructed",
        )
    return canonical


def canonical_mutation_target_payload(
    command_action: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Canonicalize the expected or freshly observed target of a mutation.

    The same helper is suitable for V1 command construction and the browser's
    last-instant page observation. Mutable editor defaults are intentionally
    excluded: they are inputs to the save, not the identity being mutated.
    """

    if not isinstance(values, dict):
        raise MutationCommandContractError(
            "MUTATION_TARGET_INVALID",
            "mutation target values must be a mapping",
        )
    action = str(command_action or "").strip()
    if action not in _MUTATION_COMMAND_ACTIONS:
        raise MutationCommandContractError(
            "MUTATION_TARGET_ACTION_INVALID",
            "command action has no mutation target contract",
        )
    store_name = _canonical_optional_target_text(values.get("store_name"))
    product_query = _canonical_optional_target_text(values.get("product_query"))
    target_source_urls = _canonical_target_source_urls(values.get("target_source_urls"))
    if not store_name:
        raise MutationCommandContractError(
            "MUTATION_TARGET_INVALID",
            "mutation target requires an exact store_name",
        )
    if action == "claim_from_data_acquisition":
        category_name = _canonical_optional_target_text(values.get("category_name"))
        claim_mark = _canonical_optional_target_text(values.get("claim_mark"))
        if not claim_mark or not target_source_urls:
            raise MutationCommandContractError(
                "MUTATION_TARGET_INVALID",
                "claim target requires claim_mark and canonical source URLs",
            )
        return {
            "schema": "dxm.mutation-target.v1",
            "action": action,
            "claim_mark": claim_mark,
            "product_query": product_query,
            "category_name": category_name,
            "store_name": store_name,
            "target_source_urls": target_source_urls,
        }
    target_identity = _canonical_frozen_target_identity(
        values.get("target_identity"),
        store_name=store_name,
    )
    if target_identity is None:
        raise MutationCommandContractError(
            "MUTATION_TARGET_INVALID",
            "save target requires a frozen target_identity",
        )
    frozen_source_urls = target_identity["source_urls"]
    if target_source_urls and target_source_urls != frozen_source_urls:
        raise MutationCommandContractError(
            "MUTATION_TARGET_INVALID",
            "mutation source URLs do not match the frozen target identity",
        )
    target_source_urls = frozen_source_urls
    target = {
        "schema": "dxm.mutation-target.v1",
        "action": action,
        # Display text is never part of a mutation identity.
        "product_query": None,
        "store_name": store_name,
        "target_source_urls": target_source_urls,
        "target_identity": target_identity,
        "target_identity_sha256": hashlib.sha256(
            json.dumps(
                target_identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest().upper(),
    }
    return target


def mutation_target_hash(command_action: str, values: dict[str, Any]) -> str:
    canonical = canonical_mutation_target_payload(command_action, values)
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class BrowserAgentCommand:
    command_id: str
    idempotency_key: str
    deadline: str
    expected_page: str
    runtime_id: str
    task_id: int | str | None
    job_id: int | str | None
    state: str
    action: str
    params: dict[str, Any]
    execution_mode: str = ""
    execution_payload_hash: str | None = None
    step_label: str | None = None
    mutation_scope_id: str | None = None
    target_hash: str | None = None
    authorization_fingerprint: str | None = None
    authorization_lease_id: str | None = None
    authorization_lease_fingerprint: str | None = None
    stage_task_facts_fingerprint: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "command_id": self.command_id,
            "idempotency_key": self.idempotency_key,
            "deadline": self.deadline,
            "expected_page": self.expected_page,
            "runtime_id": self.runtime_id,
            "task_id": self.task_id,
            "job_id": self.job_id,
            "state": self.state,
            "action": self.action,
            "params": dict(self.params),
            "step_label": self.step_label,
        }
        if self.execution_mode:
            payload["execution_mode"] = self.execution_mode
        for key in (
            "mutation_scope_id",
            "target_hash",
            "authorization_fingerprint",
            "authorization_lease_id",
            "authorization_lease_fingerprint",
            "stage_task_facts_fingerprint",
            "execution_payload_hash",
        ):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        return payload


def browser_agent_command_sha256(command: BrowserAgentCommand) -> str:
    """Digest the exact serialized command that crosses the worker boundary."""

    if not isinstance(command, BrowserAgentCommand):
        raise MutationCommandContractError(
            "MUTATION_COMMAND_INVALID",
            "browser agent command is required",
        )
    return canonical_contract_sha256(command.to_payload())


def validate_browser_agent_command(command: BrowserAgentCommand) -> dict[str, int]:
    """Return the exact inner-mutation ordinal plan or fail closed."""

    pair = (str(command.state or ""), str(command.action or ""))
    plan = MUTATION_COMMAND_PLANS.get(pair)
    mutation_adjacent = pair[0] in _MUTATION_STATES or pair[1] in _MUTATION_COMMAND_ACTIONS
    mutation_fields = (
        command.mutation_scope_id,
        command.target_hash,
        command.authorization_fingerprint,
        command.authorization_lease_id,
        command.authorization_lease_fingerprint,
        command.stage_task_facts_fingerprint,
        command.execution_payload_hash,
    )
    if plan is None:
        if mutation_adjacent:
            raise MutationCommandContractError(
                "MUTATION_COMMAND_SCOPE_INVALID",
                "mutation state and command action do not form an allowed pair",
            )
        if any(value is not None for value in mutation_fields):
            raise MutationCommandContractError(
                "NON_MUTATION_SCOPE_FORBIDDEN",
                "non-mutation commands cannot carry mutation scope fields",
            )
        if pair == ("VERIFY_NOT_PUBLISHED", "verify_not_published") and (
            str(command.execution_mode or "") == "batch_draft_save"
        ):
            try:
                validate_save_verification_context(
                    command.params.get("save_verification_context"),
                    task_id=command.task_id,
                    job_id=command.job_id,
                    runtime_id=command.runtime_id,
                    execution_mode=command.execution_mode,
                    structural_only=True,
                )
            except BatchCommandContractError as exc:
                raise MutationCommandContractError(
                    exc.reason_code,
                    "batch VERIFY_NOT_PUBLISHED is not bound to one exact SAVE",
                ) from exc
        return {}

    execution_mode = _required_text(
        command.execution_mode,
        reason_code="MUTATION_EXECUTION_MODE_REQUIRED",
        field_name="execution_mode",
    )
    allowed_modes = (
        {"claim_only"}
        if pair == ("CLAIM_TO_DRAFT_BOX", "claim_from_data_acquisition")
        else {"single_save", "batch_save", "batch_draft_save"}
    )
    if execution_mode not in allowed_modes:
        raise MutationCommandContractError(
            "MUTATION_EXECUTION_MODE_INVALID",
            "execution_mode is not allowed for this mutation command",
        )

    if execution_mode == "batch_draft_save":
        try:
            validate_batch_queue_guard_shape(command.params.get("batch_queue_guard"))
        except BatchCommandContractError as exc:
            raise MutationCommandContractError(
                exc.reason_code,
                "batch_draft_save requires one exact frozen queue guard",
            ) from exc
        execution_payload_hash = _required_sha256(
            command.execution_payload_hash,
            field_name="execution_payload_hash",
        )
        defaults = command.params.get("defaults")
        execution_payload = (
            defaults.get("_frozen_execution_payload")
            if isinstance(defaults, dict)
            else None
        )
        defaults_payload_hash = (
            defaults.get("_frozen_execution_payload_hash")
            if isinstance(defaults, dict)
            else None
        )
        if not isinstance(execution_payload, dict):
            raise MutationCommandContractError(
                "MUTATION_EXECUTION_PAYLOAD_REQUIRED",
                "batch_draft_save requires a frozen execution payload",
            )
        embedded_hash = _required_sha256(
            execution_payload.get("payload_hash"),
            field_name="embedded execution payload hash",
        )
        defaults_hash = _required_sha256(
            defaults_payload_hash,
            field_name="defaults execution payload hash",
        )
        try:
            encoded = json.dumps(
                {
                    key: value
                    for key, value in execution_payload.items()
                    if key != "payload_hash"
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise MutationCommandContractError(
                "MUTATION_EXECUTION_PAYLOAD_INVALID",
                "batch execution payload is not canonical JSON",
            ) from exc
        recomputed = hashlib.sha256(encoded).hexdigest()
        if not (
            hmac.compare_digest(execution_payload_hash.casefold(), embedded_hash.casefold())
            and hmac.compare_digest(execution_payload_hash.casefold(), defaults_hash.casefold())
            and hmac.compare_digest(execution_payload_hash.casefold(), recomputed.casefold())
        ):
            raise MutationCommandContractError(
                "MUTATION_EXECUTION_PAYLOAD_MISMATCH",
                "batch execution payload hashes do not match",
            )
        fields = execution_payload.get("fields")
        if not isinstance(fields, list):
            raise MutationCommandContractError(
                "MUTATION_EXECUTION_PAYLOAD_INVALID",
                "batch execution fields are missing",
            )
        for field in fields:
            if (
                not isinstance(field, dict)
                or not isinstance(field.get("field_key"), str)
                or "resolved_value" not in field
                or defaults.get(field["field_key"]) != field["resolved_value"]
            ):
                raise MutationCommandContractError(
                    "MUTATION_EXECUTION_PAYLOAD_MISMATCH",
                    "batch defaults differ from the embedded execution fields",
                )

    scope_id = _required_text(
        command.mutation_scope_id,
        reason_code="MUTATION_SCOPE_REQUIRED",
        field_name="mutation_scope_id",
    )
    _required_sha256(scope_id, field_name="mutation_scope_id")
    lease_id = _required_text(
        command.authorization_lease_id,
        reason_code="MUTATION_AUTHORIZATION_LEASE_REQUIRED",
        field_name="authorization_lease_id",
    )
    if command.execution_mode == "batch_draft_save":
        _required_sha256(
            command.authorization_lease_fingerprint,
            field_name="authorization_lease_fingerprint",
        )
    _required_sha256(command.target_hash, field_name="target_hash")
    _required_sha256(command.authorization_fingerprint, field_name="authorization_fingerprint")
    _required_sha256(
        command.stage_task_facts_fingerprint,
        field_name="stage_task_facts_fingerprint",
    )
    expected_scope = build_mutation_scope_id(
        authorization_lease_id=lease_id,
        task_id=command.task_id,
        job_id=command.job_id,
        state=command.state,
        action=command.action,
    )
    if not hmac.compare_digest(scope_id, expected_scope):
        raise MutationCommandContractError(
            "MUTATION_SCOPE_FINGERPRINT_MISMATCH",
            "mutation_scope_id does not match the logical authorization scope",
        )
    return dict(plan)


def mutation_ordinal_for_command(
    command: BrowserAgentCommand,
    mutation_action: str,
) -> int:
    plan = validate_browser_agent_command(command)
    ordinal = plan.get(str(mutation_action or ""))
    if ordinal is None:
        raise MutationCommandContractError(
            "MUTATION_ACTION_OUTSIDE_COMMAND_SCOPE",
            "mutation action is outside this command's exact ordinal plan",
        )
    return ordinal


def browser_agent_command_from_worker_request(
    request: dict[str, Any],
    *,
    step_label: str | None = None,
) -> BrowserAgentCommand:
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    return BrowserAgentCommand(
        command_id=str(request.get("command_id") or ""),
        idempotency_key=str(request.get("idempotency_key") or ""),
        deadline=str(request.get("deadline") or ""),
        expected_page=str(request.get("expected_page") or ""),
        runtime_id=str(request.get("runtime_id") or ""),
        task_id=request.get("task_id"),
        job_id=request.get("job_id"),
        state=str(request.get("state") or ""),
        action=str(request.get("action") or ""),
        params=dict(params),
        execution_mode=str(
            request.get("execution_mode") or request.get("mode") or ""
        ),
        execution_payload_hash=request.get("execution_payload_hash"),
        step_label=step_label if step_label is not None else request.get("step_label"),
        mutation_scope_id=request.get("mutation_scope_id"),
        target_hash=request.get("target_hash"),
        authorization_fingerprint=request.get("authorization_fingerprint"),
        authorization_lease_id=request.get("authorization_lease_id"),
        authorization_lease_fingerprint=request.get(
            "authorization_lease_fingerprint"
        ),
        stage_task_facts_fingerprint=request.get("stage_task_facts_fingerprint"),
    )
