import io
import json
import logging

import pytest

from src.services.log_redaction import redact_text

from src.services.structured_logging import (
    StructuredLogFormatter, append_structured_log, build_log_record, log_exception, structured_log_level,
)


def test_nested_credentials_raw_documents_and_url_queries_are_redacted():
    payload = build_log_record("request_failed", component="contract", password="do-not-log",
        nested={"api_key": "private-key", "raw_body": "private document", "safe": 3},
        message="token=private-value Bearer private-bearer https://unit.invalid/path?id=private-id")
    serialized = json.dumps(payload)
    for forbidden in ("do-not-log", "private-key", "private document", "private-value", "private-bearer", "private-id"):
        assert forbidden not in serialized
    assert payload["fields"]["nested"]["safe"] == 3
    assert payload["schema"] == "dxm.log.v1"


def test_quoted_passwords_and_complete_cookie_headers_are_not_partially_retained():
    payload = build_log_record("failed", component="contract",
        detail='password="private first second"\nCookie: first=private-one; second=private-two')
    assert "private" not in json.dumps(payload)


@pytest.mark.parametrize("secret", ['prefix"private-tail', 'prefix\\private-tail', 'prefix\nprivate-tail',
    'prefix\\"private-tail', 'prefix\\\\"private-tail'])
def test_json_string_escaping_never_exposes_a_secret_suffix(secret):
    raw = json.dumps({"password": secret, "safe": "preserved"})
    sanitized = redact_text(raw)
    assert "private-tail" not in sanitized
    assert json.loads(sanitized) == {"password": "[REDACTED]", "safe": "preserved"}
    for message in ("provider: " + raw + " completed", "provider body=" + json.dumps(raw),
                    "provider: " + json.dumps({"nested": [{"api_key": secret}]})):
        assert "private-tail" not in redact_text(message)


@pytest.mark.parametrize("message", ['password="prefix\\"private-tail',
    'body="{\\"password\\":\\"prefix\\\\\\"private-tail',
    '{"password":"prefix\\\\"private-tail"}', 'password="prefix\nprivate-tail'])
def test_unknown_or_truncated_secret_formats_fail_closed(message):
    assert "private-tail" not in redact_text(message)


@pytest.mark.parametrize("message", ['password=[REDACTED]private-tail',
    'password="[REDACTED]private-tail', "password='[REDACTED]private-tail",
    'password="[REDACTED]private-tail"', 'passphrase=private-tail',
    'password=[REDACTED]private-tail {"status":"safe"} private-tail'])
def test_redaction_marker_prefix_never_authorizes_a_secret_suffix(message):
    assert "private-tail" not in redact_text(message)


@pytest.mark.parametrize("header", ["Cookie: first=private-tail", "Set-Cookie: first=private-tail",
    "Authorization: Bearer private-tail", "passphrase=private-tail"])
def test_secret_headers_inside_json_strings_keep_json_and_later_safe_fields(header):
    raw = json.dumps({"message": header, "status": "preserved", "nested": {"safe": 3}})
    sanitized = redact_text(raw)
    parsed = json.loads(sanitized)
    assert "private-tail" not in sanitized
    assert parsed["message"].endswith("[REDACTED]")
    assert parsed["status"] == "preserved" and parsed["nested"] == {"safe": 3}
    embedded = redact_text("before " + raw + " after")
    assert embedded.startswith("before ") and embedded.endswith(" after")
    assert json.loads(embedded[len("before "):-len(" after")]) == parsed
    encoded = redact_text(json.dumps(raw))
    assert json.loads(json.loads(encoded)) == parsed


def test_nonsecret_escaped_json_and_embedded_context_remain_readable():
    safe = {"path": r"C:\\runtime\\safe", "note": 'a "quoted"\nline', "status": "saved"}
    assert json.loads(redact_text(json.dumps(safe))) == safe
    message = 'before ' + json.dumps({"password": 'private"tail', "status": "saved"}) + ' after'
    sanitized = redact_text(message)
    assert sanitized.startswith('before ') and sanitized.endswith(' after')
    assert '"status": "saved"' in sanitized


def test_exception_records_diagnostics_without_changing_exception_semantics():
    stream = io.StringIO()
    logger = logging.Logger("dxm.test")
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredLogFormatter())
    logger.addHandler(handler)
    exception = RuntimeError("cookie=private-session")
    log_exception(logger, "dispatch_failed", exception, task_id=7, execution_state="unknown")
    payload = json.loads(stream.getvalue())
    assert payload["fields"]["exception_type"] == "RuntimeError"
    assert payload["fields"]["execution_state"] == "unknown"
    assert payload["fields"]["task_id"] == 7
    assert "private-session" not in stream.getvalue()
    assert str(exception) == "cookie=private-session"


def test_log_file_failure_is_recorded_on_stderr_without_faking_success(tmp_path, capsys):
    target = tmp_path / "directory"
    target.mkdir()
    assert not append_structured_log(target, "event", component="contract")
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["event"] == "log_write_failed"
    assert diagnostic["level"] == "ERROR"


def test_runtime_file_consumers_use_explicit_structured_severity(tmp_path):
    path = tmp_path / "backend.log"
    assert append_structured_log(path, "dispatch_closed", component="contract", level="ERROR", token="private")
    line = path.read_text(encoding="utf-8").strip()
    assert structured_log_level(line) == "error"
    assert "private" not in line
    assert structured_log_level("not a JSON record") is None
    assert structured_log_level('{"level":"ERROR"}') is None
