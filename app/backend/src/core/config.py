import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ["DXM_DATA_DIR"]).expanduser().resolve() if os.environ.get("DXM_DATA_DIR") else BASE_DIR.parent.parent / "data"
SQLITE_DIR = DATA_DIR / "sqlite"
EVIDENCE_DIR = DATA_DIR / "evidences"
SCREENSHOT_DIR = DATA_DIR / "screenshots"
SESSION_DIR = DATA_DIR / "sessions"
AI_DIR = DATA_DIR / "ai"
DB_PATH = SQLITE_DIR / "dxm_auto_uikit.db"
TITLE_AI_CONFIG_FILE = AI_DIR / "title-ai.json"

for path in [DATA_DIR, SQLITE_DIR, EVIDENCE_DIR, SCREENSHOT_DIR, SESSION_DIR, AI_DIR]:
    path.mkdir(parents=True, exist_ok=True)
