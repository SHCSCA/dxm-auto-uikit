from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit

from src.batch_edit.scope_contract import canonical_sha256


FROZEN_EXECUTION_PAYLOAD_SCHEMA = "dxm.batch_draft_save.execution_payload.v1"
# Runtime-only defaults keys attached by the Runner for Path A template Select
# writes. They must never participate in the frozen defaults equality contract.
FROZEN_EXECUTION_RUNTIME_DEFAULT_KEYS = frozenset({"_path_a_fill_context"})


class FrozenExecutionContractError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(detail)


def strip_frozen_execution_runtime_defaults(defaults: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in defaults.items()
        if key not in FROZEN_EXECUTION_RUNTIME_DEFAULT_KEYS
    }


def compile_frozen_execution_payload(
    task: Mapping[str, Any],
    job: Mapping[str, Any],
    *,
    save_stage: str = "SAVE1",
    for_save: bool = False,
) -> dict[str, Any]:
    """Compile the only values E3 may write from one frozen E2 item snapshot."""

    product_id = _positive_id_text(job.get("product_id"), "job.product_id")
    payload = task.get("payload")
    plan = payload.get("plan_snapshot") if isinstance(payload, Mapping) else None
    if not isinstance(plan, Mapping):
        _reject("FROZEN_EXECUTION_SNAPSHOT_REQUIRED", "task plan_snapshot is missing")
    item_snapshots = plan.get("item_snapshots")
    if not isinstance(item_snapshots, list):
        _reject("FROZEN_EXECUTION_ITEMS_INVALID", "plan item_snapshots must be a list")
    matches = [
        item
        for item in item_snapshots
        if isinstance(item, Mapping)
        and str(item.get("product_id") or "").strip() == product_id
    ]
    if len(matches) != 1:
        _reject(
            "FROZEN_EXECUTION_ITEM_MISMATCH",
            "current job must bind exactly one frozen item_snapshot",
        )
    item = matches[0]
    category_id = _non_empty_text(item.get("categoryId"), "categoryId")
    all_editor_actions = plan.get("editor_actions", {})
    if not isinstance(all_editor_actions, Mapping):
        _reject("FROZEN_EXECUTION_EDITOR_ACTIONS_INVALID", "editor_actions is invalid")
    target_category = item.get("target_category")
    if target_category is not None and not isinstance(target_category, Mapping):
        _reject("FROZEN_EXECUTION_TARGET_INVALID", "target_category is invalid")
    action_category_id = (
        _non_empty_text(target_category.get("category_id"), "target_category.category_id")
        if isinstance(target_category, Mapping)
        else category_id
    )
    editor_actions = all_editor_actions.get(action_category_id, {})
    if not isinstance(editor_actions, Mapping):
        _reject("FROZEN_EXECUTION_EDITOR_ACTIONS_INVALID", "category editor_actions is invalid")

    category_schema = item.get("category_schema")
    if not isinstance(category_schema, Mapping):
        _reject("FROZEN_EXECUTION_SCHEMA_REQUIRED", "category_schema is missing")
    normalized_schema = category_schema.get("normalized_schema")
    schema_hash = _sha256_text(category_schema.get("schema_hash"), "schema_hash")
    if not isinstance(normalized_schema, Mapping):
        _reject("FROZEN_EXECUTION_SCHEMA_INVALID", "normalized category schema is missing")
    if canonical_sha256(normalized_schema) != schema_hash:
        _reject("FROZEN_EXECUTION_SCHEMA_DRIFT", "category schema hash does not match")
    properties = normalized_schema.get("properties")
    if not isinstance(properties, Mapping):
        _reject("FROZEN_EXECUTION_SCHEMA_INVALID", "category schema properties are missing")

    field_mapping = item.get("field_mapping")
    if not isinstance(field_mapping, Mapping):
        _reject("FROZEN_EXECUTION_MAPPING_REQUIRED", "field_mapping is missing")
    mapping_version = _non_empty_text(
        field_mapping.get("mapping_version"),
        "mapping_version",
    )
    entries = field_mapping.get("entries")
    mapping_hash = _sha256_text(field_mapping.get("mapping_hash"), "mapping_hash")
    if not isinstance(entries, list) or not entries:
        _reject("FROZEN_EXECUTION_MAPPING_INVALID", "field mapping entries are missing")
    mapping_body = {"mapping_version": mapping_version, "entries": entries}
    if canonical_sha256(mapping_body) != mapping_hash:
        _reject("FROZEN_EXECUTION_MAPPING_DRIFT", "field mapping hash does not match")

    resolution = item.get("resolution_result")
    if not isinstance(resolution, Mapping):
        _reject("FROZEN_EXECUTION_RESOLUTION_REQUIRED", "resolution_result is missing")
    resolved_fields = resolution.get("resolved_fields")
    unresolved_fields = resolution.get("unresolved_fields")
    price_validation = resolution.get("price_validation")
    resolution_hash = _sha256_text(
        resolution.get("resolution_hash"),
        "resolution_hash",
    )
    if not isinstance(resolved_fields, list):
        _reject("FROZEN_EXECUTION_RESOLUTION_INVALID", "resolved_fields must be a list")
    if not isinstance(unresolved_fields, list) or any(
        not isinstance(value, str) or not value.strip()
        for value in unresolved_fields
    ):
        _reject("FROZEN_EXECUTION_RESOLUTION_INVALID", "unresolved_fields is invalid")
    if not isinstance(price_validation, Mapping):
        _reject("FROZEN_EXECUTION_RESOLUTION_INVALID", "price_validation is missing")
    resolution_body = {
        "resolved_fields": resolved_fields,
        "unresolved_fields": unresolved_fields,
        "price_validation": price_validation,
    }
    if canonical_sha256(resolution_body) != resolution_hash:
        _reject("FROZEN_EXECUTION_RESOLUTION_DRIFT", "resolution hash does not match")

    mappings: dict[str, dict[str, str]] = {}
    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, Mapping):
            _reject("FROZEN_EXECUTION_MAPPING_INVALID", f"mapping entry {index} is invalid")
        field_key = _non_empty_text(raw_entry.get("field_key"), "field_key")
        ui_label_zh = _non_empty_text(
            raw_entry.get("ui_label_zh"),
            "ui_label_zh",
        )
        ui_binding = _non_empty_text(raw_entry.get("ui_binding"), "ui_binding")
        schema_path = _non_empty_text(
            raw_entry.get("category_schema_path"),
            "category_schema_path",
        )
        if field_key in mappings:
            _reject("FROZEN_EXECUTION_MAPPING_INVALID", "field mapping keys are duplicated")
        if schema_path != f"$.properties.{field_key}":
            _reject("FROZEN_EXECUTION_MAPPING_INVALID", "field mapping path is unstable")
        property_schema = properties.get(field_key)
        if (
            not isinstance(property_schema, Mapping)
            or property_schema.get("ui_binding") != ui_binding
        ):
            _reject(
                "FROZEN_EXECUTION_BINDING_DRIFT",
                "field UI binding is not proven by the frozen category schema",
            )
        mappings[field_key] = {
            "ui_label_zh": ui_label_zh,
            "ui_binding": ui_binding,
            "category_schema_path": schema_path,
            **({'delegated_to': raw_entry['delegated_to']} if 'delegated_to' in raw_entry else {}),
        }

    fields: list[dict[str, Any]] = []
    seen_fields: set[str] = set()
    for index, raw_field in enumerate(resolved_fields):
        if not isinstance(raw_field, Mapping):
            _reject("FROZEN_EXECUTION_RESOLUTION_INVALID", f"resolved field {index} is invalid")
        field_key = _non_empty_text(raw_field.get("field_key"), "field_key")
        if field_key in seen_fields:
            _reject("FROZEN_EXECUTION_RESOLUTION_INVALID", "resolved field keys are duplicated")
        seen_fields.add(field_key)
        binding = mappings.get(field_key)
        if binding is None:
            _reject(
                "FROZEN_EXECUTION_BINDING_MISSING",
                f"resolved field {field_key} has no frozen UI binding",
            )
        if "resolved_value" not in raw_field:
            _reject(
                "FROZEN_EXECUTION_VALUE_MISSING",
                f"resolved field {field_key} has no value",
            )
        descriptor = {
            "field_key": field_key,
            "ui_label_zh": binding["ui_label_zh"],
            "ui_binding": binding["ui_binding"],
            "category_schema_path": binding["category_schema_path"],
            "resolved_value": deepcopy(raw_field["resolved_value"]),
        }
        if plan.get("path") == "B":
            # Preserve the winning common-plan source, not an application claim.
            # Historical missing provenance stays missing rather than being invented.
            descriptor.update({key: deepcopy(raw_field[key]) for key in ("source", "source_ref") if key in raw_field})
            if 'delegated_to' in binding:
                descriptor['delegated_to'] = binding['delegated_to']
        # Complex editor controls need an explicit runtime route.  Keeping the
        # control contract beside the frozen field prevents the visible-page
        # fallback from treating a structured object as label text.
        ui_control = properties[field_key].get("ui_control")
        if ui_control is not None:
            if not isinstance(ui_control, str) or not ui_control.strip():
                _reject(
                    "FROZEN_EXECUTION_CONTROL_INVALID",
                    f"resolved field {field_key} has an invalid ui_control",
                )
            descriptor["ui_control"] = ui_control.strip()
        fields.append(descriptor)

    unresolved = [str(value).strip() for value in unresolved_fields]
    if len(set(unresolved)) != len(unresolved) or seen_fields.intersection(unresolved):
        _reject("FROZEN_EXECUTION_RESOLUTION_INVALID", "resolution field sets overlap or duplicate")
    from src.batch_edit.plan_template_contract import PlanTemplateContractError, validate_editor_actions

    try:
        validate_editor_actions(dict(editor_actions), {field["field_key"]: field["resolved_value"] for field in fields})
    except PlanTemplateContractError as exc:
        _reject("FROZEN_EXECUTION_EDITOR_ACTIONS_INVALID", str(exc))
    body = {
        "schema": FROZEN_EXECUTION_PAYLOAD_SCHEMA,
        **({"execution_path": "B"} if plan.get("path") == "B" else {}),
        **({"dxm_template_refs": deepcopy(plan["dxm_template_refs"])}
           if plan.get("path") == "B" and "dxm_template_refs" in plan else {}),
        "product_id": product_id,
        "category_id": category_id,
        "category_schema_hash": schema_hash,
        "field_mapping_hash": mapping_hash,
        "resolution_hash": resolution_hash,
        "fields": fields,
        "unresolved_fields": unresolved,
        "price_validation": deepcopy(dict(price_validation)),
        **({"editor_actions": deepcopy(dict(editor_actions))} if editor_actions else {}),
        **(
            {"target_category": _normalized_target_category(target_category)}
            if target_category is not None
            else {}
        ),
    }
    if save_stage not in {"SAVE1", "SAVE2"}:
        _reject("FROZEN_EXECUTION_STAGE_INVALID", "unknown save stage")
    if plan.get('path') == 'B':
        content_policy = build_content_finalize_policy(
            item, editor_actions=editor_actions, source_sha256=plan.get('plan_content_sha256'))
        if item.get('content_finalize_policy') != content_policy:
            _reject('CONTENT_FINALIZE_POLICY_DRIFT', 'output ownership differs from the frozen shared plan')
        if content_policy is not None and save_stage == 'SAVE1':
            body['content_finalize_policy'] = content_policy
            if for_save:
                # Candidate hashes alone are not persisted command lineage.
                # Keep SAVE1 closed until repository-backed results are consumed.
                _reject('CONTENT_FINALIZE_STAGE_NOT_FROZEN', 'SAVE1 requires persisted, independently verified generated outputs')
    if item.get("deferred_save2") is not None:
        policy = deferred_save2_policy(item)
        if save_stage == "SAVE2":
            seal = validated_save2_stage_freeze(task, job)
            body.update(
                save_stage="SAVE2", stage_freeze_sha256=seal["freeze_sha256"],
                stage_preimage=deepcopy(seal["observation"]),
                fields=deepcopy(seal["fields"]), unresolved_fields=[],
                resolution_hash=canonical_sha256(seal["fields"]),
            )
            body.pop("editor_actions", None)
            body.pop("target_category", None)
        else:
            # A main-page command must never carry second-page values.
            deferred_keys = {field["field_key"] for field in policy["fields"]}
            if deferred_keys.intersection(field["field_key"] for field in fields):
                _reject("SAVE2_VALUES_FROZEN_EARLY", "main-page payload contains SAVE2 values")
    return {**body, "payload_hash": canonical_sha256(body)}


