from __future__ import annotations

import hashlib
from copy import deepcopy

from src import db, repository as repository_module
from src.repository import Repository
from src.batch_edit.plan_snapshot_store import PlanSnapshotStore
from src.batch_edit.plan_snapshot_compiler import plan_snapshot_sha256
from src.batch_edit.frozen_execution_contract import build_content_finalize_policy, frozen_scope_field_bindings
from src.execution import batch_dispatch_authority as authority, mutation_dispatch_ledger as ledger_module
from src.execution.browser_agent_protocol import build_frozen_product_target_identity
from src.execution.batch_command_contract import build_path_b_save1_discovery_profile
from src.execution.controlled_mutation_dispatch import ControlledMutationDispatch
from src.execution.mutation_dispatch_ledger import MutationDispatchLedger
from src.execution.v1_runner import V1TaskRunner
from src.real_dxm_write_scope import (REAL_DXM_WRITE_SCOPE_SCHEMA, REAL_DXM_WRITE_APPROVAL_SCHEMA,
    canonical_sha256, prepare_real_dxm_write_scope, prepare_real_dxm_write_approval)
from src.state_machine.batch_draft_authorization import build_batch_draft_save_task_facts, build_authorization_context


NOW = "2026-08-31T00:01:00Z"
ISSUED_AT = "2026-08-31T00:00:00Z"
APPROVED_AT = "2026-08-31T00:00:30Z"
EXPIRES_AT = "2026-08-31T00:10:00Z"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest().upper()
HASH_A, HASH_B, HASH_C, HASH_D = (value * 64 for value in "ABCD")
GIT_HEAD = "1" * 40


def _scope_facts(*, task_id: int = 701) -> dict:
    products = []
    for ordinal, product_id in enumerate((8101, 8102, 8103), start=1):
        products.append(
            {
                "ordinal": ordinal,
                "productId": product_id,
                "allowedFields": [
                    {
                        "field": "title",
                        "saveStage": "SAVE1",
                        "preimageSha256": HASH_A,
                        "expectedSha256": HASH_B,
                    },
                    {
                        "field": "semi_goods",
                        "saveStage": "SAVE2",
                        "preimageSha256": HASH_C,
                        "expectedSha256": HASH_D,
                    },
                ],
                "saves": [
                    {"stage": "SAVE1", "maxPhysicalRequests": 1},
                    {"stage": "SAVE2", "maxPhysicalRequests": 1},
                ],
            }
        )
    return {
        "schema": REAL_DXM_WRITE_SCOPE_SCHEMA,
        "stage": "execute",
        "path": "B",
        "issuedAt": ISSUED_AT,
        "expiresAt": EXPIRES_AT,
        "nonce": "scope-nonce-00000001",
        "account": {"accountContextHash": HASH_A},
        "shop": {"shopId": 91, "shopName": "Contract Shop"},
        "snapshot": {
            "snapshotId": 601,
            "snapshotSha256": HASH_B,
            "taskId": task_id,
        },
        "git": {"head": GIT_HEAD},
        "worktree": {
            "schema": "dxm.git-worktree.identity.v1",
            "git_head": GIT_HEAD,
            "git_dirty": False,
            "status_count": 0,
            "status_sha256": EMPTY_SHA256,
            "execution_file_count": 12,
            "execution_tree_sha256": HASH_C,
        },
        "runtime": {
            "runtimeInstanceId": "backend-runtime-contract",
            "browserRuntimeId": "browser-runtime-contract",
            "browserSessionId": "persistent-session-contract",
        },
        "l2": {"status": "passed", "evidenceFingerprint": HASH_D},
        "orderedProducts": products,
        "publishAllowed": False,
        "maxPhysicalRequestsPerSave": 1,
    }


def _prepared_scope(*, task_id: int = 701) -> dict:
    return prepare_real_dxm_write_scope(_scope_facts(task_id=task_id), now=NOW)


def _approval_facts(scope: dict) -> dict:
    return {
        "schema": REAL_DXM_WRITE_APPROVAL_SCHEMA,
        "stage": "execute",
        "scopeSha256": scope["scopeSha256"],
        "nonce": scope["nonce"],
        "approvedAt": APPROVED_AT,
        "expiresAt": scope["expiresAt"],
        "approvedBy": "contract-operator",
        "decision": "APPROVE",
    }


def _prepared_approval(scope: dict) -> dict:
    return prepare_real_dxm_write_approval(
        _approval_facts(scope),
        scope=scope,
        now=NOW,
    )


