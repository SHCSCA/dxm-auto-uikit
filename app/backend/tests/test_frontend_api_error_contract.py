from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
API_TS = REPO_ROOT / "app" / "frontend" / "src" / "api.ts"


def test_frontend_api_errors_hide_raw_technical_failures_from_user_messages():
    source = API_TS.read_text(encoding="utf-8")
    response_error = source[source.index("async function responseError("):source.index("function safeApiErrorMessage")]
    safe_error = source[source.index("function safeApiErrorMessage"):]

    assert "safeApiErrorMessage(" in response_error
    assert "return payload.detail" not in response_error
    assert "return payload.message" not in response_error
    assert "return text.trim()" not in response_error
    assert "Cannot switch to a different thread" in safe_error
    assert "Internal Server Error" in safe_error
    assert "Traceback" in safe_error
    assert "<html" in safe_error
    assert "本机服务处理失败" in safe_error
    assert "操作结果未确认。系统不会自动重试" in safe_error