def build_content_finalize_policy(item, *, editor_actions, source_sha256):
    """Lock output ownership from the common mapping; never infer it from labels or current values."""
    from src.batch_edit.plan_template_contract import validate_editor_actions

    entries = item.get('field_mapping', {}).get('entries', [])
    delegated = [entry for entry in entries if isinstance(entry, Mapping) and 'delegated_to' in entry]
    if not delegated:
        return None
    source_sha256 = _sha256_text(source_sha256, 'shared plan content')
    validate_editor_actions(dict(editor_actions))
    properties = item['category_schema']['normalized_schema']['properties']
    stage_fields = item.get('real_write_stage_fields', {}).get('SAVE1', [])
    fields, keys, bindings = [], set(), set()

    def translatable(definition):
        if not isinstance(definition, Mapping) or definition.get('readOnly') is True:
            return False
        if definition.get('type') == 'string':
            return definition.get('natural_language') is True and not definition.get('enum')
        if definition.get('type') == 'array':
            return translatable(definition.get('items'))
        return definition.get('type') == 'object' and any(
            translatable(child) for child in definition.get('properties', {}).values())

    for entry in delegated:
        key, binding, owner = entry.get('field_key'), entry.get('ui_binding'), entry.get('delegated_to')
        definition = properties.get(key)
        if (not isinstance(owner, str) or owner not in {'content_finalize.video', 'content_finalize.translation'}
                or key in keys or binding in bindings or key not in stage_fields
                or not isinstance(definition, Mapping) or definition.get('readOnly') is True
                or definition.get('ui_binding') != binding or definition.get('ui_section') == 'semi_managed'):
            _reject('CONTENT_FINALIZE_BINDING_INVALID', 'generated output must own one writable frozen SAVE1 binding')
        action = owner.removeprefix('content_finalize.')
        if editor_actions.get(action, {}).get('enabled') is not True:
            _reject('CONTENT_FINALIZE_ACTION_REQUIRED', 'output owner has no enabled shared action')
        if action == 'video':
            if key != 'videoUrl' or binding != 'dxm_editor:videoUrl' or definition.get('type') != 'string' or definition.get('ui_control') != 'media':
                _reject('CONTENT_FINALIZE_VIDEO_FIELD_INVALID', 'video owner requires the proven product video field')
        elif not translatable(definition):
            _reject('CONTENT_FINALIZE_TRANSLATION_FIELD_INVALID', 'translation output needs explicit natural-language schema leaves')
        keys.add(key); bindings.add(binding)
        fields.append({'field_key': key, 'ui_binding': binding, 'delegated_to': owner,
                       'property_schema': deepcopy(dict(definition))})
    if {field['delegated_to'] for field in fields} != {'content_finalize.video', 'content_finalize.translation'}:
        _reject('CONTENT_FINALIZE_OWNERS_INCOMPLETE', 'both mandatory generated-output owners must be explicit')
    body = {'schema': 'dxm.content_finalize_policy.v1', 'source_sha256': source_sha256,
            'editor_actions_sha256': canonical_sha256(editor_actions),
            'order': ['video', 'wholesale', 'translation'], 'fields': fields}
    return {**body, 'policy_sha256': canonical_sha256(body)}