def _shared_required_editor_actions_plan():
    return {
        "id": 71, "name": "共享动作合同", "version": "1.0.0", "shop_id": "91",
        "category_ids": ["17"], "path": "B", "configuration_contract": "local_plan_template.v3",
        "status": "draft", "source_snapshots": {}, "dxm_template_refs": [],
        "fixed_values": {"publish_allowed": False, "field_values": {"17": {}}},
        "fill_rules": {"17": {}}, "source_policies": {"17": {}},
        "field_mappings": {"17": {"mapping_version": "1.0.0", "entries": [{
            "field_key": "title", "ui_label_zh": "标题", "ui_binding": "dxm_editor:title",
            "category_schema_path": "$.properties.title",
        }]}},
        "editor_actions": {"17": {
            "video": {"enabled": True, "failure_strategy": "pause", "max_wait_seconds": 300, "poll_interval_seconds": 5},
            "wholesale": {"enabled": True, "min_quantity": 3, "discount_percent": 10, "deduction_method": "payment"},
            "translation": {"enabled": True, "translate_type": "normal", "direction": "zh_en",
                            "apply_to": ["title", "attributes", "description_pc", "description_mobile", "custom_name"]},
            "description": {"editor": "new", "generate_mobile_from_pc": True, "confirm_before_save": True},
            "marketing_images": {"generate_from_product_images": True, "required_slots": ["1:1_white_background", "3:4_scene"]},
        }},
        "validation_policy": {"required_fields": "fail_closed", "natural_language": "english_before_save"},
        "exception_policy": {"unknown": "stop_batch"}, "provenance": "pure contract only",
    }



