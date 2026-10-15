import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support.acceptance_export_case import public_acceptance_export


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts/report/generate_v1_acceptance_record.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_v1_acceptance_record", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _export_bytes(exported):
    return json.dumps(exported, ensure_ascii=False).encode("utf-8")


def _run_cli(*args, input_bytes=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *map(str, args)],
        input=input_bytes, capture_output=True, check=False, timeout=15,
    )


def test_generate_v1_acceptance_record_covers_required_evidence(tmp_path):
    module = _load_generator()
    exported = public_acceptance_export()
    source_bytes = _export_bytes(exported)
    export_path = tmp_path / "private-source-name.json"
    export_path.write_bytes(source_bytes)

    loaded, loaded_bytes, source_name = module.load_public_export(export_path)
    record = module.build_acceptance_record(
        loaded, source_bytes=loaded_bytes, source_name=source_name,
    )

    assert record["schemaVersion"] == "real_dxm_path_b_acceptance_record.v1"
    assert record["verdict"] == "REAL_PATH_B_3_ACCEPTED"
    assert record["ready"] is True
    assert record["blockers"] == []
    assert record["sourceManifest"] == {
        "sourceKind": "public_api_export_json", "sizeBytes": len(source_bytes),
        "sha256": hashlib.sha256(source_bytes).hexdigest().upper(),
        "apiSchemaVersion": "real_dxm_path_b_acceptance_export.v1",
    }
    assert record["task"]["mode"] == "batch_draft_save"
    assert record["task"]["path"] == "B"
    assert [item["ordinal"] for item in record["orderedProducts"]] == [1, 2, 3]
    assert len(record["saveReceipts"]) == len(record["mutationLedger"]) == 6
    assert {item["stage"] for item in record["saveReceipts"]} == {"SAVE1", "SAVE2"}
    assert all(item["persisted"] is True for item in record["saveReceipts"])
    assert set(record["capabilities"]) == {
        "video", "wholesale", "translation", "semi_managed", "rollback_preparation",
    }
    assert all(item["status"] == "passed" for item in record["capabilities"].values())
    assert record["zeroPublish"] == {
        "allowed": False, "requestCount": 0, "published": False,
        "finalReadbackPublished": False,
    }
    assert record["campaign"]["totals"]["physicalMutation"] == 7
    assert record["campaign"]["discovery"]["leafProofCount"] == 5
    assert record["writerFence"]["released"] is True
    assert all(item["passed"] is True for item in record["checks"])

    rendered = json.dumps(record)
    for field in ("productId", "jobId", "commandId", "leaseId", "shopId", "browserSessionId"):
        assert f'"{field}"' not in rendered
    for private_value in ("private-source-name", "private-session-test", "private-command-", "private-lease-"):
        assert private_value not in rendered
    assert record["task"]["taskRefSha256"] == hashlib.sha256(b"task:42").hexdigest().upper()


@pytest.mark.parametrize("transport", ["file", "stdin"])
def test_acceptance_cli_consumes_public_export_and_writes_json(tmp_path, transport):
    source_bytes = _export_bytes(public_acceptance_export())
    source_path = tmp_path / "public-export.json"
    source_path.write_bytes(source_bytes)
    output_path = tmp_path / "record.json"
    result = _run_cli(
        "--input", "-" if transport == "stdin" else source_path, "--output", output_path,
        input_bytes=source_bytes if transport == "stdin" else None,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8")
    assert result.stdout == b""
    assert result.stderr.strip() == b"REAL_PATH_B_3_ACCEPTED"
    assert json.loads(output_path.read_bytes())["ready"] is True


@pytest.mark.parametrize("drift,expected_check", [
    ("unpersisted", "SIX_CANONICAL_RECEIPTS"),
    ("missing_proof", "SIX_CANONICAL_RECEIPTS"),
    ("ledger_authority", "MUTATION_LEDGER_EXACT"),
    ("wrong_order", "THREE_PRODUCTS_ORDERED"),
    ("published", "ZERO_PUBLISH"),
    ("chronology", "DISCOVERY_FORMAL_CAMPAIGN_BOUND"),
])
def test_export_claim_cannot_override_missing_or_inconsistent_evidence(drift, expected_check):
    module = _load_generator()
    exported = public_acceptance_export()
    if drift == "unpersisted":
        exported["saveReceipts"][0]["persisted"] = False
    elif drift == "missing_proof":
        exported["saveReceipts"][0].pop("unpublishedReadbackSha256")
    elif drift == "ledger_authority":
        exported["mutationLedger"][0]["commandId"] = "different-command"
    elif drift == "wrong_order":
        exported["orderedProducts"].reverse()
    elif drift == "published":
        exported["publish"]["published"] = True
    elif drift == "chronology":
        exported["campaign"]["chronology"]["formalTaskCreatedAt"] = "2026-08-30T00:00:00Z"
    record = module.build_acceptance_record(
        exported, source_bytes=_export_bytes(exported), source_name="public.json",
    )
    assert record["ready"] is False
    assert record["verdict"] == "INTERNAL_NON_READY"
    assert expected_check in {item["code"] for item in record["blockers"]}


def test_non_ready_cli_preserves_redacted_blockers_without_claiming_success(tmp_path):
    exported = public_acceptance_export()
    exported["blockers"] = [{"code": "private title token=secret", "message": "private-note"}]
    result = _run_cli("--input", "-", input_bytes=_export_bytes(exported))
    record = json.loads(result.stdout)
    assert result.returncode == 2
    assert record["ready"] is False
    assert {item["code"] for item in record["blockers"]} == {"INVALID_BLOCKER_CODE", "NO_BLOCKERS"}
    assert b"INTERNAL_NON_READY" in result.stderr
    assert b"private" not in result.stdout
    assert b"secret" not in result.stdout


def test_sqlite_input_is_rejected_without_database_access(tmp_path, monkeypatch, capsys):
    module = _load_generator()
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE reports (summary_json TEXT)")
        connection.execute("INSERT INTO reports VALUES ('private-legacy-report')")
    original_bytes = db_path.read_bytes()

    def reject_connection(*_args, **_kwargs):
        pytest.fail("离线生成器不得绕过公共投影读取数据库")

    monkeypatch.setattr(sqlite3, "connect", reject_connection)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT_PATH), "--input", str(db_path)])
    assert module.main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ACCEPTANCE_INPUT_REJECTED" in captured.err
    assert "private-legacy-report" not in captured.err
    assert db_path.read_bytes() == original_bytes
    assert not hasattr(module, "generate_markdown")


def test_cli_rejects_legacy_database_and_report_selectors(tmp_path):
    source_path = tmp_path / "public.json"
    source_path.write_bytes(_export_bytes(public_acceptance_export()))
    result = _run_cli("--input", source_path, "--db", tmp_path / "legacy.db", "--report-id", 11)
    assert result.returncode == 2
    assert result.stdout == b""
    assert b"unrecognized arguments" in result.stderr