def deferred_save2_policy(item: Mapping[str, Any]) -> dict[str, Any]:
    raw = item.get("deferred_save2")
    if not isinstance(raw, Mapping) or set(raw) != {"schema", "freeze_timing", "source_sha256", "fields", "policy_sha256"}:
        _reject("SAVE2_POLICY_INVALID", "missing exact shared SAVE2 policy")
    body = {key: deepcopy(value) for key, value in raw.items() if key != "policy_sha256"}
    if (body["schema"] != "dxm.deferred_save2_policy.v1" or body["freeze_timing"] != "after_native_gate"
            or canonical_sha256(body) != raw["policy_sha256"]):
        _reject("SAVE2_POLICY_DRIFT", "shared SAVE2 policy changed")
    _sha256_text(body["source_sha256"], "shared template source")
    fields = body["fields"]
    if not isinstance(fields, list) or not fields:
        _reject("SAVE2_POLICY_INVALID", "SAVE2 policy has no fields")
    keys, bindings = set(), set()
    for field in fields:
        required = {"field_key", "ui_binding", "ui_label_zh", "property_schema", "rule"}
        if not isinstance(field, Mapping) or set(field) not in (required, required | {"source", "source_ref"}):
            _reject("SAVE2_POLICY_INVALID", "SAVE2 field rule shape is invalid")
        if "source" in field:
            _non_empty_text(field["source"], "SAVE2 source")
            _non_empty_text(field["source_ref"], "SAVE2 source reference")
        key = _non_empty_text(field["field_key"], "SAVE2 field")
        binding = _non_empty_text(field["ui_binding"], "SAVE2 binding")
        definition, rule = field["property_schema"], field["rule"]
        if (key in keys or binding in bindings or "publish" in key.casefold() or "发布" in key
                or not isinstance(definition, Mapping) or definition.get("ui_section") != "semi_managed"
                or definition.get("ui_binding") != binding or not isinstance(rule, Mapping)
                or not (set(rule) == {"value"} or rule == {"source": "current"})):
            _reject("SAVE2_POLICY_INVALID", "SAVE2 binding or shared rule is invalid")
        keys.add(key)
        bindings.add(binding)
    if keys != set(item.get("real_write_stage_fields", {}).get("SAVE2", [])):
        _reject("SAVE2_POLICY_COVERAGE_INVALID", "SAVE2 policy does not exactly cover its stage")
    return deepcopy(dict(raw))


