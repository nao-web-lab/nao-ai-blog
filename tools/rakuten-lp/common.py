"""共通処理（パス・設定・環境変数・JSON入出力・時刻）。

秘密情報(APIキー等)はこのファイルにもコードにも一切書かない。
環境変数、または config.json の env_files で指定した .env ファイル
（既存の rakuten-threads-auto/local/env/common.env。git管理外）から読み込む。
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOL_DIR.parents[1]
DATA_DIR = TOOL_DIR / "data"
CONTENT_DIR = DATA_DIR / "content"
LOG_DIR = TOOL_DIR / "logs"
PRODUCTS_DIR = REPO_ROOT / "products"
DB_PATH = DATA_DIR / "database.json"
GENERATED_LOG = LOG_DIR / "generated-products.json"
FAILED_LOG = LOG_DIR / "failed-products.json"

JST = timezone(timedelta(hours=9))

for _d in (DATA_DIR, CONTENT_DIR, LOG_DIR, PRODUCTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def now_jst() -> datetime:
    return datetime.now(JST)


def today_str() -> str:
    return now_jst().strftime("%Y-%m-%d")


def load_config() -> dict:
    return json.loads((TOOL_DIR / "config.json").read_text(encoding="utf-8"))


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_env_files(config: dict) -> None:
    """env_files の KEY=VALUE を環境変数に読み込む（既に設定済みの値は上書きしない）。"""
    for rel in config.get("env_files", []):
        path = (TOOL_DIR / rel).resolve()
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


SECRET_PARAM_RE = re.compile(r"(applicationId|accessKey|affiliateId|key)=[^&\s\"']+", re.I)


def redact(text: str) -> str:
    """ログにAPIキー等が混ざらないようにマスクする。"""
    text = SECRET_PARAM_RE.sub(lambda m: m.group(1) + "=***", str(text))
    for name in ("RAKUTEN_APPLICATION_ID", "RAKUTEN_ACCESS_KEY", "GEMINI_API_KEY"):
        v = os.getenv(name)
        if v and len(v) >= 6:
            text = text.replace(v, "***")
    return text


def append_log(path: Path, entry: dict, keep: int = 3000) -> None:
    entries = read_json(path, [])
    entries.append(entry)
    write_json(path, entries[-keep:])


def log(msg: str) -> None:
    print(f"[{now_jst().strftime('%H:%M:%S')}] {redact(msg)}", flush=True)
