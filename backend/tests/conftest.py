"""
Pytest session isolation configuration (`backend/tests/conftest.py`).

Ensures all automated tests run strictly in temporary directories so that:
1. Live host/AWS `backend/data/cloudmove_transactional.db`, `migrations_state.json`,
   `discovery_sessions/`, and `uc2_staged/` are NEVER mutated by test runs.
2. Read-only host `$HOME` sandboxes never fail test execution.
3. Temporary test artifacts under `generated/` are cleaned or isolated cleanly.
"""

from __future__ import annotations

import atexit
import os
from pathlib import Path
import shutil
import tempfile

_TEST_ISOLATION_ROOT = Path(tempfile.mkdtemp(prefix="cloudmove_pytest_"))
_TEST_DATA_DIR = _TEST_ISOLATION_ROOT / "data"
_TEST_HOME = _TEST_ISOLATION_ROOT / "home"
_TEST_DEPLOYMENTS = _TEST_ISOLATION_ROOT / "generated" / "deployments"
_TEST_STAGING = _TEST_ISOLATION_ROOT / "generated" / "staging_images"
_TEST_OSQUERY = _TEST_ISOLATION_ROOT / "osquery"

for _d in (_TEST_DATA_DIR, _TEST_HOME, _TEST_DEPLOYMENTS, _TEST_STAGING, _TEST_OSQUERY):
    _d.mkdir(parents=True, exist_ok=True)

os.environ["HOME"] = str(_TEST_HOME)
os.environ["CLOUDMOVE_DATA_DIR"] = str(_TEST_DATA_DIR)
os.environ["CLOUDMOVE_DB_PATH"] = str(_TEST_DATA_DIR / "cloudmove_transactional.db")
os.environ["CLOUDMOVE_AGENT_INVENTORY"] = str(_TEST_DATA_DIR / "cloudmove-osquery-agent-inventory.json")
os.environ["CLOUDMOVE_OSQUERY_DIR"] = str(_TEST_OSQUERY)
os.environ["CLOUDMOVE_ENABLE_IMDS_SELF_DISCOVERY"] = "false"
os.environ["CLOUDMOVE_ALLOW_SERVER_AWS_FALLBACK"] = "false"


def _cleanup_test_root() -> None:
    shutil.rmtree(_TEST_ISOLATION_ROOT, ignore_errors=True)


atexit.register(_cleanup_test_root)


import pytest  # noqa: E402


@pytest.fixture(autouse=True, scope="session")
def _isolate_singletons_to_temp():
    """Keep workspace-level singletons pointed at the temporary test root."""
    from app.migration import image_migrator, orchestrator
    from app.migration.cloud_deployer import cloud_deployer
    from app.discovery.storage import discovery_store

    orig_ws_root = cloud_deployer.workspace_root
    orig_store_dir = discovery_store.storage_dir
    orig_staging_base = image_migrator.STAGING_BASE_DIR
    orig_orch_store = orchestrator.migration_orchestrator.store_path

    cloud_deployer.workspace_root = _TEST_ISOLATION_ROOT
    discovery_store.storage_dir = _TEST_DATA_DIR / "discovery_sessions"
    image_migrator.STAGING_BASE_DIR = _TEST_STAGING
    orchestrator.migration_orchestrator.store_path = _TEST_DATA_DIR / "migrations_state.json"

    try:
        yield
    finally:
        cloud_deployer.workspace_root = orig_ws_root
        discovery_store.storage_dir = orig_store_dir
        image_migrator.STAGING_BASE_DIR = orig_staging_base
        orchestrator.migration_orchestrator.store_path = orig_orch_store