def build_content_finalize_stage_freeze(task, job, *, observation, receipts):
    """Build an append-only result candidate, not a write grant or persisted success.

    The repository must independently bind each receipt to its actual command
    before persisting this candidate. Original inputs/preimages are never edited.
    """
    from src.batch_edit.plan_schema_contract import assert_value_matches_schema
    from src.batch_edit.plan_template_contract import HAN_PATTERN
    from src.execution.canonical_receipt import ContentFinalizeReceipt, ReceiptPhase, validated_field_readbacks_from_payload
    from src.execution.e3_authority_contract import parse_strict_utc_timestamp

    initial = compile_frozen_execution_payload(task, job)
    policy = initial.get('content_finalize_policy')
    if not isinstance(policy, Mapping) or initial.get('execution_path') != 'B':
        _reject('CONTENT_FINALIZE_POLICY_REQUIRED', 'generated outputs need the frozen shared field owners')
    plan = task['payload']['plan_snapshot']
    item = next(item for item in plan['item_snapshots'] if str(item['product_id']) == str(job['product_id']))
    scope_hash = _sha256_text(task['payload'].get('real_dxm_write_authorization', {}).get('scope_sha256'), 'content scope')
    if not isinstance(observation, Mapping) or set(observation) != {
        'product_id', 'shop_id', 'browser_session_id', 'page_url', 'target_identity_sha256',
        'observed_at', 'values', 'bindings', 'write_attempted', 'evidence_ref',
    }:
        _reject('CONTENT_FINALIZE_OBSERVATION_INVALID', 'missing exact post-action observation')
    page = urlsplit(observation['page_url'])
    if (str(observation['product_id']) != str(job['product_id']) or str(observation['shop_id']) != str(item['shop_id'])
            or observation['target_identity_sha256'] != item['target_identity_sha256']
            or observation['write_attempted'] is not False or page.scheme != 'https' or page.netloc != 'www.dianxiaomi.com'
            or page.path != '/web/smt/edit' or page.fragment or parse_qs(page.query).get('id') != [str(job['product_id'])]):
        _reject('CONTENT_FINALIZE_OBSERVATION_IDENTITY_DRIFT', 'result observation belongs to a different page/target')
    _non_empty_text(observation['browser_session_id'], 'content browser session')
    observed_at = parse_strict_utc_timestamp(observation['observed_at'], field='content observed_at')
    expected = {field['field_key']: field['resolved_value'] for field in initial['fields']}
    bindings = {field['field_key']: field['ui_binding'] for field in initial['fields']}
    values = observation['values']
    if (not isinstance(values, Mapping) or set(values) != set(expected) or len(expected) != len(initial['fields'])
            or observation['bindings'] != bindings):
        _reject('CONTENT_FINALIZE_READBACK_INCOMPLETE', 'every frozen field must be independently read back')
    owners = {field['field_key']: field for field in policy['fields']}
    for key in set(expected) - set(owners):
        if canonical_sha256(values[key]) != canonical_sha256(expected[key]):
            _reject('CONTENT_FINALIZE_UNDELEGATED_FIELD_CHANGED', 'an action changed a field it does not own')

    def translated(before, after, definition):
        if definition.get('readOnly') is not True and definition.get('natural_language') is True and definition.get('type') == 'string':
            if not isinstance(after, str) or HAN_PATTERN.search(after):
                _reject('CONTENT_FINALIZE_TRANSLATION_NOT_ENGLISH', 'translated text is not an English-save result')
            return
        if definition.get('readOnly') is not True and isinstance(before, dict) and isinstance(after, dict) and set(before) == set(after):
            for key in before:
                translated(before[key], after[key], definition.get('properties', {}).get(key, {}))
            return
        if definition.get('readOnly') is not True and isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
            for left, right in zip(before, after):
                translated(left, right, definition.get('items', {}))
            return
        if canonical_sha256(before) != canonical_sha256(after):
            _reject('CONTENT_FINALIZE_TRANSLATION_STRUCTURE_CHANGED', 'translation changed an ID, non-text value or structure')

    for key, descriptor in owners.items():
        assert_value_matches_schema(values[key], descriptor['property_schema'], field_key=key)
        if descriptor['delegated_to'] == 'content_finalize.translation':
            translated(expected[key], values[key], descriptor['property_schema'])
        elif urlsplit(values[key]).scheme not in {'http', 'https'} or not urlsplit(values[key]).netloc:
            _reject('CONTENT_FINALIZE_VIDEO_IDENTITY_INVALID', 'generated product video must have an actual media URL')
    if not isinstance(receipts, Mapping) or set(receipts) != {'video', 'wholesale', 'translation'}:
        _reject('CONTENT_FINALIZE_RECEIPTS_INCOMPLETE', 'all three ordered action receipts are mandatory')
    grants, previous_completion = set(), None
    for action in policy['order']:
        wrapper = receipts[action]
        if not isinstance(wrapper, Mapping) or set(wrapper) != {'canonical_receipt', 'receipt_sha256'}:
            _reject('CONTENT_FINALIZE_RECEIPT_INVALID', 'action receipt wrapper is incomplete')
        raw = wrapper['canonical_receipt']
        if not isinstance(raw, Mapping) or set(raw) != {
            'phase', 'action_grant_id', 'result_ok', 'error_code', 'error_detail', 'unresolved',
            'media_identity', 'started_at', 'completed_at', 'field_readbacks', 'canonical_sha256',
        }:
            _reject('CONTENT_FINALIZE_RECEIPT_INVALID', 'action receipt is incomplete')
        fields = validated_field_readbacks_from_payload(raw['field_readbacks'], require_nonempty=True, reason_prefix='CONTENT_FINALIZE')
        receipt = ContentFinalizeReceipt(**{key: value for key, value in raw.items() if key not in {'field_readbacks', 'phase'}},
            phase=ReceiptPhase(raw['phase']), field_readbacks=fields)
        digest = receipt.finalize()
        start = parse_strict_utc_timestamp(raw['started_at'], field='content action start')
        end = parse_strict_utc_timestamp(raw['completed_at'], field='content action end')
        if (raw['phase'] != 'content_finalize_'+action or digest != wrapper['receipt_sha256']
                or raw['canonical_sha256'] != digest or raw['action_grant_id'] in grants
                or (previous_completion is not None and start < previous_completion) or end > observed_at
                or any(not start <= parse_strict_utc_timestamp(field.timestamp, field='content field readback') <= end for field in fields)):
            _reject('CONTENT_FINALIZE_RECEIPT_LINEAGE_INVALID', 'action order, unique grant, timestamp or digest differs')
        grants.add(raw['action_grant_id']); previous_completion = end
        if action == 'wholesale':
            if {field.field_key for field in fields} != {'bulkOrder', 'bulkDiscount', 'reduceStrategy', 'aeopAeProductSKUs'} or any(
                    canonical_sha256(field.before_value) != canonical_sha256(field.after_value) for field in fields):
                _reject('CONTENT_FINALIZE_WHOLESALE_READBACK_INVALID', 'wholesale finalization must be a complete zero-write validation')
            continue
        owned = {key for key, descriptor in owners.items() if descriptor['delegated_to'] == 'content_finalize.'+action}
        if {field.field_key for field in fields} != owned or any(
                canonical_sha256(field.before_value) != canonical_sha256(expected[field.field_key])
                or canonical_sha256(field.after_value) != canonical_sha256(values[field.field_key]) for field in fields):
            _reject('CONTENT_FINALIZE_OWNER_READBACK_MISMATCH', 'the sole owner did not prove every delegated field')
        if action == 'video' and receipt.media_identity != values['videoUrl']:
            _reject('CONTENT_FINALIZE_VIDEO_IDENTITY_INVALID', 'generated and placed media are not the same identity')
    ref = observation['evidence_ref']
    if (not isinstance(ref, Mapping) or set(ref) != {'path', 'sha256', 'size'}
            or not isinstance(ref['path'], str) or not ref['path'].strip() or type(ref['size']) is not int or ref['size'] <= 0):
        _reject('CONTENT_FINALIZE_EVIDENCE_INVALID', 'post-action screenshot descriptor is missing')
    _sha256_text(ref['sha256'], 'content screenshot')
    body = {'schema': 'dxm.content_finalize_stage_freeze.v1', 'task_id': task['id'], 'job_id': job['id'],
        'product_id': job['product_id'], 'snapshot_sha256': plan['snapshot_hash'], 'scope_sha256': scope_hash,
        'policy_sha256': policy['policy_sha256'], 'initial_execution_payload_hash': initial['payload_hash'],
        'observation': deepcopy(dict(observation)), 'receipts': deepcopy(dict(receipts)),
        'fields': [{**deepcopy(field), 'resolved_value': deepcopy(values[field['field_key']])} for field in initial['fields']]}
    return {**body, 'freeze_sha256': canonical_sha256(body)}


