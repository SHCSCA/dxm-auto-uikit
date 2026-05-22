from pathlib import Path

from src.execution import browser_runtime


def test_chrome_launch_options_uses_env_path(monkeypatch):
    monkeypatch.setenv("DXM_CHROME_PATH", "C:/Chrome/chrome.exe")
    monkeypatch.setattr(browser_runtime.platform, "system", lambda: "Windows")

    options = browser_runtime.chrome_launch_options(headless=True)

    assert options == {
        "headless": True,
        "executable_path": "C:/Chrome/chrome.exe",
    }


def test_chrome_launch_options_allows_playwright_fallback(monkeypatch):
    monkeypatch.delenv("DXM_CHROME_PATH", raising=False)
    monkeypatch.setattr(browser_runtime.platform, "system", lambda: "Windows")
    monkeypatch.setattr(browser_runtime.shutil, "which", lambda command: None)
    monkeypatch.setattr(browser_runtime, "_known_chrome_paths", lambda: (Path("Z:/missing/chrome.exe"),))

    options = browser_runtime.chrome_launch_options(headless=False)

    assert options == {"headless": False}


def test_chrome_launch_options_adds_no_sandbox_off_windows(monkeypatch):
    monkeypatch.setenv("DXM_CHROME_PATH", "/usr/bin/google-chrome")
    monkeypatch.setattr(browser_runtime.platform, "system", lambda: "Linux")

    options = browser_runtime.chrome_launch_options(headless=True)

    assert options["executable_path"] == "/usr/bin/google-chrome"
    assert options["args"] == ["--no-sandbox"]
