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


def test_multistep_terraform_status_stays_running_between_subprocesses(tmp_path: Path, monkeypatch):
    """Multi-step dry_run must report is_running=True / RUNNING between step subprocesses."""
    runner = CloudDeploymentRunner(workspace_root=tmp_path)
    mig_id = "mig-test-multistep"
    job_dir = runner.resolve_job_dir(mig_id)
    (job_dir / "main.tf").write_text("# dummy\n", encoding="utf-8")

    monkeypatch.setattr("app.migration.cloud_deployer.shutil.which", lambda _name: sys.executable)

    observed_statuses = []

    def _fake_stream(_mig_id, _job_dir, cmd, env=None, timeout_sec=60):
        # Record status *between* subprocess steps when _active_processes has no entry
        with runner._lock:
            assert _mig_id not in runner._active_processes
        observed_statuses.append(runner.get_terraform_status(_mig_id, _job_dir))
        time.sleep(0.08)
        return {"returncode": 0, "cancelled": False, "error": None, "output": "ok"}

    monkeypatch.setattr(runner, "_run_streaming_subprocess", _fake_stream)

    start_payload = runner.execute_terraform_command(
        migration_id=mig_id,
        job_dir=job_dir,
        action="dry_run",
        async_exec=True,
    )
    assert start_payload["is_running"] is True
    assert start_payload["status"] == "RUNNING"

    deadline = time.time() + 5.0
    final_status = start_payload
    while time.time() < deadline:
        final_status = runner.get_terraform_status(mig_id, job_dir)
        if not final_status["is_running"] and final_status["status"] != "RUNNING":
            break
        time.sleep(0.03)

    assert len(observed_statuses) == 3
    for mid_status in observed_statuses:
        assert mid_status["is_running"] is True
        assert mid_status["status"] == "RUNNING"
        assert mid_status["active_command"] == "dry_run"

    assert final_status["is_running"] is False
    assert final_status["status"] == "SUCCESS"
    assert final_status["active_command"] is None


def test_target_architecture_handles_empty_component_ports():
    """build_target_cloud_cmir must not raise IndexError when container_ports or host_ports are []."""
    from app.migration.target_architecture import build_target_cloud_cmir

    cmir = build_target_cloud_cmir(
        app_discovery={
            "app_id": "app-empty-ports",
            "app_name": "empty-ports",
            "components": [
                {
                    "name": "bootstrap",
                    "tier": "worker",
                    "runtime": "postgres:17",
                    "container_ports": [],
                    "host_ports": [],
                },
                {
                    "name": "backend",
                    "tier": "backend",
                    "runtime": "node:24-alpine",
                    "container_ports": [5001],
                    "host_ports": [],
                },
            ],
        },
        target_provider="aws",
        deployment_mode="container",
    )
    app_nodes = [r for r in cmir.resources if r.type == "application"]
    assert len(app_nodes) == 2
    assert app_nodes[0].metadata["container_port"] == 80
    assert app_nodes[1].metadata["container_port"] == 5001


def test_collector_script_resolves_and_serves_python_collector():
    """GET /api/v1/discovery/collector-script must return the real Python script (200)."""
    resp = client.get("/api/v1/discovery/collector-script")
    assert resp.status_code == 200
    assert "collect_osquery_inventory" in resp.text
    assert 'filename="cloudmove_osquery_export.py"' in resp.headers.get("content-disposition", "")


def test_probe_uc2_file_raw_and_download_proxies(monkeypatch):
    """Case 2 view, raw text, and download proxies should fetch cleanly and guard traversal."""
    import urllib.request

    bad = client.get("/api/v1/migration/probe-uc2-file-raw?ip=13.218.196.73&path=../../etc/shadow")
    assert bad.status_code == 400

    class _FakeResp:
        def __init__(self, body: bytes):
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def _fake_urlopen(req, timeout=8.0):
        return _FakeResp(b"print('ok')\n")

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    raw_resp = client.get(
        "/api/v1/migration/probe-uc2-file-raw?ip=13.218.196.73&path=home/lacastrilp/demo.py"
    )
    assert raw_resp.status_code == 200
    assert raw_resp.text == "print('ok')\n"

    dl_resp = client.get(
        "/api/v1/migration/probe-uc2-file-download?ip=13.218.196.73&path=home/lacastrilp/demo.py"
    )
    assert dl_resp.status_code == 200
    assert dl_resp.content == b"print('ok')\n"
    assert 'filename="demo.py"' in dl_resp.headers.get("content-disposition", "")
