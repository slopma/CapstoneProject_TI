import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _path_from_env(name: str, default: Path) -> Path:
    return Path(os.getenv(name, str(default))).expanduser()


def _origins_from_env() -> list[str]:
    return [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]


INVENTORY_PATH = _path_from_env(
    "INVENTORY_PATH",
    PROJECT_ROOT / "inventory" / "onprem-example.json",
)
AWS_OUTPUT_PATH = _path_from_env(
    "AWS_OUTPUT_PATH",
    PROJECT_ROOT / "generated" / "aws" / "main.tf",
)
CORS_ORIGINS = _origins_from_env()