def content_dispatch_case(monkeypatch):
    """通过实际冻结、批准、作用域与 ledger 入口准备临时内容动作事务。"""
    # 仅构造临时库合同，不接浏览器、业务响应或保存回执。
    for module, name in ((repository_module, 'now_iso'), (authority, 'utc_now_iso'), (ledger_module, 'utc_now_iso'), (ledger_module, 'now_iso')):
        monkeypatch.setattr(module, name, lambda: NOW)
    repo = Repository()
    store = repo.create_store('Contract Shop', 'AliExpress')
    products = [81010001, 81010002, 81010003]
    actions = _shared_required_editor_actions_plan()['editor_actions']['17']
    values = {'title': 'Shared input', 'videoUrl': '', 'bulkOrder': 3, 'semi_goods': 2}
    properties = {key: {'type': 'string' if isinstance(value, str) else 'integer',
        'ui_binding': 'dxm_editor:'+key, 'ui_section': 'semi_managed' if key == 'semi_goods' else 'basic_info'}
        for key, value in values.items()}
    properties['title']['natural_language'] = True
    properties['videoUrl']['ui_control'] = 'media'
    schema = {'type': 'object', 'properties': properties}
    mapping = {'mapping_version': 'unit.content.v1', 'entries': [{'field_key': key, 'ui_binding': definition['ui_binding'],
        'ui_label_zh': '字段', 'category_schema_path': '$.properties.'+key,
        **({'delegated_to': 'content_finalize.'+('video' if key == 'videoUrl' else 'translation')} if key in {'videoUrl', 'title'} else {})}
        for key, definition in properties.items()]}
    resolution = {'resolved_fields': [{'field_key': key, 'resolved_value': value} for key, value in values.items() if key != 'semi_goods'],
        'unresolved_fields': [], 'price_validation': {}}
    items = []
    for product in products:
        target = build_frozen_product_target_identity(product_id=str(product), store_name=store['name'],
            source_urls=[f'https://detail.1688.com/offer/{product}.html'])
        item = {'product_id': str(product), 'shop_id': str(store['id']), 'categoryId': '17',
            'target_identity': target, 'target_identity_sha256': canonical_sha256(target),
            'current_value_snapshot': deepcopy(values), 'category_schema': {'normalized_schema': schema, 'schema_hash': canonical_sha256(schema)},
            'field_mapping': {**mapping, 'mapping_hash': canonical_sha256(mapping)},
            'resolution_result': {**resolution, 'resolution_hash': canonical_sha256(resolution)},
            'real_write_stage_fields': {'SAVE1': ['title', 'videoUrl', 'bulkOrder'], 'SAVE2': ['semi_goods']}}
        item['content_finalize_policy'] = build_content_finalize_policy(item, editor_actions=actions, source_sha256=HASH_B)
        semi_policy = {'schema': 'dxm.deferred_save2_policy.v1', 'freeze_timing': 'after_native_gate', 'source_sha256': HASH_B,
            'fields': [{'field_key': 'semi_goods', 'ui_binding': 'dxm_editor:semi_goods', 'ui_label_zh': '字段',
                'property_schema': properties['semi_goods'], 'rule': {'value': 2}}]}
        item['deferred_save2'] = {**semi_policy, 'policy_sha256': canonical_sha256(semi_policy)}
        items.append(item)
    body = {'schema': 'dxm_batch_draft_save_plan.v1', 'mode': 'batch_draft_save', 'path': 'B', 'shop_scope': str(store['id']),
        'publish_allowed': False, 'local_plan_template': {'id': 71, 'version': '1.0.0'}, 'plan_content_sha256': HASH_B,
        'editor_actions': {'17': actions}, 'product_ids': [str(value) for value in products], 'item_snapshots': items,
        'session_context': {'session_ref': 'unit-reader', 'account_ref_hash': HASH_A, 'shop_id': str(store['id']), 'shop_name': store['name']}}
    plan = {**body, 'snapshot_hash': plan_snapshot_sha256(body)}
    row = PlanSnapshotStore().freeze_with_task(plan, idempotency_key='unit-content-dispatch')
    facts = _scope_facts(task_id=row['task_id'])
    facts.update(schema='real_dxm_write_scope.v3', shop={'shopId': store['id'], 'shopName': store['name']},
        snapshot={'snapshotId': row['id'], 'snapshotSha256': plan['snapshot_hash'], 'taskId': row['task_id']})
    for scoped, product, item in zip(facts['orderedProducts'], products, items):
        scoped.update(productId=product, allowedFields=frozen_scope_field_bindings(item))
    scope = prepare_real_dxm_write_scope(facts, now=NOW)
    assert repo.prepare_real_dxm_write_scope(scope)['ok'] is True
    assert repo.consume_real_dxm_write_approval(scope=scope, approval=_prepared_approval(scope))['ok'] is True
    task = repo.get_task_private(row['task_id'])
    from src.execution.batch_command_contract import build_path_b_save1_discovery_profile, validate_path_b_save1_discovery_dispatch, BatchCommandContractError
    profile = build_path_b_save1_discovery_profile(task, target_product_id=products[0], scope_sha256=scope['scopeSha256'],
        approval_sha256=task['payload']['real_dxm_write_authorization']['approval_sha256'], discovery_key_sha256=HASH_C)
    task['payload']['real_dxm_path_b_discovery'] = profile
    with db.connection() as conn:
        conn.execute('UPDATE tasks SET payload_json=? WHERE id=?', (db.dumps(task['payload']), task['id']))
    stages = build_batch_draft_save_task_facts(task_id=task['id'], store_id=store['id'], product_ids=products,
        plan_snapshot_id=row['id'], plan_snapshot_hash=plan['snapshot_hash'], path='B',
        real_authorization=task['payload']['real_dxm_write_authorization'])
    context = build_authorization_context(stage_task_facts=stages, runtime_instance_id=facts['runtime']['runtimeInstanceId'],
        browser_session_id=facts['runtime']['browserSessionId'], git_head=GIT_HEAD, worktree_identity=facts['worktree'],
        l2_evidence_fingerprint=HASH_D, approved_by='contract-operator')
    assert repo.approve_and_start_task_with_authorization(task['id'], token='unit-only', confirmation='CONFIRM_DXM_SAVE_ONLY',
        approved_by='contract-operator', authorization_context=context, lease_id='unit-parent', issued_at=ISSUED_AT,
        consumed_at=NOW, expires_at='2026-08-31T00:04:00Z').ok is True
    live = authority.LiveDispatchFacts(runtime_instance_id=facts['runtime']['runtimeInstanceId'],
        browser_runtime_id=facts['runtime']['browserRuntimeId'], browser_session_id=facts['runtime']['browserSessionId'],
        git_head=GIT_HEAD, worktree_identity=facts['worktree'], l2_status='passed', l2_evidence_fingerprint=HASH_D, account_ref_hash=HASH_A)
    current_live = [live]
    ledger = MutationDispatchLedger(recover_inflight=False, live_facts_provider=lambda: current_live[0])
    dispatch = ControlledMutationDispatch(ledger=ledger)
    runner = V1TaskRunner(repo, None)
    monkeypatch.setattr(runner, '_browser_agent_runtime_id', lambda: live.browser_runtime_id)
    original_leases = deepcopy(task['payload']['real_dxm_write_authorization']['save_leases'])
    return {"repository": repo, "store": store, "products": products, "scope": scope,
            "task": task, "live": live, "current_live": current_live, "ledger": ledger,
            "dispatch": dispatch, "runner": runner, "original_leases": original_leases}
