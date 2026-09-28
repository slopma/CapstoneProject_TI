import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
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
AZURE_OUTPUT_PATH = _path_from_env(
    "AZURE_OUTPUT_PATH",
    PROJECT_ROOT / "generated" / "azure" / "main.tf",
)
K8S_OUTPUT_PATH = _path_from_env(
    "K8S_OUTPUT_PATH",
    PROJECT_ROOT / "generated" / "k8s" / "manifests.yaml",
)
CORS_ORIGINS = _origins_from_env()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")