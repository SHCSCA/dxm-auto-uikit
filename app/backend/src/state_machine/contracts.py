from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ExecutionMode(StrEnum):
    PROBE = "probe"
    DRY_RUN = "dry_run"
    CLAIM_ONLY = "claim_only"
    SINGLE_SAVE = "single_save"
    BATCH_SAVE = "batch_save"
    BATCH_DRAFT_SAVE = "batch_draft_save"


FORBIDDEN_EXECUTION_MODES = frozenset(
    {
        "publish",
        "continue_publish",
        "save_and_publish",
    }
)


class StateName(StrEnum):
    INIT = "INIT"
    PRECHECK_CONFIG = "PRECHECK_CONFIG"
    PRECHECK_SESSION = "PRECHECK_SESSION"
    PRECHECK_SELECTOR_PROFILE = "PRECHECK_SELECTOR_PROFILE"
    PRECHECK_PUBLISH_GUARD = "PRECHECK_PUBLISH_GUARD"
    OPEN_DATA_ACQUISITION = "OPEN_DATA_ACQUISITION"
    CLAIM_TO_DRAFT_BOX = "CLAIM_TO_DRAFT_BOX"
    VERIFY_DRAFT_BOX_CLAIM = "VERIFY_DRAFT_BOX_CLAIM"
    OPEN_DRAFT_LIST = "OPEN_DRAFT_LIST"
    FIND_PRODUCT = "FIND_PRODUCT"
    ITEM_LOCKING = "ITEM_LOCKING"
    ITEM_LOCKED = "ITEM_LOCKED"
    CLAIM_PRODUCT = "CLAIM_PRODUCT"
    VERIFY_LIST_OWNERSHIP = "VERIFY_LIST_OWNERSHIP"
    OPEN_EDIT_PAGE = "OPEN_EDIT_PAGE"
    VERIFY_EDIT_OWNERSHIP = "VERIFY_EDIT_OWNERSHIP"
    FILL_BASE_INFO = "FILL_BASE_INFO"
    FILL_VARIANTS = "FILL_VARIANTS"
    FILL_MEDIA = "FILL_MEDIA"
    FILL_COMPLIANCE = "FILL_COMPLIANCE"
    ENABLE_SEMI_MANAGED = "ENABLE_SEMI_MANAGED"
    OPEN_SEMI_MANAGED_PAGE = "OPEN_SEMI_MANAGED_PAGE"
    FILL_SEMI_GOODS = "FILL_SEMI_GOODS"
    FILL_SEMI_VARIANTS = "FILL_SEMI_VARIANTS"
    PRE_SAVE_GUARD_CHECK = "PRE_SAVE_GUARD_CHECK"
    SAVE_ONLY = "SAVE_ONLY"
    VERIFY_SAVE_RESULT = "VERIFY_SAVE_RESULT"
    VERIFY_NOT_PUBLISHED = "VERIFY_NOT_PUBLISHED"
    WRITE_REPORT = "WRITE_REPORT"
    RELEASE_LOCK = "RELEASE_LOCK"
    DONE = "DONE"
    FAILED = "FAILED"
    CAPTURE_EVIDENCE = "CAPTURE_EVIDENCE"
    WRITE_EXCEPTION = "WRITE_EXCEPTION"
    STOP_OR_NEXT_PRODUCT = "STOP_OR_NEXT_PRODUCT"
    # 批量保存专属状态
    BATCH_VIDEO_CHECK = "BATCH_VIDEO_CHECK"
    BATCH_VIDEO_SELECT = "BATCH_VIDEO_SELECT"
    BATCH_VIDEO_SUBMIT = "BATCH_VIDEO_SUBMIT"
    BATCH_VIDEO_POLL = "BATCH_VIDEO_POLL"
    BATCH_VIDEO_PLACE = "BATCH_VIDEO_PLACE"
    BATCH_WHOLESALE_FILL = "BATCH_WHOLESALE_FILL"
    BATCH_TRANSLATE_CHECK = "BATCH_TRANSLATE_CHECK"
    BATCH_TRANSLATE_EXECUTE = "BATCH_TRANSLATE_EXECUTE"
    BATCH_SEMI_CHECK = "BATCH_SEMI_CHECK"
    BATCH_SEMI_MODAL = "BATCH_SEMI_MODAL"
    BATCH_SEMI_COUNTRY = "BATCH_SEMI_COUNTRY"
    BATCH_SEMI_BATCH_FILL = "BATCH_SEMI_BATCH_FILL"
    BATCH_SEMI_SAVE = "BATCH_SEMI_SAVE"
    BATCH_ROLLBACK = "BATCH_ROLLBACK"
    # Path B 双保存合同专属状态：SAVE1 后由原生门裁决（"编辑半托管信息"）；
    # 由此进入 /web/smt/editFromSmt 完成半托管并触发 SAVE2。
    SAVE_INTENT_MODAL = "SAVE_INTENT_MODAL"
    SAVE2_ONLY = "SAVE2_ONLY"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    retryable_error_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")