def frozen_scope_field_bindings(item: Mapping[str, Any], *, stage_freeze=None) -> list[dict[str, Any]]:
    """Single projection for Prepare, dispatch and acceptance; no missing-to-null conversion."""
    stages = item.get("real_write_stage_fields", {})
    current = item.get("current_value_snapshot", {})
    resolved = {field["field_key"]: field for field in item.get("resolution_result", {}).get("resolved_fields", [])}
    policy = deferred_save2_policy(item) if item.get("deferred_save2") is not None else None
    content = item.get('content_finalize_policy')
    content_fields = {}
    delegated = {entry['field_key']: entry['delegated_to'] for entry in item.get('field_mapping', {}).get('entries', []) if 'delegated_to' in entry}
    if delegated and content is None:
        _reject('CONTENT_FINALIZE_POLICY_REQUIRED', 'delegated fields cannot fall back to fixed expected hashes')
    if content is not None:
        required = {'schema', 'source_sha256', 'editor_actions_sha256', 'order', 'fields', 'policy_sha256'}
        if (not isinstance(content, Mapping) or set(content) != required
                or content['schema'] != 'dxm.content_finalize_policy.v1'
                or not isinstance(content['fields'], list) or not content['fields']
                or content['order'] != ['video', 'wholesale', 'translation']
                or canonical_sha256({key: value for key, value in content.items() if key != 'policy_sha256'}) != content['policy_sha256']):
            _reject('CONTENT_FINALIZE_POLICY_DRIFT', 'shared output policy changed before scope projection')
        _sha256_text(content['source_sha256'], 'content shared source')
        _sha256_text(content['editor_actions_sha256'], 'content shared actions')
        properties = item.get('category_schema', {}).get('normalized_schema', {}).get('properties', {})
        for field in content['fields']:
            if (not isinstance(field, Mapping) or set(field) != {'field_key', 'ui_binding', 'delegated_to', 'property_schema'}
                    or field['field_key'] in content_fields or field['field_key'] not in stages.get('SAVE1', [])
                    or field['property_schema'] != properties.get(field['field_key'])
                    or field['ui_binding'] != properties.get(field['field_key'], {}).get('ui_binding')):
                _reject('CONTENT_FINALIZE_POLICY_DRIFT', 'shared output bindings changed')
            content_fields[field['field_key']] = field
        if ({key: field['delegated_to'] for key, field in content_fields.items()} != delegated
                or set(delegated.values()) != {'content_finalize.video', 'content_finalize.translation'}):
            _reject('CONTENT_FINALIZE_POLICY_DRIFT', 'shared output owners changed')
    result = []
    for stage in ("SAVE1", "SAVE2"):
        keys = stages.get(stage)
        if not isinstance(keys, list) or not keys:
            _reject("REAL_WRITE_STAGE_EMPTY", "both save stages require explicit fields")
        for key in keys:
            if stage == "SAVE2" and policy is not None:
                if stage_freeze is None:
                    result.append({"field": key, "saveStage": stage, "freezeAt": "after_native_gate", "ruleSha256": policy["policy_sha256"]})
                else:
                    result.append({"field": key, "saveStage": stage,
                                   "preimageSha256": canonical_sha256(stage_freeze["observation"]["values"][key]),
                                   "expectedSha256": canonical_sha256(next(field["resolved_value"] for field in stage_freeze["fields"] if field["field_key"] == key))})
            else:
                if key not in current or key not in resolved or "resolved_value" not in resolved[key]:
                    _reject("REAL_WRITE_PREIMAGE_FACT_MISSING", f"missing exact preimage/expected for {key}")
                if key in content_fields:
                    result.append({'field': key, 'saveStage': 'SAVE1', 'freezeAt': 'after_content_finalize',
                        'delegatedTo': content_fields[key]['delegated_to'], 'ruleSha256': content['policy_sha256'],
                        'preimageSha256': canonical_sha256(current[key]),
                        'inputSha256': canonical_sha256(resolved[key]['resolved_value'])})
                    continue
                result.append({"field": key, "saveStage": stage, "preimageSha256": canonical_sha256(current[key]),
                               "expectedSha256": canonical_sha256(resolved[key]["resolved_value"])})
    if len({field["field"] for field in result}) != len(result):
        _reject("REAL_WRITE_STAGE_COVERAGE_INVALID", "duplicate stage fields")
    return result


