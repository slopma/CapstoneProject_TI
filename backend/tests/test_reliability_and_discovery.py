"""
Regression tests for reliability, concurrency lock safety, subprocess cancellation,
and live agent discovery routing (`test_reliability_and_discovery.py`).
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.main import app
from app.migration.cloud_deployer import CloudDeploymentRunner


client = TestClient(app)


def test_discovery_agent_live_endpoint_returns_200():
    """Verify `/api/v1/discovery/agent-live` forwards Request properly without 500 TypeError."""
    resp = client.get("/api/v1/discovery/agent-live")
    assert resp.status_code == 200
    payload = resp.json()
    assert "agent_connected" in payload
    assert "aws_storage_quota" in payload


def test_execute_terraform_command_while_running_does_not_deadlock(tmp_path: Path):
    """Calling execute_terraform_command while a process is active must not deadlock _lock."""
    runner = CloudDeploymentRunner(workspace_root=tmp_path)
    mig_id = "mig-test-lock"
    job_dir = runner.resolve_job_dir(mig_id)
    (job_dir / "main.tf").write_text("# dummy\n", encoding="utf-8")

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    with runner._lock:
        runner._active_processes[mig_id] = mock_proc
        runner._active_commands[mig_id] = "apply"

    result_holder = {}

    def _invoke():
        result_holder["cmd"] = runner.execute_terraform_command(
            migration_id=mig_id,
            job_dir=job_dir,
            action="plan",
            async_exec=True,
        )
        result_holder["status"] = runner.get_terraform_status(mig_id, job_dir)

    t = threading.Thread(target=_invoke, daemon=True)
    t.start()
    t.join(timeout=3.0)
    assert not t.is_alive(), "Deadlock detected in CloudDeploymentRunner._lock"
    assert result_holder["cmd"]["already_running"] is True
    assert result_holder["cmd"]["success"] is False
    assert result_holder["status"]["is_running"] is True

    with runner._lock:
        runner._active_processes.pop(mig_id, None)
        runner._active_commands.pop(mig_id, None)


def test_streaming_subprocess_cancels_silent_process_promptly(tmp_path: Path):
    """Cancel must abort a silent subprocess quickly even when it emits no stdout lines."""
    runner = CloudDeploymentRunner(workspace_root=tmp_path)
    mig_id = "mig-test-cancel"
    job_dir = runner.resolve_job_dir(mig_id)

    res_holder = {}

    def _run():
        res_holder["res"] = runner._run_streaming_subprocess(
            migration_id=mig_id,
            job_dir=job_dir,
            cmd=[sys.executable, "-c", "import time; time.sleep(30)"],
            env={},
            timeout_sec=30,
        )

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    # Wait briefly until subprocess is registered in _active_processes
    deadline = time.time() + 3.0
    while time.time() < deadline:
        with runner._lock:
            if mig_id in runner._active_processes:
                break
        time.sleep(0.05)

    start_cancel = time.time()
    cancel_status = runner.cancel_terraform_execution(mig_id, job_dir)
    t.join(timeout=3.0)
    elapsed = time.time() - start_cancel

    assert not t.is_alive(), "Subprocess reader failed to abort after cancellation"
    assert elapsed < 3.0
    assert cancel_status["is_running"] is False
    assert res_holder["res"]["cancelled"] is True