@dataclass(frozen=True)
class StateNodeSpec:
    state_name: StateName
    preconditions: tuple[str, ...]
    actions: tuple[str, ...]
    expected_url: tuple[str, ...] = ()
    expected_text: tuple[str, ...] = ()
    expected_dom: tuple[str, ...] = ()
    expected_network: tuple[str, ...] = ()
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    failure_code: str = "E999"
    evidence_required: tuple[str, ...] = ("screenshot", "dom_snapshot")
    publish_guard_required: bool = True
    ownership_required: bool = True

    def validate(self) -> None:
        if not self.preconditions:
            raise ValueError(f"{self.state_name} must declare preconditions")
        if not self.actions:
            raise ValueError(f"{self.state_name} must declare actions")
        if not self.failure_code:
            raise ValueError(f"{self.state_name} must declare failure_code")
        if not self.evidence_required:
            raise ValueError(f"{self.state_name} must require evidence")


def normalize_execution_mode(mode: str) -> ExecutionMode:
    normalized = mode.strip().lower()
    if normalized in FORBIDDEN_EXECUTION_MODES:
        raise ValueError(f"execution mode is forbidden: {normalized}")
    return ExecutionMode(normalized)


def build_v1_state_specs() -> dict[StateName, StateNodeSpec]:
    specs = {
        StateName.PRECHECK_CONFIG: StateNodeSpec(
            state_name=StateName.PRECHECK_CONFIG,
            preconditions=("task payload exists",),
            actions=("validate store, templates, mode, publish rules",),
            failure_code="E302",
            ownership_required=False,
        ),
        StateName.PRECHECK_SESSION: StateNodeSpec(
            state_name=StateName.PRECHECK_SESSION,
            preconditions=("config precheck passed",),
            actions=("verify local dianxiaomi login state",),
            expected_text=("products navigation visible",),
            failure_code="E101",
            ownership_required=False,
        ),
        StateName.PRECHECK_PUBLISH_GUARD: StateNodeSpec(
            state_name=StateName.PRECHECK_PUBLISH_GUARD,
            preconditions=("session is usable",),
            actions=("verify forbidden publish modes and visible publish risks",),
            failure_code="E999",
            ownership_required=False,
        ),
        StateName.OPEN_DATA_ACQUISITION: StateNodeSpec(
            state_name=StateName.OPEN_DATA_ACQUISITION,
            preconditions=("session is usable", "publish guard passed"),
            actions=("open dianxiaomi existing claimable product list",),
            expected_url=("/web/productCrawl/dataAcquisition",),
            expected_text=("已有待认领商品", "认领"),
            failure_code="E201",
            ownership_required=False,
        ),
        StateName.CLAIM_TO_DRAFT_BOX: StateNodeSpec(
            state_name=StateName.CLAIM_TO_DRAFT_BOX,
            preconditions=("existing claimable product list is open", "target claimable product is unique"),
            actions=("claim target existing product to draft box",),
            expected_text=("认领", "采集箱"),
            failure_code="E202",
            ownership_required=False,
        ),
        StateName.VERIFY_DRAFT_BOX_CLAIM: StateNodeSpec(
            state_name=StateName.VERIFY_DRAFT_BOX_CLAIM,
            preconditions=("claim to draft box completed",),
            actions=("open draft box and verify claimed product exists",),
            expected_url=("/web/smt/smtProductList/draft",),
            expected_dom=("unique claimed draft row",),
            failure_code="E202",
            ownership_required=False,
        ),
        StateName.OPEN_DRAFT_LIST: StateNodeSpec(
            state_name=StateName.OPEN_DRAFT_LIST,
            preconditions=("session is usable", "publish guard passed"),
            actions=("open smt draft list",),
            expected_url=("/web/smt/smtProductList/draft",),
            failure_code="E201",
            ownership_required=False,
        ),
        StateName.FIND_PRODUCT: StateNodeSpec(
            state_name=StateName.FIND_PRODUCT,
            preconditions=("draft list is open", "task filter is configured"),
            actions=("locate unique target product row",),
            expected_dom=("unique product row",),
            failure_code="E201",
            ownership_required=False,
        ),
        StateName.ITEM_LOCKING: StateNodeSpec(
            state_name=StateName.ITEM_LOCKING,
            preconditions=("target product row is unique",),
            actions=("create or refresh local ownership lock",),
            failure_code="E202",
            publish_guard_required=False,
        ),
        StateName.CLAIM_PRODUCT: StateNodeSpec(
            state_name=StateName.CLAIM_PRODUCT,
            preconditions=("local ownership lock acquired",),
            actions=("write task claim mark to product row remark",),
            expected_text=("claim mark visible",),
            failure_code="E202",
        ),
        StateName.VERIFY_LIST_OWNERSHIP: StateNodeSpec(
            state_name=StateName.VERIFY_LIST_OWNERSHIP,
            preconditions=("claim action completed",),
            actions=("read product row claim mark and compare lock token context",),
            expected_text=("task claim mark visible",),
            failure_code="E202",
        ),
        StateName.OPEN_EDIT_PAGE: StateNodeSpec(
            state_name=StateName.OPEN_EDIT_PAGE,
            preconditions=("list ownership verified",),
            actions=("open product edit page",),
            expected_dom=("edit form visible",),
            failure_code="E901",
        ),
        StateName.VERIFY_EDIT_OWNERSHIP: StateNodeSpec(
            state_name=StateName.VERIFY_EDIT_OWNERSHIP,
            preconditions=("edit page is open",),
            actions=("compare store, title, sku or product id against task payload",),
            failure_code="E202",
        ),
        StateName.PRE_SAVE_GUARD_CHECK: StateNodeSpec(
            state_name=StateName.PRE_SAVE_GUARD_CHECK,
            preconditions=("semi managed fields are filled", "edit ownership verified"),
            actions=("scan visible buttons, modals, url and pending network risks",),
            failure_code="E999",
        ),
        StateName.SAVE_ONLY: StateNodeSpec(
            state_name=StateName.SAVE_ONLY,
            preconditions=("pre save publish guard passed",),
            actions=("click save button only",),
            expected_text=("edit success", "saved to pending publish"),
            expected_network=("save response code is success",),
            failure_code="E802",
        ),
        StateName.VERIFY_NOT_PUBLISHED: StateNodeSpec(
            state_name=StateName.VERIFY_NOT_PUBLISHED,
            preconditions=("save result verified",),
            actions=("record published=false proof",),
            failure_code="E999",
        ),
        StateName.WRITE_REPORT: StateNodeSpec(
            state_name=StateName.WRITE_REPORT,
            preconditions=("item reached terminal status",),
            actions=("write item report with evidence and published=false",),
            failure_code="E802",
            publish_guard_required=False,
        ),
        StateName.RELEASE_LOCK: StateNodeSpec(
            state_name=StateName.RELEASE_LOCK,
            preconditions=("report is written or item failed",),
            actions=("release local ownership lock",),
            failure_code="E202",
            publish_guard_required=False,
        ),
        # 批量保存专属状态规格
        StateName.BATCH_VIDEO_CHECK: StateNodeSpec(
            state_name=StateName.BATCH_VIDEO_CHECK,
            preconditions=("batch product list is loaded",),
            actions=("check video field status for batch products",),
            failure_code="E601",
        ),
        StateName.BATCH_VIDEO_SELECT: StateNodeSpec(
            state_name=StateName.BATCH_VIDEO_SELECT,
            preconditions=("video check completed", "products without video identified"),
            actions=("select video source for batch products",),
            failure_code="E602",
        ),
        StateName.BATCH_VIDEO_SUBMIT: StateNodeSpec(
            state_name=StateName.BATCH_VIDEO_SUBMIT,
            preconditions=("video selections confirmed",),
            actions=("submit video batch upload request",),
            failure_code="E603",
        ),
        StateName.BATCH_VIDEO_POLL: StateNodeSpec(
            state_name=StateName.BATCH_VIDEO_POLL,
            preconditions=("video submit request sent",),
            actions=("poll video upload status",),
            failure_code="E604",
        ),
        StateName.BATCH_VIDEO_PLACE: StateNodeSpec(
            state_name=StateName.BATCH_VIDEO_PLACE,
            preconditions=("video upload completed",),
            actions=("place video into product video fields",),
            failure_code="E605",
        ),
        StateName.BATCH_WHOLESALE_FILL: StateNodeSpec(
            state_name=StateName.BATCH_WHOLESALE_FILL,
            preconditions=("batch products in edit context",),
            actions=("fill wholesale price tiers for batch products",),
            failure_code="E606",
        ),
        StateName.BATCH_TRANSLATE_CHECK: StateNodeSpec(
            state_name=StateName.BATCH_TRANSLATE_CHECK,
            preconditions=("batch products selected",),
            actions=("check translation status for batch products",),
            failure_code="E607",
        ),
        StateName.BATCH_TRANSLATE_EXECUTE: StateNodeSpec(
            state_name=StateName.BATCH_TRANSLATE_EXECUTE,
            preconditions=("translation check completed",),
            actions=("execute batch translation",),
            failure_code="E608",
        ),
        StateName.BATCH_SEMI_CHECK: StateNodeSpec(
            state_name=StateName.BATCH_SEMI_CHECK,
            preconditions=("batch products in semi-managed context",),
            actions=("check semi-managed mode compatibility",),
            failure_code="E609",
        ),
        StateName.BATCH_SEMI_MODAL: StateNodeSpec(
            state_name=StateName.BATCH_SEMI_MODAL,
            preconditions=("semi check passed",),
            actions=("open semi-managed batch modal",),
            failure_code="E610",
        ),
        StateName.BATCH_SEMI_COUNTRY: StateNodeSpec(
            state_name=StateName.BATCH_SEMI_COUNTRY,
            preconditions=("semi modal opened",),
            actions=("select batch country settings",),
            failure_code="E611",
        ),
        StateName.BATCH_SEMI_BATCH_FILL: StateNodeSpec(
            state_name=StateName.BATCH_SEMI_BATCH_FILL,
            preconditions=("country selected",),
            actions=("fill semi-managed batch fields",),
            failure_code="E612",
        ),
        StateName.BATCH_SEMI_SAVE: StateNodeSpec(
            state_name=StateName.BATCH_SEMI_SAVE,
            preconditions=("semi batch fields filled",),
            actions=("save batch semi-managed changes",),
            failure_code="E613",
        ),
        StateName.BATCH_ROLLBACK: StateNodeSpec(
            state_name=StateName.BATCH_ROLLBACK,
            preconditions=("batch operation failed",),
            actions=("rollback batch changes",),
            failure_code="E699",
        ),
    }
    for spec in specs.values():
        spec.validate()
    return specs
