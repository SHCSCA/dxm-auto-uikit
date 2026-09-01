"""Fail-closed canonical evidence receipts for DXM Path B.

The receipt is an acceptance contract, not a best-effort event log.  A
successful product receipt requires five capability receipts and two distinct
SAVE receipts.  Each SAVE freezes its full field readback and four-part proof
chain: network request, business-success response, page-success screenshot,
and an independent unpublished readback.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import PurePath
from typing import Any, Iterable, Mapping


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


class ReceiptValidationError(ValueError):
    """Stable fail-closed receipt validation failure."""

    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"[{reason_code}] {detail}")


class ReceiptPhase(StrEnum):
    """Receipt phase identifiers matching the Path B state machine."""

    PHASE_1_FIRST_SAVE = "phase_1_first_save"
    PHASE_2_SECOND_SAVE = "phase_2_second_save"
    CONTENT_FINALIZE_WHOLESALE = "content_finalize_wholesale"
    CONTENT_FINALIZE_VIDEO = "content_finalize_video"
    CONTENT_FINALIZE_TRANSLATION = "content_finalize_translation"
    SEMI_MANAGED_ENTRY = "semi_managed_entry"
    ROLLBACK_PREPARATION = "rollback_preparation"


class SaveProofKind(StrEnum):
    """Evidence components required for every physical SAVE."""

    # SCREENSHOT is retained for compatibility. New producers should use the
    # phase-explicit PAGE_SUCCESS_SCREENSHOT member.
    SCREENSHOT = "screenshot"
    PAGE_SUCCESS_SCREENSHOT = "page_success_screenshot"
    NETWORK_REQUEST = "network_request"
    NETWORK_RESPONSE = "network_response"
    UNPUBLISHED_STATUS = "unpublished_status"


_SAVE_PHASES = (
    ReceiptPhase.PHASE_1_FIRST_SAVE,
    ReceiptPhase.PHASE_2_SECOND_SAVE,
)
_CAPABILITY_PHASES = frozenset(
    {
        ReceiptPhase.CONTENT_FINALIZE_WHOLESALE,
        ReceiptPhase.CONTENT_FINALIZE_VIDEO,
        ReceiptPhase.CONTENT_FINALIZE_TRANSLATION,
        ReceiptPhase.SEMI_MANAGED_ENTRY,
        ReceiptPhase.ROLLBACK_PREPARATION,
    }
)
_EXPECTED_PAGE_KIND = {
    ReceiptPhase.PHASE_1_FIRST_SAVE: "editor",
    ReceiptPhase.PHASE_2_SECOND_SAVE: "semi_managed",
}


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ReceiptValidationError(
            "RECEIPT_NOT_CANONICAL_JSON",
            "receipt contains a non-canonical JSON value",
        ) from exc


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _required_text(value: Any, *, reason_code: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ReceiptValidationError(
            reason_code,
            f"{field_name} is required and must be canonical text",
        )
    return value


def _required_sha256(value: Any, *, reason_code: str, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ReceiptValidationError(reason_code, f"{field_name} must be a SHA-256 digest")
    return value.casefold()


def _parse_timestamp(value: Any, *, reason_code: str, field_name: str) -> datetime:
    text = _required_text(value, reason_code=reason_code, field_name=field_name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReceiptValidationError(reason_code, f"{field_name} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReceiptValidationError(reason_code, f"{field_name} must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _field_readback_dict(readback: "FieldReadback") -> dict[str, Any]:
    return {
        "field_key": readback.field_key,
        "field_label": readback.field_label,
        "source": readback.source,
        "before_value": readback.before_value,
        "after_value": readback.after_value,
        "readback_proven": readback.readback_proven,
        "timestamp": readback.timestamp,
    }


def _validate_field_readbacks(
    readbacks: Iterable["FieldReadback"],
    *,
    require_nonempty: bool,
    reason_prefix: str,
) -> None:
    items = list(readbacks)
    if require_nonempty and not items:
        raise ReceiptValidationError(
            f"{reason_prefix}_READBACK_REQUIRED",
            "at least one field readback is required",
        )
    seen: set[str] = set()
    for readback in items:
        if not isinstance(readback, FieldReadback):
            raise ReceiptValidationError(
                f"{reason_prefix}_READBACK_INVALID",
                "field readback has an unsupported shape",
            )
        key = _required_text(
            readback.field_key,
            reason_code=f"{reason_prefix}_READBACK_INVALID",
            field_name="field_key",
        )
        _required_text(
            readback.field_label,
            reason_code=f"{reason_prefix}_READBACK_INVALID",
            field_name=f"{key}.field_label",
        )
        _required_text(
            readback.source,
            reason_code=f"{reason_prefix}_READBACK_INVALID",
            field_name=f"{key}.source",
        )
        _parse_timestamp(
            readback.timestamp,
            reason_code=f"{reason_prefix}_READBACK_TIMESTAMP_INVALID",
            field_name=f"{key}.timestamp",
        )
        if readback.readback_proven is not True:
            raise ReceiptValidationError(
                f"{reason_prefix}_READBACK_UNPROVEN",
                f"{key} has no independent after-value readback",
            )
        if key in seen:
            raise ReceiptValidationError(
                f"{reason_prefix}_READBACK_DUPLICATE",
                f"duplicate field readback: {key}",
            )
        seen.add(key)


@dataclass
class FieldReadback:
    """Before/after readback for one governed field."""

    field_key: str
    field_label: str
    source: str
    before_value: Any | None
    after_value: Any | None
    readback_proven: bool
    timestamp: str | None

    def to_dict(self) -> dict[str, Any]:
        return _field_readback_dict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FieldReadback":
        return cls(
            field_key=payload.get("field_key"),
            field_label=payload.get("field_label"),
            source=payload.get("source"),
            before_value=payload.get("before_value"),
            after_value=payload.get("after_value"),
            readback_proven=payload.get("readback_proven") is True,
            timestamp=payload.get("timestamp"),
        )


def validated_field_readbacks_from_payload(
    value: Any,
    *,
    require_nonempty: bool,
    reason_prefix: str,
) -> list[FieldReadback]:
    """Parse exact JSON readbacks and reject omitted or surplus evidence facts."""

    expected_keys = {
        "field_key",
        "field_label",
        "source",
        "before_value",
        "after_value",
        "readback_proven",
        "timestamp",
    }
    if not isinstance(value, list) or any(
        not isinstance(item, Mapping) or set(item) != expected_keys
        for item in value
    ):
        raise ReceiptValidationError(
            f"{reason_prefix}_READBACK_INVALID",
            "field_readbacks must contain exact canonical readback objects",
        )
    readbacks = [FieldReadback.from_dict(item) for item in value]
    _validate_field_readbacks(
        readbacks,
        require_nonempty=require_nonempty,
        reason_prefix=reason_prefix,
    )
    return readbacks


@dataclass
class SaveProof:
    """One persisted, target-bound proof for a SAVE operation."""

    proof_kind: SaveProofKind
    file_path: str | None
    network_url: str | None
    network_method: str | None
    network_status: int | None
    body_sha256: str | None
    timestamp: str | None
    proven: bool = False

    # Phase-specific acceptance facts. Defaults preserve constructor
    # compatibility while validation rejects absent facts.
    evidence_id: str | None = None
    source: str | None = None
    target_hash: str | None = None
    business_success: bool | None = None
    business_code: int | str | None = None
    business_message: str | None = None
    page_kind: str | None = None
    page_success: bool | None = None
    unpublished: bool | None = None
    independent: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        kind = (
            self.proof_kind.value
            if isinstance(self.proof_kind, SaveProofKind)
            else str(self.proof_kind)
        )
        return {
            "proof_kind": kind,
            "file_path": self.file_path,
            "network_url": self.network_url,
            "network_method": self.network_method,
            "network_status": self.network_status,
            "body_sha256": self.body_sha256,
            "timestamp": self.timestamp,
            "proven": self.proven,
            "evidence_id": self.evidence_id,
            "source": self.source,
            "target_hash": self.target_hash,
            "business_success": self.business_success,
            "business_code": self.business_code,
            "business_message": self.business_message,
            "page_kind": self.page_kind,
            "page_success": self.page_success,
            "unpublished": self.unpublished,
            "independent": self.independent,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        proof_kind: SaveProofKind | str | None = None,
    ) -> "SaveProof":
        raw_kind = proof_kind if proof_kind is not None else payload.get("proof_kind")
        return cls(
            proof_kind=SaveProofKind(str(raw_kind)),
            file_path=payload.get("file_path"),
            network_url=payload.get("network_url"),
            network_method=payload.get("network_method"),
            network_status=payload.get("network_status"),
            body_sha256=payload.get("body_sha256"),
            timestamp=payload.get("timestamp"),
            proven=payload.get("proven") is True,
            evidence_id=payload.get("evidence_id"),
            source=payload.get("source"),
            target_hash=payload.get("target_hash"),
            business_success=payload.get("business_success"),
            business_code=payload.get("business_code"),
            business_message=payload.get("business_message"),
            page_kind=payload.get("page_kind"),
            page_success=payload.get("page_success"),
            unpublished=payload.get("unpublished"),
            independent=payload.get("independent"),
        )

    def evidence_identity(self) -> str:
        """Return the stable persisted evidence identity used for reuse checks."""

        if isinstance(self.evidence_id, str) and self.evidence_id.strip():
            return f"id:{self.evidence_id.strip()}"
        if isinstance(self.file_path, str) and self.file_path.strip():
            # PurePath normalizes separators without touching the filesystem.
            return f"file:{PurePath(self.file_path.strip()).as_posix().casefold()}"
        kind = (
            self.proof_kind.value
            if isinstance(self.proof_kind, SaveProofKind)
            else str(self.proof_kind)
        )
        return "event:" + _canonical_sha256(
            {
                "proof_kind": kind,
                "network_url": self.network_url,
                "network_method": self.network_method,
                "network_status": self.network_status,
                "body_sha256": self.body_sha256,
                "timestamp": self.timestamp,
                "source": self.source,
            }
        )


@dataclass
class SaveReceipt:
    """Fail-closed acceptance receipt for exactly one physical SAVE."""

    save_phase: ReceiptPhase
    save_lease_id: str
    action_grant_id: str
    proofs: dict[SaveProofKind, SaveProof] = field(default_factory=dict)
    field_readbacks: list[FieldReadback] = field(default_factory=list)
    save_result_ok: bool | None = None
    error_code: str | None = None
    error_detail: str | None = None
    unresolved: bool = False
    canonical_save_receipt_sha256: str | None = None

    # Required Path B acceptance facts. Defaults keep legacy construction
    # import-compatible, but ``finalize`` rejects missing values.
    mutation_id: str | None = None
    ledger_entry_id: int | None = None
    target_hash: str | None = None
    dispatched_at: str | None = None
    completed_at: str | None = None
    physical_mutation_count: int | None = None
    publish_request_count: int | None = None
    published: bool | None = None

    def _proof_by_kind(self) -> dict[SaveProofKind, SaveProof]:
        normalized: dict[SaveProofKind, SaveProof] = {}
        for raw_kind, proof in self.proofs.items():
            try:
                kind = (
                    raw_kind
                    if isinstance(raw_kind, SaveProofKind)
                    else SaveProofKind(str(raw_kind))
                )
            except ValueError as exc:
                raise ReceiptValidationError(
                    "SAVE_PROOF_KIND_INVALID",
                    f"unsupported proof kind: {raw_kind}",
                ) from exc
            if not isinstance(proof, SaveProof) or SaveProofKind(str(proof.proof_kind)) != kind:
                raise ReceiptValidationError(
                    "SAVE_PROOF_KIND_MISMATCH",
                    f"proof map key does not match proof payload: {kind.value}",
                )
            if kind in normalized:
                raise ReceiptValidationError("SAVE_PROOF_DUPLICATE", kind.value)
            normalized[kind] = proof
        return normalized

    def _serialize_proofs(self) -> dict[str, Any]:
        return {
            kind.value: proof.to_dict()
            for kind, proof in sorted(self._proof_by_kind().items(), key=lambda item: item[0].value)
        }

    def _serialize(self) -> dict[str, Any]:
        phase = (
            self.save_phase.value
            if isinstance(self.save_phase, ReceiptPhase)
            else str(self.save_phase)
        )
        return {
            "save_phase": phase,
            "save_lease_id": self.save_lease_id,
            "action_grant_id": self.action_grant_id,
            "mutation_id": self.mutation_id,
            "ledger_entry_id": self.ledger_entry_id,
            "target_hash": self.target_hash,
            "dispatched_at": self.dispatched_at,
            "completed_at": self.completed_at,
            "physical_mutation_count": self.physical_mutation_count,
            "publish_request_count": self.publish_request_count,
            "published": self.published,
            "save_result_ok": self.save_result_ok,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "unresolved": self.unresolved,
            "proofs": self._serialize_proofs(),
            # Complete before/after values, labels, provenance, and timestamps
            # are part of the per-save hash.
            "field_readbacks": [item.to_dict() for item in self.field_readbacks],
        }

    def compute_sha256(self) -> str:
        return _canonical_sha256(self._serialize())

    def evidence_identities(self) -> frozenset[str]:
        return frozenset(proof.evidence_identity() for proof in self._proof_by_kind().values())

    def validate_for_acceptance(self) -> None:
        try:
            phase = (
                self.save_phase
                if isinstance(self.save_phase, ReceiptPhase)
                else ReceiptPhase(str(self.save_phase))
            )
        except ValueError as exc:
            raise ReceiptValidationError("SAVE_PHASE_INVALID", str(self.save_phase)) from exc
        if phase not in _SAVE_PHASES:
            raise ReceiptValidationError("SAVE_PHASE_INVALID", phase.value)
        _required_text(
            self.save_lease_id,
            reason_code="SAVE_LEASE_REQUIRED",
            field_name="save_lease_id",
        )
        _required_text(
            self.action_grant_id,
            reason_code="SAVE_ACTION_GRANT_REQUIRED",
            field_name="action_grant_id",
        )
        _required_text(
            self.mutation_id,
            reason_code="SAVE_MUTATION_ID_REQUIRED",
            field_name="mutation_id",
        )
        target_hash = _required_sha256(
            self.target_hash,
            reason_code="SAVE_TARGET_HASH_INVALID",
            field_name="target_hash",
        )
        if (
            isinstance(self.ledger_entry_id, bool)
            or not isinstance(self.ledger_entry_id, int)
            or self.ledger_entry_id <= 0
        ):
            raise ReceiptValidationError(
                "SAVE_LEDGER_ENTRY_REQUIRED",
                "ledger_entry_id must be a positive integer",
            )
        dispatched_at = _parse_timestamp(
            self.dispatched_at,
            reason_code="SAVE_DISPATCH_TIMESTAMP_INVALID",
            field_name="dispatched_at",
        )
        completed_at = _parse_timestamp(
            self.completed_at,
            reason_code="SAVE_COMPLETION_TIMESTAMP_INVALID",
            field_name="completed_at",
        )
        if completed_at < dispatched_at:
            raise ReceiptValidationError(
                "SAVE_TIMESTAMP_ORDER_INVALID",
                "completed_at precedes dispatched_at",
            )
        if self.unresolved is not False:
            raise ReceiptValidationError("SAVE_OUTCOME_UNKNOWN", "SAVE is unresolved")
        if self.save_result_ok is not True:
            raise ReceiptValidationError(
                "SAVE_RESULT_NOT_OK",
                "SAVE result is not explicitly successful",
            )
        if self.error_code is not None or self.error_detail is not None:
            raise ReceiptValidationError(
                "SAVE_SUCCESS_HAS_ERROR",
                "successful SAVE cannot contain error fields",
            )
        if self.physical_mutation_count != 1:
            raise ReceiptValidationError(
                "SAVE_PHYSICAL_MUTATION_COUNT_INVALID",
                "physical_mutation_count must equal 1",
            )
        if self.publish_request_count != 0 or self.published is not False:
            raise ReceiptValidationError(
                "SAVE_PUBLISH_NOT_PROVEN_ABSENT",
                "SAVE requires zero publish requests and published=false",
            )

        proofs = self._proof_by_kind()
        screenshot_kinds = {
            kind
            for kind in (SaveProofKind.SCREENSHOT, SaveProofKind.PAGE_SUCCESS_SCREENSHOT)
            if kind in proofs
        }
        if len(screenshot_kinds) != 1:
            raise ReceiptValidationError(
                "SAVE_PAGE_SCREENSHOT_REQUIRED",
                "exactly one page-success screenshot proof is required",
            )
        required = {
            SaveProofKind.NETWORK_REQUEST,
            SaveProofKind.NETWORK_RESPONSE,
            SaveProofKind.UNPUBLISHED_STATUS,
        }
        missing = sorted(kind.value for kind in required if kind not in proofs)
        if missing:
            raise ReceiptValidationError("SAVE_PROOF_REQUIRED", ",".join(missing))

        for kind, proof in proofs.items():
            if proof.proven is not True:
                raise ReceiptValidationError("SAVE_PROOF_UNPROVEN", kind.value)
            proof_at = _parse_timestamp(
                proof.timestamp,
                reason_code="SAVE_PROOF_TIMESTAMP_INVALID",
                field_name=f"proofs.{kind.value}.timestamp",
            )
            if proof_at < dispatched_at or proof_at > completed_at:
                raise ReceiptValidationError(
                    "SAVE_PROOF_OUTSIDE_DISPATCH_WINDOW",
                    kind.value,
                )
            proof_target = _required_sha256(
                proof.target_hash,
                reason_code="SAVE_PROOF_TARGET_INVALID",
                field_name=f"proofs.{kind.value}.target_hash",
            )
            if proof_target != target_hash:
                raise ReceiptValidationError("SAVE_PROOF_TARGET_MISMATCH", kind.value)
            _required_text(
                proof.source,
                reason_code="SAVE_PROOF_SOURCE_REQUIRED",
                field_name=f"proofs.{kind.value}.source",
            )

        screenshot = proofs[next(iter(screenshot_kinds))]
        _required_text(
            screenshot.file_path,
            reason_code="SAVE_PAGE_SCREENSHOT_FILE_REQUIRED",
            field_name="page_success_screenshot.file_path",
        )
        _required_sha256(
            screenshot.body_sha256,
            reason_code="SAVE_PAGE_SCREENSHOT_HASH_REQUIRED",
            field_name="page_success_screenshot.body_sha256",
        )
        if screenshot.page_success is not True:
            raise ReceiptValidationError(
                "SAVE_PAGE_SUCCESS_NOT_PROVEN",
                "page-success screenshot is not explicitly successful",
            )
        if screenshot.page_kind != _EXPECTED_PAGE_KIND[phase]:
            raise ReceiptValidationError(
                "SAVE_PAGE_KIND_MISMATCH",
                f"{phase.value} requires {_EXPECTED_PAGE_KIND[phase]}",
            )
        screenshot_at = _parse_timestamp(
            screenshot.timestamp,
            reason_code="SAVE_PROOF_TIMESTAMP_INVALID",
            field_name="page_success_screenshot.timestamp",
        )

        request = proofs[SaveProofKind.NETWORK_REQUEST]
        request_url = _required_text(
            request.network_url,
            reason_code="SAVE_NETWORK_REQUEST_URL_REQUIRED",
            field_name="network_request.network_url",
        )
        if str(request.network_method or "").upper() != "POST":
            raise ReceiptValidationError(
                "SAVE_NETWORK_REQUEST_METHOD_INVALID",
                "network request must be POST",
            )
        _required_sha256(
            request.body_sha256,
            reason_code="SAVE_NETWORK_REQUEST_HASH_REQUIRED",
            field_name="network_request.body_sha256",
        )
        request_at = _parse_timestamp(
            request.timestamp,
            reason_code="SAVE_PROOF_TIMESTAMP_INVALID",
            field_name="network_request.timestamp",
        )

        response = proofs[SaveProofKind.NETWORK_RESPONSE]
        if response.network_url != request_url:
            raise ReceiptValidationError(
                "SAVE_NETWORK_PAIR_MISMATCH",
                "request and response URLs differ",
            )
        if str(response.network_method or "").upper() != "POST":
            raise ReceiptValidationError(
                "SAVE_NETWORK_RESPONSE_METHOD_INVALID",
                "network response must be bound to the POST request",
            )
        if (
            isinstance(response.network_status, bool)
            or not isinstance(response.network_status, int)
            or not 200 <= response.network_status < 300
        ):
            raise ReceiptValidationError(
                "SAVE_NETWORK_RESPONSE_STATUS_INVALID",
                "network response must be HTTP 2xx",
            )
        _required_sha256(
            response.body_sha256,
            reason_code="SAVE_NETWORK_RESPONSE_HASH_REQUIRED",
            field_name="network_response.body_sha256",
        )
        if response.business_success is not True:
            raise ReceiptValidationError(
                "SAVE_BUSINESS_SUCCESS_NOT_PROVEN",
                "HTTP success without explicit business success is rejected",
            )
        if str(response.business_code).strip() != "0":
            raise ReceiptValidationError(
                "SAVE_BUSINESS_CODE_INVALID",
                "business-success response requires business code 0",
            )
        _required_text(
            response.business_message,
            reason_code="SAVE_BUSINESS_MESSAGE_REQUIRED",
            field_name="network_response.business_message",
        )
        response_at = _parse_timestamp(
            response.timestamp,
            reason_code="SAVE_PROOF_TIMESTAMP_INVALID",
            field_name="network_response.timestamp",
        )
        if response_at < request_at:
            raise ReceiptValidationError(
                "SAVE_NETWORK_TIMESTAMP_ORDER_INVALID",
                "business response precedes its request",
            )
        if screenshot_at < response_at:
            raise ReceiptValidationError(
                "SAVE_PAGE_PROOF_TOO_EARLY",
                "page-success screenshot must be captured after business success",
            )

        unpublished = proofs[SaveProofKind.UNPUBLISHED_STATUS]
        if unpublished.unpublished is not True or unpublished.independent is not True:
            raise ReceiptValidationError(
                "SAVE_UNPUBLISHED_PROOF_NOT_INDEPENDENT",
                "unpublished status must be explicit and independently read back",
            )
        _required_sha256(
            unpublished.body_sha256,
            reason_code="SAVE_UNPUBLISHED_PROOF_HASH_REQUIRED",
            field_name="unpublished_status.body_sha256",
        )
        unpublished_at = _parse_timestamp(
            unpublished.timestamp,
            reason_code="SAVE_PROOF_TIMESTAMP_INVALID",
            field_name="unpublished_status.timestamp",
        )
        if unpublished_at < response_at:
            raise ReceiptValidationError(
                "SAVE_UNPUBLISHED_PROOF_TOO_EARLY",
                "unpublished readback must be captured after business success",
            )

        identities = [proof.evidence_identity() for proof in proofs.values()]
        if len(identities) != len(set(identities)):
            raise ReceiptValidationError(
                "SAVE_EVIDENCE_REUSED_WITHIN_PHASE",
                "proof artifacts within one SAVE must be distinct",
            )
        _validate_field_readbacks(
            self.field_readbacks,
            require_nonempty=True,
            reason_prefix="SAVE",
        )
        for readback in self.field_readbacks:
            readback_at = _parse_timestamp(
                readback.timestamp,
                reason_code="SAVE_READBACK_TIMESTAMP_INVALID",
                field_name=f"{readback.field_key}.timestamp",
            )
            if readback_at < dispatched_at or readback_at > completed_at:
                raise ReceiptValidationError(
                    "SAVE_READBACK_OUTSIDE_DISPATCH_WINDOW",
                    readback.field_key,
                )

    def validate_integrity(self) -> None:
        self.validate_for_acceptance()
        if self.canonical_save_receipt_sha256 is not None:
            expected = _required_sha256(
                self.canonical_save_receipt_sha256,
                reason_code="SAVE_RECEIPT_HASH_INVALID",
                field_name="canonical_save_receipt_sha256",
            )
            if expected != self.compute_sha256().casefold():
                raise ReceiptValidationError(
                    "SAVE_RECEIPT_FROZEN_HASH_MISMATCH",
                    "SAVE receipt changed after finalization",
                )

    def finalize(self) -> str:
        self.validate_for_acceptance()
        computed = self.compute_sha256()
        if (
            self.canonical_save_receipt_sha256 is not None
            and self.canonical_save_receipt_sha256.casefold() != computed.casefold()
        ):
            raise ReceiptValidationError(
                "SAVE_RECEIPT_FROZEN_HASH_MISMATCH",
                "SAVE receipt changed after finalization",
            )
        self.canonical_save_receipt_sha256 = computed
        return computed

    def to_dict(self) -> dict[str, Any]:
        return self._serialize() | {
            "canonical_save_receipt_sha256": self.canonical_save_receipt_sha256,
        }

    def to_persisted_dict(self) -> dict[str, Any]:
        """Return one independently hash-verified SAVE receipt record."""

        self.finalize()
        return {"schema_version": "dxm.path-b.save-receipt.v1"} | self.to_dict()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SaveReceipt":
        raw_proofs = payload.get("proofs")
        if not isinstance(raw_proofs, Mapping):
            raise ReceiptValidationError("SAVE_PROOFS_INVALID", "proofs must be an object")
        proofs: dict[SaveProofKind, SaveProof] = {}
        for raw_kind, raw_proof in raw_proofs.items():
            if not isinstance(raw_proof, Mapping):
                raise ReceiptValidationError("SAVE_PROOF_INVALID", str(raw_kind))
            kind = SaveProofKind(str(raw_kind))
            proofs[kind] = SaveProof.from_dict(raw_proof, proof_kind=kind)
        raw_readbacks = payload.get("field_readbacks")
        if not isinstance(raw_readbacks, list):
            raise ReceiptValidationError("SAVE_READBACK_INVALID", "field_readbacks must be a list")
        receipt = cls(
            save_phase=ReceiptPhase(str(payload.get("save_phase"))),
            save_lease_id=payload.get("save_lease_id"),
            action_grant_id=payload.get("action_grant_id"),
            proofs=proofs,
            field_readbacks=[FieldReadback.from_dict(item) for item in raw_readbacks],
            save_result_ok=payload.get("save_result_ok"),
            error_code=payload.get("error_code"),
            error_detail=payload.get("error_detail"),
            unresolved=payload.get("unresolved") is True,
            canonical_save_receipt_sha256=payload.get("canonical_save_receipt_sha256"),
            mutation_id=payload.get("mutation_id"),
            ledger_entry_id=payload.get("ledger_entry_id"),
            target_hash=payload.get("target_hash"),
            dispatched_at=payload.get("dispatched_at"),
            completed_at=payload.get("completed_at"),
            physical_mutation_count=payload.get("physical_mutation_count"),
            publish_request_count=payload.get("publish_request_count"),
            published=payload.get("published"),
        )
        receipt.validate_integrity()
        return receipt


@dataclass
class ContentFinalizeReceipt:
    """Receipt for one of the five mandatory Path B capabilities."""

    phase: ReceiptPhase
    action_grant_id: str
    result_ok: bool | None = None
    error_code: str | None = None
    error_detail: str | None = None
    unresolved: bool = False
    field_readbacks: list[FieldReadback] = field(default_factory=list)
    media_identity: str | None = None
    canonical_sha256: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    def _serialize(self) -> dict[str, Any]:
        phase = self.phase.value if isinstance(self.phase, ReceiptPhase) else str(self.phase)
        return {
            "phase": phase,
            "action_grant_id": self.action_grant_id,
            "result_ok": self.result_ok,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "unresolved": self.unresolved,
            "media_identity": self.media_identity,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "field_readbacks": [item.to_dict() for item in self.field_readbacks],
        }

    def validate_for_acceptance(self) -> None:
        try:
            phase = (
                self.phase
                if isinstance(self.phase, ReceiptPhase)
                else ReceiptPhase(str(self.phase))
            )
        except ValueError as exc:
            raise ReceiptValidationError("CAPABILITY_PHASE_INVALID", str(self.phase)) from exc
        if phase not in _CAPABILITY_PHASES:
            raise ReceiptValidationError("CAPABILITY_PHASE_INVALID", phase.value)
        _required_text(
            self.action_grant_id,
            reason_code="CAPABILITY_ACTION_GRANT_REQUIRED",
            field_name=f"{phase.value}.action_grant_id",
        )
        if self.result_ok is not True or self.unresolved is not False:
            raise ReceiptValidationError("CAPABILITY_NOT_PROVEN", phase.value)
        if self.error_code is not None or self.error_detail is not None:
            raise ReceiptValidationError("CAPABILITY_SUCCESS_HAS_ERROR", phase.value)
        if self.started_at is not None:
            started = _parse_timestamp(
                self.started_at,
                reason_code="CAPABILITY_TIMESTAMP_INVALID",
                field_name=f"{phase.value}.started_at",
            )
            completed = _parse_timestamp(
                self.completed_at,
                reason_code="CAPABILITY_TIMESTAMP_INVALID",
                field_name=f"{phase.value}.completed_at",
            )
            if completed < started:
                raise ReceiptValidationError("CAPABILITY_TIMESTAMP_ORDER_INVALID", phase.value)
        elif self.completed_at is not None:
            raise ReceiptValidationError("CAPABILITY_TIMESTAMP_INVALID", phase.value)
        if phase == ReceiptPhase.CONTENT_FINALIZE_VIDEO:
            _required_text(
                self.media_identity,
                reason_code="VIDEO_MEDIA_IDENTITY_REQUIRED",
                field_name="media_identity",
            )
        _validate_field_readbacks(
            self.field_readbacks,
            require_nonempty=False,
            reason_prefix="CAPABILITY",
        )

    def compute_sha256(self) -> str:
        return _canonical_sha256(self._serialize())

    def finalize(self) -> str:
        self.validate_for_acceptance()
        computed = self.compute_sha256()
        if (
            self.canonical_sha256 is not None
            and self.canonical_sha256.casefold() != computed.casefold()
        ):
            raise ReceiptValidationError(
                "CAPABILITY_RECEIPT_FROZEN_HASH_MISMATCH",
                "capability receipt changed after finalization",
            )
        self.canonical_sha256 = computed
        return computed

    def to_dict(self) -> dict[str, Any]:
        return self._serialize() | {"canonical_sha256": self.canonical_sha256}


@dataclass
class CanonicalReceipt:
    """Canonical acceptance receipt for one Path B product/job."""

    task_id: int
    job_id: int
    product_id: int | None
    mode: str
    claim_mark: str
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    canonical_receipt_sha256: str | None = None
    content_finalize_receipts: list[ContentFinalizeReceipt] = field(default_factory=list)
    save_receipts: list[SaveReceipt] = field(default_factory=list)
    all_field_readbacks: list[FieldReadback] = field(default_factory=list)
    rollback_prepared: bool = False
    rollback_preimage_sha256: str | None = None
    rollback_performed: bool = False
    rollback_success: bool | None = None
    rollback_reason: str | None = None
    job_status: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    needs_manual_review: bool = False

    def _assert_mutable(self) -> None:
        if self.canonical_receipt_sha256 is not None:
            raise ReceiptValidationError(
                "CANONICAL_RECEIPT_FROZEN",
                "receipt cannot be extended after finalization",
            )

    def add_content_finalize_receipt(self, receipt: ContentFinalizeReceipt) -> None:
        self._assert_mutable()
        if not isinstance(receipt, ContentFinalizeReceipt):
            raise ReceiptValidationError("CAPABILITY_RECEIPT_INVALID", "unsupported receipt")
        phase = (
            receipt.phase
            if isinstance(receipt.phase, ReceiptPhase)
            else ReceiptPhase(str(receipt.phase))
        )
        if any(existing.phase == phase for existing in self.content_finalize_receipts):
            raise ReceiptValidationError("CAPABILITY_RECEIPT_DUPLICATE", phase.value)
        self.content_finalize_receipts.append(receipt)
        self.all_field_readbacks.extend(receipt.field_readbacks)

    def add_save_receipt(self, receipt: SaveReceipt) -> None:
        self._assert_mutable()
        if not isinstance(receipt, SaveReceipt):
            raise ReceiptValidationError("SAVE_RECEIPT_INVALID", "unsupported receipt")
        phase = (
            receipt.save_phase
            if isinstance(receipt.save_phase, ReceiptPhase)
            else ReceiptPhase(str(receipt.save_phase))
        )
        if phase not in _SAVE_PHASES:
            raise ReceiptValidationError("SAVE_PHASE_INVALID", phase.value)
        if any(existing.save_phase == phase for existing in self.save_receipts):
            raise ReceiptValidationError("SAVE_RECEIPT_DUPLICATE", phase.value)
        expected_phase = (
            _SAVE_PHASES[len(self.save_receipts)]
            if len(self.save_receipts) < 2
            else None
        )
        if phase != expected_phase:
            raise ReceiptValidationError(
                "SAVE_PHASE_ORDER_INVALID",
                "SAVE1 must be appended before SAVE2",
            )
        self.save_receipts.append(receipt)
        self.all_field_readbacks.extend(receipt.field_readbacks)

    def mark_rollback_prepared(self, preimage_sha256: str) -> None:
        self._assert_mutable()
        self.rollback_preimage_sha256 = _required_sha256(
            preimage_sha256,
            reason_code="ROLLBACK_PREIMAGE_HASH_INVALID",
            field_name="rollback_preimage_sha256",
        )
        self.rollback_prepared = True

    def mark_rollback_performed(self, success: bool, reason: str) -> None:
        self._assert_mutable()
        self.rollback_performed = True
        self.rollback_success = success
        self.rollback_reason = reason

    def mark_unknown(self, error_code: str, error_detail: str) -> None:
        self._assert_mutable()
        self.job_status = "unknown"
        self.error_code = error_code
        self.error_detail = error_detail
        self.needs_manual_review = True

    def mark_failed(self, error_code: str, error_detail: str) -> None:
        self._assert_mutable()
        self.job_status = "failed"
        self.error_code = error_code
        self.error_detail = error_detail

    def mark_succeeded(self) -> None:
        self._assert_mutable()
        self.job_status = "succeeded"
        self.error_code = None
        self.error_detail = None
        self.needs_manual_review = False

    def _serialize(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "job_id": self.job_id,
            "product_id": self.product_id,
            "mode": self.mode,
            "claim_mark": self.claim_mark,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "job_status": self.job_status,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "needs_manual_review": self.needs_manual_review,
            "content_finalize_receipts": [
                item.to_dict() for item in self.content_finalize_receipts
            ],
            "save_receipts": [item.to_dict() for item in self.save_receipts],
            "rollback": {
                "prepared": self.rollback_prepared,
                "preimage_sha256": self.rollback_preimage_sha256,
                "performed": self.rollback_performed,
                "success": self.rollback_success,
                "reason": self.rollback_reason,
            },
            "all_field_readbacks": [item.to_dict() for item in self.all_field_readbacks],
        }

    def validate_for_acceptance(self) -> None:
        for field_name, value in (("task_id", self.task_id), ("job_id", self.job_id)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ReceiptValidationError("RECEIPT_ID_INVALID", field_name)
        if self.product_id is not None and (
            isinstance(self.product_id, bool)
            or not isinstance(self.product_id, int)
            or self.product_id <= 0
        ):
            raise ReceiptValidationError("RECEIPT_ID_INVALID", "product_id")
        if self.mode != "batch_draft_save":
            raise ReceiptValidationError("RECEIPT_MODE_INVALID", "Path B requires batch_draft_save")
        _required_text(self.claim_mark, reason_code="CLAIM_MARK_REQUIRED", field_name="claim_mark")
        started_at = _parse_timestamp(
            self.started_at,
            reason_code="RECEIPT_TIMESTAMP_INVALID",
            field_name="started_at",
        )
        completed_at = _parse_timestamp(
            self.completed_at,
            reason_code="RECEIPT_TIMESTAMP_INVALID",
            field_name="completed_at",
        )
        if completed_at < started_at:
            raise ReceiptValidationError(
                "RECEIPT_TIMESTAMP_ORDER_INVALID",
                "completion precedes start",
            )
        if self.job_status != "succeeded" or self.needs_manual_review:
            raise ReceiptValidationError("RECEIPT_JOB_NOT_SUCCEEDED", str(self.job_status))
        if self.error_code is not None or self.error_detail is not None:
            raise ReceiptValidationError("RECEIPT_SUCCESS_HAS_ERROR", "error fields are populated")

        capability_phases: list[ReceiptPhase] = []
        capability_grants: list[str] = []
        for receipt in self.content_finalize_receipts:
            receipt.validate_for_acceptance()
            phase = (
                receipt.phase
                if isinstance(receipt.phase, ReceiptPhase)
                else ReceiptPhase(str(receipt.phase))
            )
            capability_phases.append(phase)
            capability_grants.append(receipt.action_grant_id)
        if (
            len(capability_phases) != len(_CAPABILITY_PHASES)
            or set(capability_phases) != _CAPABILITY_PHASES
        ):
            missing = sorted(phase.value for phase in _CAPABILITY_PHASES - set(capability_phases))
            raise ReceiptValidationError(
                "MANDATORY_CAPABILITY_RECEIPTS_INCOMPLETE",
                ",".join(missing) or "duplicate capability phase",
            )
        if len(capability_grants) != len(set(capability_grants)):
            raise ReceiptValidationError(
                "CAPABILITY_ACTION_GRANT_REUSED",
                "capability action grants must be phase-specific",
            )
        if not self.rollback_prepared:
            raise ReceiptValidationError(
                "ROLLBACK_PREPARATION_REQUIRED",
                "rollback preimage was not prepared",
            )
        _required_sha256(
            self.rollback_preimage_sha256,
            reason_code="ROLLBACK_PREIMAGE_HASH_INVALID",
            field_name="rollback_preimage_sha256",
        )

        if len(self.save_receipts) != 2:
            raise ReceiptValidationError(
                "SAVE_RECEIPT_COUNT_INVALID",
                "exactly two SAVE receipts are required",
            )
        phases = [
            receipt.save_phase
            if isinstance(receipt.save_phase, ReceiptPhase)
            else ReceiptPhase(str(receipt.save_phase))
            for receipt in self.save_receipts
        ]
        if tuple(phases) != _SAVE_PHASES:
            raise ReceiptValidationError(
                "SAVE_PHASE_ORDER_INVALID",
                "required order is first_save then second_save",
            )
        for receipt in self.save_receipts:
            receipt.validate_for_acceptance()
        for field_name, values in {
            "save_lease_id": [item.save_lease_id for item in self.save_receipts],
            "action_grant_id": [item.action_grant_id for item in self.save_receipts],
            "mutation_id": [item.mutation_id for item in self.save_receipts],
            "ledger_entry_id": [item.ledger_entry_id for item in self.save_receipts],
        }.items():
            if len(values) != len(set(values)):
                raise ReceiptValidationError(
                    "SAVE_PHASE_AUTHORITY_REUSED",
                    f"SAVE1/SAVE2 reuse {field_name}",
                )
        first_save, second_save = self.save_receipts
        if str(first_save.target_hash).casefold() != str(second_save.target_hash).casefold():
            raise ReceiptValidationError(
                "SAVE_PHASE_TARGET_MISMATCH",
                "SAVE1 and SAVE2 must prove the same frozen product target",
            )
        first_completed_at = _parse_timestamp(
            first_save.completed_at,
            reason_code="SAVE_COMPLETION_TIMESTAMP_INVALID",
            field_name="save1.completed_at",
        )
        second_dispatched_at = _parse_timestamp(
            second_save.dispatched_at,
            reason_code="SAVE_DISPATCH_TIMESTAMP_INVALID",
            field_name="save2.dispatched_at",
        )
        if second_dispatched_at <= first_completed_at:
            raise ReceiptValidationError(
                "SAVE_PHASE_TIMESTAMP_ORDER_INVALID",
                "SAVE2 dispatch must occur after SAVE1 completed",
            )
        first_evidence = first_save.evidence_identities()
        second_evidence = second_save.evidence_identities()
        reused = sorted(first_evidence & second_evidence)
        if reused:
            raise ReceiptValidationError(
                "SAVE_PHASE_EVIDENCE_REUSED",
                ",".join(reused),
            )

        nested_readbacks = [
            readback.to_dict()
            for receipt in self.content_finalize_receipts
            for readback in receipt.field_readbacks
        ] + [
            readback.to_dict()
            for receipt in self.save_receipts
            for readback in receipt.field_readbacks
        ]
        aggregate_readbacks = [item.to_dict() for item in self.all_field_readbacks]
        if sorted(map(_canonical_json, aggregate_readbacks)) != sorted(
            map(_canonical_json, nested_readbacks)
        ):
            raise ReceiptValidationError(
                "CANONICAL_READBACK_AGGREGATE_MISMATCH",
                "all_field_readbacks must exactly match nested receipts",
            )

    def compute_sha256(self) -> str:
        return _canonical_sha256(self._serialize())

    def finalize(self) -> str:
        if self.canonical_receipt_sha256 is not None:
            self.validate_integrity()
            return self.canonical_receipt_sha256
        for receipt in self.content_finalize_receipts:
            receipt.finalize()
        for receipt in self.save_receipts:
            receipt.finalize()
        if self.completed_at is None:
            self.completed_at = datetime.now(timezone.utc).isoformat()
        self.validate_for_acceptance()
        self.canonical_receipt_sha256 = self.compute_sha256()
        return self.canonical_receipt_sha256

    def validate_integrity(self) -> None:
        self.validate_for_acceptance()
        expected = _required_sha256(
            self.canonical_receipt_sha256,
            reason_code="CANONICAL_RECEIPT_HASH_INVALID",
            field_name="canonical_receipt_sha256",
        )
        if expected != self.compute_sha256().casefold():
            raise ReceiptValidationError(
                "CANONICAL_RECEIPT_FROZEN_HASH_MISMATCH",
                "canonical receipt changed after finalization",
            )

    def save_receipt_dicts(self) -> list[dict[str, Any]]:
        """Return two independently persistable, hash-verified SAVE records."""

        return [receipt.to_persisted_dict() for receipt in self.save_receipts]

    def to_dict(self) -> dict[str, Any]:
        if self.canonical_receipt_sha256 is not None:
            self.validate_integrity()
        return self._serialize() | {
            "canonical_receipt_sha256": self.canonical_receipt_sha256,
        }

    def to_persisted_dict(self) -> dict[str, Any]:
        self.finalize()
        return {"schema_version": "dxm.path-b.canonical-receipt.v1"} | self.to_dict()


def make_field_readback(
    field_key: str,
    field_label: str,
    source: str,
    before_value: Any,
    after_value: Any,
    readback_proven: bool,
    timestamp: str | None = None,
) -> FieldReadback:
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()
    return FieldReadback(
        field_key=field_key,
        field_label=field_label,
        source=source,
        before_value=before_value,
        after_value=after_value,
        readback_proven=readback_proven,
        timestamp=timestamp,
    )


def build_save_receipt_from_verified_pair(
    *,
    save_command: Mapping[str, Any] | Any,
    ledger_entry: Mapping[str, Any],
    save_action_result: Mapping[str, Any],
    verification_action_result: Mapping[str, Any],
    expected_execution_payload: Mapping[str, Any],
    expected_verification_context: Mapping[str, Any],
) -> SaveReceipt:
    """Freeze one SAVE stage immediately after its independent VERIFY.

    A complete receipt cannot be produced in the SAVE callback because its
    unpublished proof does not exist yet.  This post-VERIFY boundary is the
    earliest causally valid persistence hook.
    """

    from src.execution.action_result_contract import (
        ActionResultContractError,
        validate_independent_save_verification_pair,
    )

    command = (
        save_command.to_payload()
        if callable(getattr(save_command, "to_payload", None))
        else dict(save_command)
        if isinstance(save_command, Mapping)
        else None
    )
    if not isinstance(command, Mapping):
        raise ReceiptValidationError("SAVE_COMMAND_INVALID", "SAVE command is required")
    state = str(command.get("state") or "")
    phase_contract = {
        "SAVE_ONLY": (
            ReceiptPhase.PHASE_1_FIRST_SAVE,
            "SAVE1",
            "editor",
            "VERIFY_SAVE1_NOT_PUBLISHED",
        ),
        "SAVE2_ONLY": (
            ReceiptPhase.PHASE_2_SECOND_SAVE,
            "SAVE2",
            "semi_managed",
            "VERIFY_SAVE2_NOT_PUBLISHED",
        ),
    }.get(state)
    if phase_contract is None or command.get("action") != "save_only":
        raise ReceiptValidationError(
            "SAVE_COMMAND_STATE_INVALID",
            "only formal SAVE1/SAVE2 commands produce acceptance stage receipts",
        )
    phase, scope_stage, expected_page, verification_state = phase_contract
    try:
        pair = validate_independent_save_verification_pair(
            save_action_result,
            verification_action_result,
            expected_page=expected_page,
            execution_mode="batch_draft_save",
            expected_execution_payload=expected_execution_payload,
            expected_verification_context=expected_verification_context,
            expected_save_command=command,
            expected_save_state=state,
            expected_verification_state=verification_state,
        )
    except ActionResultContractError as exc:
        raise ReceiptValidationError(
            "SAVE_ACTION_PAIR_INVALID",
            f"{scope_stage}:{exc.reason_code}",
        ) from exc

    save = pair["save"]
    verification = pair["verification"]
    observations = save["evidence"]["observations"]
    verification_observations = verification["evidence"]["observations"]
    raw_network = observations.get("network_save_result")
    raw_audit = observations.get("network_audit")
    raw_authorization = observations.get("mutation_authorization")
    if not all(
        isinstance(value, Mapping)
        for value in (raw_network, raw_audit, raw_authorization)
    ):
        raise ReceiptValidationError(
            "SAVE_RECEIPT_SOURCE_INCOMPLETE",
            f"{scope_stage}: structured SAVE facts are missing",
        )
    network = dict(raw_network)
    audit = dict(raw_audit)
    authorization = dict(raw_authorization)
    if (
        audit.get("mutation_request_count") != 1
        or audit.get("save_request_count") != 1
        or audit.get("other_mutation_request_count") != 0
        or audit.get("publish_request_count") != 0
    ):
        raise ReceiptValidationError(
            "SAVE_NETWORK_AUDIT_INVALID",
            f"{scope_stage}: exactly one SAVE and zero publish requests are required",
        )

    required_network_evidence = (
        "request_body_sha256",
        "response_body_sha256",
        "request_observed_at",
        "response_observed_at",
        "request_evidence_id",
        "response_evidence_id",
    )
    if any(network.get(key) in (None, "") for key in required_network_evidence):
        raise ReceiptValidationError(
            "SAVE_NETWORK_CANONICAL_EVIDENCE_MISSING",
            f"{scope_stage}: request/response hashes, times, and identities are required",
        )
    request_body_sha = _required_sha256(
        network.get("request_body_sha256"),
        reason_code="SAVE_NETWORK_REQUEST_HASH_REQUIRED",
        field_name="request_body_sha256",
    )
    response_body_sha = _required_sha256(
        network.get("response_body_sha256"),
        reason_code="SAVE_NETWORK_RESPONSE_HASH_REQUIRED",
        field_name="response_body_sha256",
    )
    request_evidence_id = _required_text(
        network.get("request_evidence_id"),
        reason_code="SAVE_NETWORK_EVIDENCE_ID_REQUIRED",
        field_name="request_evidence_id",
    )
    response_evidence_id = _required_text(
        network.get("response_evidence_id"),
        reason_code="SAVE_NETWORK_EVIDENCE_ID_REQUIRED",
        field_name="response_evidence_id",
    )
    if request_evidence_id == response_evidence_id:
        raise ReceiptValidationError(
            "SAVE_NETWORK_EVIDENCE_ID_REUSED",
            f"{scope_stage}: request and response evidence identities must differ",
        )

    save_refs = save["evidence"]["refs"]
    verification_refs = verification["evidence"]["refs"]
    if len(save_refs) != 1 or len(verification_refs) != 1:
        raise ReceiptValidationError(
            "SAVE_SCREENSHOT_CARDINALITY_INVALID",
            f"{scope_stage}: exactly one SAVE and one unpublished screenshot are required",
        )
    save_ref = save_refs[0]
    verification_ref = verification_refs[0]
    target_hash = _required_sha256(
        command.get("target_hash"),
        reason_code="SAVE_TARGET_HASH_INVALID",
        field_name="target_hash",
    )
    request_at = _parse_timestamp(
        network.get("request_observed_at"),
        reason_code="SAVE_PROOF_TIMESTAMP_INVALID",
        field_name="request_observed_at",
    )
    response_at = _parse_timestamp(
        network.get("response_observed_at"),
        reason_code="SAVE_PROOF_TIMESTAMP_INVALID",
        field_name="response_observed_at",
    )
    screenshot_at = _parse_timestamp(
        save_ref.get("captured_at"),
        reason_code="SAVE_PROOF_TIMESTAMP_INVALID",
        field_name="save_evidence.captured_at",
    )
    unpublished_at = _parse_timestamp(
        verification_ref.get("captured_at"),
        reason_code="SAVE_PROOF_TIMESTAMP_INVALID",
        field_name="unpublished_evidence.captured_at",
    )
    if not request_at <= response_at <= screenshot_at < unpublished_at:
        raise ReceiptValidationError(
            "SAVE_PROOF_TIMESTAMP_ORDER_INVALID",
            f"{scope_stage}: required order is request <= response <= page < unpublished",
        )

    raw_readbacks = observations.get("save_field_readbacks")
    if not isinstance(raw_readbacks, list) or not raw_readbacks:
        raise ReceiptValidationError(
            "SAVE_FIELD_READBACKS_MISSING",
            f"{scope_stage}: post-SAVE field readbacks are required",
        )
    readbacks = validated_field_readbacks_from_payload(
        raw_readbacks,
        require_nonempty=True,
        reason_prefix="SAVE",
    )

    ledger = dict(ledger_entry)
    mutation_id = _required_text(
        authorization.get("mutation_id"),
        reason_code="SAVE_MUTATION_ID_REQUIRED",
        field_name="mutation_id",
    )
    expected_ledger_binding = {
        "status": "DISPATCHED",
        "mutation_action": "save_only_click",
        "mutation_id": mutation_id,
        "ordinal": 1,
        "command_state": state,
        "command_action": "save_only",
        "task_id": str(command.get("task_id")),
        "job_id": str(command.get("job_id")),
        "mutation_scope_id": str(command.get("mutation_scope_id")),
        "authorization_lease_id": str(command.get("authorization_lease_id")),
        "authorization_lease_fingerprint": str(
            command.get("authorization_lease_fingerprint")
        ),
        "stage_task_facts_fingerprint": str(
            command.get("stage_task_facts_fingerprint")
        ),
        "target_hash": str(command.get("target_hash")),
        "authorization_fingerprint": str(
            command.get("authorization_fingerprint")
        ),
        "command_id": str(command.get("command_id")),
        "runtime_id": str(command.get("runtime_id")),
    }
    if any(
        ledger.get(key) != expected
        for key, expected in expected_ledger_binding.items()
    ):
        raise ReceiptValidationError(
            "SAVE_LEDGER_BINDING_MISMATCH",
            f"{scope_stage}: command, lease, and ledger differ",
        )
    command_sha256 = _canonical_sha256(command)
    save_action_result_sha256 = _canonical_sha256(save)
    if (
        str(ledger.get("command_sha256") or "").casefold()
        != command_sha256.casefold()
        or ledger.get("command_json") != _canonical_json(command)
        or str(ledger.get("save_action_result_sha256") or "").casefold()
        != save_action_result_sha256.casefold()
        or ledger.get("save_action_result_json") != _canonical_json(save)
    ):
        raise ReceiptValidationError(
            "SAVE_LEDGER_EVIDENCE_BINDING_MISMATCH",
            f"{scope_stage}: persisted command/action-result evidence differs",
        )
    ledger_id = ledger.get("id")
    if isinstance(ledger_id, bool) or not isinstance(ledger_id, int) or ledger_id <= 0:
        raise ReceiptValidationError(
            "SAVE_LEDGER_ENTRY_ID_INVALID",
            f"{scope_stage}: ledger row id is invalid",
        )
    dispatch_started_at = _required_text(
        ledger.get("dispatch_started_at"),
        reason_code="SAVE_DISPATCH_TIMESTAMP_INVALID",
        field_name="dispatch_started_at",
    )
    dispatched_at = _required_text(
        ledger.get("dispatched_at"),
        reason_code="SAVE_DISPATCH_TIMESTAMP_INVALID",
        field_name="dispatched_at",
    )
    save_success_recorded_at = _required_text(
        ledger.get("save_success_recorded_at"),
        reason_code="SAVE_SUCCESS_TIMESTAMP_INVALID",
        field_name="save_success_recorded_at",
    )
    dispatch_started_time = _parse_timestamp(
        dispatch_started_at,
        reason_code="SAVE_DISPATCH_TIMESTAMP_INVALID",
        field_name="dispatch_started_at",
    )
    dispatched_time = _parse_timestamp(
        dispatched_at,
        reason_code="SAVE_DISPATCH_TIMESTAMP_INVALID",
        field_name="dispatched_at",
    )
    recorded_time = _parse_timestamp(
        save_success_recorded_at,
        reason_code="SAVE_SUCCESS_TIMESTAMP_INVALID",
        field_name="save_success_recorded_at",
    )
    if not (
        dispatch_started_time <= dispatched_time <= recorded_time
        and dispatch_started_time <= request_at
        and screenshot_at <= recorded_time <= unpublished_at
    ):
        raise ReceiptValidationError(
            "SAVE_LEDGER_TIMESTAMP_ORDER_INVALID",
            f"{scope_stage}: ledger dispatch/success times do not contain the proof chain",
        )
    probe = verification_observations.get("fresh_probe")
    if not isinstance(probe, Mapping) or probe.get("published") is not False:
        raise ReceiptValidationError(
            "SAVE_UNPUBLISHED_PROOF_INVALID",
            f"{scope_stage}: independent unpublished readback is missing",
        )

    receipt = SaveReceipt(
        save_phase=phase,
        save_lease_id=_required_text(
            command.get("authorization_lease_id"),
            reason_code="SAVE_LEASE_REQUIRED",
            field_name="authorization_lease_id",
        ),
        action_grant_id=_required_text(
            command.get("command_id"),
            reason_code="SAVE_ACTION_GRANT_REQUIRED",
            field_name="command_id",
        ),
        mutation_id=mutation_id,
        ledger_entry_id=ledger_id,
        target_hash=target_hash,
        # The receipt window begins when the ledger enters DISPATCHING.  The
        # ledger's terminal ``dispatched_at`` is later and can precede the
        # asynchronous network/page evidence collected after the exact click.
        dispatched_at=dispatch_started_at,
        completed_at=unpublished_at.isoformat(),
        physical_mutation_count=1,
        publish_request_count=0,
        published=False,
        save_result_ok=True,
        unresolved=False,
        proofs={
            SaveProofKind.NETWORK_REQUEST: SaveProof(
                proof_kind=SaveProofKind.NETWORK_REQUEST,
                file_path=None,
                network_url=network.get("url"),
                network_method=network.get("method"),
                network_status=None,
                body_sha256=request_body_sha,
                timestamp=request_at.isoformat(),
                proven=True,
                evidence_id=request_evidence_id,
                source="visible_browser_network_request",
                target_hash=target_hash,
            ),
            SaveProofKind.NETWORK_RESPONSE: SaveProof(
                proof_kind=SaveProofKind.NETWORK_RESPONSE,
                file_path=None,
                network_url=network.get("url"),
                network_method=network.get("method"),
                network_status=network.get("status"),
                body_sha256=response_body_sha,
                timestamp=response_at.isoformat(),
                proven=True,
                evidence_id=response_evidence_id,
                source="visible_browser_network_response",
                target_hash=target_hash,
                business_success=True,
                business_code=network.get("code"),
                business_message=network.get("message") or network.get("msg"),
            ),
            SaveProofKind.PAGE_SUCCESS_SCREENSHOT: SaveProof(
                proof_kind=SaveProofKind.PAGE_SUCCESS_SCREENSHOT,
                file_path=save_ref.get("path"),
                network_url=None,
                network_method=None,
                network_status=None,
                body_sha256=save_ref.get("sha256"),
                timestamp=screenshot_at.isoformat(),
                proven=True,
                evidence_id=f"screenshot:{str(save_ref.get('sha256') or '').casefold()}",
                source="visible_browser_page_success_screenshot",
                target_hash=target_hash,
                page_kind=expected_page,
                page_success=True,
            ),
            SaveProofKind.UNPUBLISHED_STATUS: SaveProof(
                proof_kind=SaveProofKind.UNPUBLISHED_STATUS,
                file_path=verification_ref.get("path"),
                network_url=None,
                network_method=None,
                network_status=None,
                body_sha256=verification_ref.get("sha256"),
                timestamp=unpublished_at.isoformat(),
                proven=True,
                evidence_id=(
                    "screenshot:"
                    f"{str(verification_ref.get('sha256') or '').casefold()}"
                ),
                source="independent_structured_unpublished_readback",
                target_hash=target_hash,
                unpublished=True,
                independent=True,
            ),
        },
        field_readbacks=readbacks,
    )
    receipt.finalize()
    return receipt


RECEIPT_EVIDENCE_TYPE = "canonical_receipt"
SAVE_PROOF_EVIDENCE_TYPE = "save_proof"
CONTENT_FINALIZE_EVIDENCE_TYPE = "content_finalize_receipt"
