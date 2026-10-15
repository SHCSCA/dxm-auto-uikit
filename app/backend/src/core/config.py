from pathlib import Path

from src.core.config_bus import get_config_bus

BASE_DIR = Path(__file__).resolve().parents[2]
RUNTIME_CONFIG = get_config_bus().runtime(BASE_DIR)
DATA_DIR = RUNTIME_CONFIG.paths.data_dir
SQLITE_DIR = RUNTIME_CONFIG.paths.sqlite_dir
EVIDENCE_DIR = RUNTIME_CONFIG.paths.evidence_dir
SCREENSHOT_DIR = RUNTIME_CONFIG.paths.screenshot_dir
SESSION_DIR = RUNTIME_CONFIG.paths.session_dir
AI_DIR = RUNTIME_CONFIG.paths.ai_dir
DB_PATH = SQLITE_DIR / "dxm_auto_uikit.db"
TITLE_AI_CONFIG_FILE = AI_DIR / "title-ai.json"


RUNTIME_SUBDIRECTORIES = (
    SQLITE_DIR,
    EVIDENCE_DIR,
    SCREENSHOT_DIR,
    SESSION_DIR,
    AI_DIR,
)


def ensure_runtime_directories(data_dir: Path | None = None) -> None:
    """只在运行所有权建立后创建运行目录。"""

    paths = (
        RUNTIME_SUBDIRECTORIES
        if data_dir is None
        else tuple(data_dir / name for name in ("sqlite", "evidences", "screenshots", "sessions", "ai"))
    )
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