def build_save2_stage_freeze(task, job, *, observation, gate, save1_receipt_sha256):
    """Resolve the locked shared rules from a zero-write second-page observation.

    The caller must prove the native gate and persisted SAVE1 receipt before
    taking this observation. Persistence/dispatch revalidate their lineage.
    """
    from src.batch_edit.plan_schema_contract import assert_value_matches_schema

    plan = task["payload"]["plan_snapshot"]
    matches = [item for item in plan["item_snapshots"] if str(item["product_id"]) == str(job["product_id"])]
    if len(matches) != 1:
        _reject("SAVE2_TARGET_MISMATCH", "SAVE2 item is not unique")
    item = matches[0]
    policy = deferred_save2_policy(item)
    authorization = task["payload"].get("real_dxm_write_authorization", {})
    scope_hash = _sha256_text(authorization.get("scope_sha256"), "SAVE2 scope")
    _sha256_text(save1_receipt_sha256, "SAVE1 receipt")
    if (not isinstance(gate, Mapping) or gate.get("gate_outcome") != "admitted"
            or gate.get("same_handshake") is not True or gate.get("semi_entry_triggered") is not True
            or not isinstance(gate.get("handshake_id"), str) or not gate["handshake_id"].strip()
            or gate.get("blocked") is not False):
        _reject("SAVE2_NATIVE_GATE_REQUIRED", "native gate has not admitted this handshake")
    if not isinstance(observation, Mapping) or set(observation) != {
        "product_id", "shop_id", "browser_session_id", "page_url", "target_identity_sha256",
        "observed_at", "values", "bindings", "write_attempted", "evidence_ref",
    }:
        _reject("SAVE2_OBSERVATION_INVALID", "SAVE2 observation shape is invalid")
    page = urlsplit(observation["page_url"])
    if (str(observation["product_id"]) != str(job["product_id"])
            or str(observation["shop_id"]) != str(item["shop_id"])
            or observation["target_identity_sha256"] != item["target_identity_sha256"]
            or observation["write_attempted"] is not False
            or page.scheme != "https" or page.netloc != "www.dianxiaomi.com"
            or page.path != "/web/smt/editFromSmt"
            or parse_qs(page.query).get("id") != [str(job["product_id"])]):
        _reject("SAVE2_OBSERVATION_IDENTITY_INVALID", "SAVE2 observation is not the admitted zero-write page")
    _non_empty_text(observation["browser_session_id"], "browser session")
    from src.execution.e3_authority_contract import parse_strict_utc_timestamp
    parse_strict_utc_timestamp(observation["observed_at"], field="SAVE2 observed_at")
    values = observation["values"]
    expected_bindings = {field["field_key"]: field["ui_binding"] for field in policy["fields"]}
    if not isinstance(values, Mapping) or set(values) != set(expected_bindings) or observation["bindings"] != expected_bindings:
        _reject("SAVE2_PREIMAGE_INCOMPLETE", "every SAVE2 field must have a real value and unique binding")
    fields = []
    for field in policy["fields"]:
        key, rule = field["field_key"], field["rule"]
        value = deepcopy(rule["value"] if "value" in rule else values[key])
        assert_value_matches_schema(value, field["property_schema"], field_key=key)
        fields.append({"field_key": key, "ui_binding": field["ui_binding"], "ui_label_zh": field["ui_label_zh"],
                       "category_schema_path": f"$.properties.{key}", "resolved_value": value,
                       **{name: deepcopy(field[name]) for name in ("source", "source_ref") if name in field},
                       **({"ui_control": field["property_schema"]["ui_control"]} if "ui_control" in field["property_schema"] else {})})
    body = {"schema": "dxm.save2_stage_freeze.v1", "task_id": task["id"], "job_id": job["id"],
            "product_id": job["product_id"], "snapshot_sha256": plan["snapshot_hash"],
            "scope_sha256": scope_hash, "policy_sha256": policy["policy_sha256"],
            "save1_receipt_sha256": save1_receipt_sha256, "gate": deepcopy(dict(gate)),
            "observation": deepcopy(dict(observation)), "fields": fields}
    return {**body, "freeze_sha256": canonical_sha256(body)}


