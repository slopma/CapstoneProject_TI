import os
from pathlib import Path
from dotenv import load_dotenv

_repo_root_cand = Path(__file__).resolve().parents[2]
if not (_repo_root_cand / "backend").exists() and Path("/app/app").is_dir():
    PROJECT_ROOT = Path("/app")
else:
    PROJECT_ROOT = _repo_root_cand

DATA_DIR = (
    PROJECT_ROOT / "data"
    if (PROJECT_ROOT == Path("/app") and (PROJECT_ROOT / "data").is_dir())
    else PROJECT_ROOT / "backend" / "data"
)
load_dotenv(PROJECT_ROOT / ".env")


def _path_from_env(name: str, default: Path) -> Path:
    env_val = os.getenv(name)
    if env_val:
        return Path(env_val).expanduser()
    return default


def _origins_from_env() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000,*")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


INVENTORY_PATH = _path_from_env(
    "INVENTORY_PATH",
    PROJECT_ROOT / "inventory" / "onprem-enterprise-example.json",
)
AWS_OUTPUT_PATH = _path_from_env(
    "AWS_OUTPUT_PATH",
    PROJECT_ROOT / "generated" / "aws" / "main.tf",
)
CORS_ORIGINS = _origins_from_env()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
API_HOST = os.getenv("HOST", os.getenv("API_HOST", "0.0.0.0"))
API_PORT = int(os.getenv("PORT", os.getenv("API_PORT", "8000")))
FRONTEND_PORT = int(os.getenv("FRONTEND_PORT", "3000"))
DEFAULT_DB_PORT = int(os.getenv("DB_PORT", "5432"))