def validated_save2_stage_freeze(task, job):
    record = task.get("_save2_freezes", {}).get(str(job["id"]))
    if not isinstance(record, Mapping):
        _reject("SAVE2_STAGE_NOT_FROZEN", "second-page writes require a persisted stage freeze")
    expected = build_save2_stage_freeze(task, job, observation=record.get("observation"),
                                      gate=record.get("gate"), save1_receipt_sha256=record.get("save1_receipt_sha256"))
    if dict(record) != expected:
        _reject("SAVE2_STAGE_FREEZE_DRIFT", "second-page freeze or shared rule changed")
    return expected


def load_save2_stage_freezes(conn, task_id):
    """Read only persisted stage records; never accept a command's supplied seal."""
    from src.db import loads

    result = {}
    for row in conn.execute(
        "SELECT job_id, meta_json FROM job_evidences WHERE task_id=? AND evidence_type='path_b_save2_freeze' ORDER BY id",
        (task_id,),
    ).fetchall():
        key = str(row["job_id"])
        if key in result:
            _reject("SAVE2_STAGE_FREEZE_DUPLICATE", "multiple stage freezes exist for this job")
        result[key] = loads(row["meta_json"], {})
    return result


def validate_save2_persistence(conn, task, job, *, browser_session_id):
    """Recheck the append-only record's SAVE1 source before SAVE2 dispatch/VERIFY."""
    from src.db import loads

    record = validated_save2_stage_freeze(task, job)
    rows = conn.execute(
        "SELECT * FROM canonical_receipts WHERE task_id=? AND job_id=? AND receipt_kind='save_stage' AND save_stage='SAVE1'",
        (task['id'], job['id']),
    ).fetchall()
    source = loads(rows[0]['receipt_json'], {}) if len(rows) == 1 else {}
    digest = canonical_sha256({key: value for key, value in source.items() if key not in {'schema_version', 'canonical_receipt_sha256'}})
    if (len(rows) != 1 or not source or digest != record['save1_receipt_sha256']
            or source.get('canonical_receipt_sha256') != digest or rows[0]['canonical_receipt_sha256'] != digest
            or rows[0]['scope_sha256'] != record['scope_sha256'] or rows[0]['product_id'] != job['product_id']
            or record['observation']['browser_session_id'] != browser_session_id):
        _reject('SAVE2_PERSISTED_LINEAGE_DRIFT', 'SAVE1 receipt or browser session changed after late freeze')
    return record


def validate_save2_runtime_origin(payload, *, page_url, browser_session_id):
    """A late payload may only touch the same already-admitted browser page."""
    observation = payload.get("stage_preimage")
    if (payload.get("save_stage") != "SAVE2" or not isinstance(observation, Mapping)
            or observation.get("page_url") != page_url
            or observation.get("browser_session_id") != browser_session_id
            or observation.get("write_attempted") is not False
            or str(observation.get("product_id")) != str(payload.get("product_id"))):
        _reject("SAVE2_RUNTIME_ORIGIN_DRIFT", "late freeze no longer belongs to this page/session")
    _sha256_text(payload.get("stage_freeze_sha256"), "SAVE2 stage freeze")
    fields = payload.get("fields", [])
    bindings = {field["field_key"]: field["ui_binding"] for field in fields}
    if (not fields or len(bindings) != len(fields) or observation.get("bindings") != bindings
            or not isinstance(observation.get("values"), Mapping) or set(observation["values"]) != set(bindings)
            or canonical_sha256({key: value for key, value in payload.items() if key != "payload_hash"}) != payload.get("payload_hash")):
        _reject("SAVE2_RUNTIME_PREIMAGE_INVALID", "late payload does not bind every observed field")


def frozen_execution_defaults(execution_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Expose resolved values without consulting mutable templates or products."""

    fields = execution_payload.get("fields")
    if not isinstance(fields, list):
        _reject("FROZEN_EXECUTION_PAYLOAD_INVALID", "execution payload fields are missing")
    defaults: dict[str, Any] = {}
    for raw_field in fields:
        if not isinstance(raw_field, Mapping):
            _reject("FROZEN_EXECUTION_PAYLOAD_INVALID", "execution field is invalid")
        field_key = _non_empty_text(raw_field.get("field_key"), "field_key")
        if field_key in defaults or "resolved_value" not in raw_field:
            _reject("FROZEN_EXECUTION_PAYLOAD_INVALID", "execution field is duplicated or empty")
        defaults[field_key] = deepcopy(raw_field["resolved_value"])
    target_category = execution_payload.get("target_category")
    if isinstance(target_category, Mapping):
        current_category_id = _non_empty_text(
            execution_payload.get("category_id"),
            "execution payload category_id",
        )
        target_category_id = _non_empty_text(
            target_category.get("category_id"),
            "target_category.category_id",
        )
        if target_category_id == current_category_id and target_category.get("plan_owned") is not True:
            _reject(
                "FROZEN_EXECUTION_TARGET_INVALID",
                "target_category must differ from the current category",
            )
        category_name = target_category.get("category_name")
        if category_name not in (None, ""):
            defaults["category_keyword"] = str(category_name)
        category_match = target_category.get("category_match")
        if category_match not in (None, ""):
            defaults["category_match"] = str(category_match)
    editor_actions = execution_payload.get("editor_actions")
    if isinstance(editor_actions, Mapping) and editor_actions:
        defaults["_editor_actions"] = deepcopy(dict(editor_actions))
    defaults["_frozen_execution_payload"] = deepcopy(dict(execution_payload))
    defaults["_frozen_execution_payload_hash"] = _sha256_text(
        execution_payload.get("payload_hash"),
        "payload_hash",
    )
    return defaults


def validate_frozen_execution_defaults(
    defaults: Any,
    *,
    expected_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify the actual Runner defaults are exactly the embedded frozen payload."""

    if not isinstance(defaults, Mapping):
        _reject("FROZEN_EXECUTION_DEFAULTS_INVALID", "execution defaults must be an object")
    execution_payload = defaults.get("_frozen_execution_payload")
    if not isinstance(execution_payload, Mapping):
        _reject("FROZEN_EXECUTION_PAYLOAD_REQUIRED", "embedded execution payload is missing")
    payload_hash = _sha256_text(
        execution_payload.get("payload_hash"),
        "payload_hash",
    )
    payload_body = {
        key: deepcopy(value)
        for key, value in execution_payload.items()
        if key != "payload_hash"
    }
    if canonical_sha256(payload_body) != payload_hash:
        _reject("FROZEN_EXECUTION_PAYLOAD_DRIFT", "execution payload hash does not match")
    if _sha256_text(
        defaults.get("_frozen_execution_payload_hash"),
        "_frozen_execution_payload_hash",
    ) != payload_hash:
        _reject("FROZEN_EXECUTION_PAYLOAD_DRIFT", "defaults payload hash does not match")
    canonical_defaults = frozen_execution_defaults(execution_payload)
    if strip_frozen_execution_runtime_defaults(dict(defaults)) != canonical_defaults:
        _reject(
            "FROZEN_EXECUTION_DEFAULTS_DRIFT",
            "execution defaults differ from the embedded resolved fields",
        )
    if expected_payload is not None and dict(execution_payload) != dict(expected_payload):
        _reject(
            "FROZEN_EXECUTION_SNAPSHOT_DRIFT",
            "execution payload differs from the current frozen item snapshot",
        )
    return deepcopy(dict(execution_payload))


def _normalized_target_category(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = {
        "category_id": _positive_id_text(value.get("category_id"), "target_category.category_id"),
    }
    category_name = value.get("category_name")
    if category_name not in (None, ""):
        normalized["category_name"] = _non_empty_text(category_name, "target_category.category_name")
    category_match = value.get("category_match")
    if category_match not in (None, ""):
        normalized["category_match"] = _non_empty_text(category_match, "target_category.category_match")
    if value.get("plan_owned") is True:
        normalized["plan_owned"] = True
    return normalized


def _positive_id_text(value: Any, label: str) -> str:
    if isinstance(value, bool):
        _reject("FROZEN_EXECUTION_ID_INVALID", f"{label} must be a positive integer")
    text = str(value or "").strip()
    if not text.isdecimal() or int(text) <= 0:
        _reject("FROZEN_EXECUTION_ID_INVALID", f"{label} must be a positive integer")
    return text


def _non_empty_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        _reject("FROZEN_EXECUTION_TEXT_INVALID", f"{label} must be normalized text")
    return value


def _sha256_text(value: Any, label: str) -> str:
    text = _non_empty_text(value, label).upper()
    if len(text) != 64 or any(character not in "0123456789ABCDEF" for character in text):
        _reject("FROZEN_EXECUTION_HASH_INVALID", f"{label} must be SHA256")
    return text


def _reject(reason_code: str, detail: str) -> None:
    raise FrozenExecutionContractError(reason_code, detail)
