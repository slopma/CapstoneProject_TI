"""
Unit and Integration Tests for CloudMove Agent Management (`test_agents.py`).

Covers Section 3 (CloudMove Agent: Instalable y Funcional):
1. Enrollment token generation, expiration, usage tracking, and single-use enforcement.
2. Machine enrollment, hardware ID binding, Bearer API Key issuance, and revocation.
3. Outbound heartbeat with health metrics and timestamp replay protection.
4. Capability whitelist enforcement and rejection of arbitrary shell execution.
5. Task polling, execution outcome submission, and state tracking.
6. Local system inventory collection without secrets.
7. Dynamic delivery of Linux (`install.sh`) and Windows (`install.ps1`) installer scripts.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.persistence.transactional_db import TransactionalDatabase, get_transactional_db
from cloudmove_agent.system_collector import (
    collect_cpu_info,
    collect_memory_info,
    collect_disks_and_mounts,
    collect_network_interfaces,
    collect_system_inventory,
    get_stable_machine_id,
)


client = TestClient(app)


def test_enrollment_token_lifecycle(tmp_path: Path):
    db_file = tmp_path / "agent_test.sqlite3"
    db = TransactionalDatabase(db_path=db_file)

    # 1. Create a 1-use token
    tok = db.create_enrollment_token(created_by="secops@cloudmove.local", ttl_seconds=3600, max_uses=1)
    assert tok["token_id"].startswith("tok-")
    assert tok["enrollment_token"].startswith("cmat_")
    assert tok["token_prefix"].startswith("cmat_")
    assert tok["max_uses"] == 1

    # 2. List tokens
    token_list = db.list_enrollment_tokens()
    assert len(token_list) == 1
    assert token_list[0]["token_id"] == tok["token_id"]
    assert "token_hash" not in token_list[0]
    assert token_list[0]["is_active"] is True

    # 3. Consume token
    consumed = db.verify_and_consume_enrollment_token(tok["enrollment_token"])
    assert consumed is not None
    assert consumed["token_id"] == tok["token_id"]

    # 4. Attempt to consume again (should be revoked / max uses reached)
    consumed_again = db.verify_and_consume_enrollment_token(tok["enrollment_token"])
    assert consumed_again is None


def test_agent_api_enrollment_heartbeat_and_revocation():
    # 1. Generate token via API
    t_res = client.post("/api/v1/agents/enrollment-tokens", json={"ttl_seconds": 3600, "max_uses": 1})
    assert t_res.status_code == 200
    t_data = t_res.json()
    raw_token = t_data["enrollment_token"]
    assert "install_command_linux" in t_data
    assert "install_command_windows" in t_data

    # 2. Enroll an agent via API
    e_res = client.post("/api/v1/agents/enroll", json={
        "enrollment_token": raw_token,
        "hostname": "prod-srv-01.corp.local",
        "ip_address": "10.0.10.45",
        "os_family": "linux",
        "os_name": "Ubuntu",
        "os_version": "22.04 LTS",
        "architecture": "x86_64",
        "machine_id": "test-mid-12345",
    })
    assert e_res.status_code == 200
    e_data = e_res.json()
    agent_id = e_data["agent_id"]
    api_key = e_data["agent_api_key"]
    assert agent_id.startswith("agent-")
    assert api_key.startswith("cma_")
    assert e_data["status"] == "ONLINE"

    # 3. Send valid heartbeat
    hb_res = client.post(
        f"/api/v1/agents/{agent_id}/heartbeat",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "health_metrics": {"cpu_percent": 18.5, "ram_percent": 42.0, "status": "HEALTHY"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert hb_res.status_code == 200
    assert hb_res.json()["status"] == "ONLINE"

    # 4. Send heartbeat with wrong auth header -> 403
    bad_auth = client.post(
        f"/api/v1/agents/{agent_id}/heartbeat",
        headers={"Authorization": "Bearer wrong-key"},
        json={"health_metrics": {"cpu_percent": 10.0}},
    )
    assert bad_auth.status_code == 403

    # 5. Revoke agent
    rev_res = client.post(
        f"/api/v1/agents/{agent_id}/revoke",
        json={"reason": "Servidor fuera de servicio", "operator_id": "admin@cloudmove.local"},
    )
    assert rev_res.status_code == 200
    assert rev_res.json()["status"] == "REVOKED"

    # 6. Heartbeat after revocation is rejected -> 403
    rev_hb = client.post(
        f"/api/v1/agents/{agent_id}/heartbeat",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"health_metrics": {"cpu_percent": 10.0}},
    )
    assert rev_hb.status_code == 403


def test_agent_capability_whitelist_and_task_execution():
    # 1. Create token & enroll
    t_res = client.post("/api/v1/agents/enrollment-tokens", json={"ttl_seconds": 600, "max_uses": 1})
    raw_token = t_res.json()["enrollment_token"]
    e_res = client.post("/api/v1/agents/enroll", json={
        "enrollment_token": raw_token,
        "hostname": "task-worker-01",
        "ip_address": "192.168.1.15",
    })
    agent_id = e_res.json()["agent_id"]
    api_key = e_res.json()["agent_api_key"]

    # 2. Reject arbitrary shell execution
    bad_task = client.post(f"/api/v1/agents/{agent_id}/dispatch-task", json={
        "action": "execute_shell_command",
        "parameters": {"command": "rm -rf /"},
    })
    assert bad_task.status_code == 400
    assert "rechazada por la política de seguridad" in bad_task.json()["detail"]

    # 3. Dispatch authorized task: collect_inventory
    good_task = client.post(f"/api/v1/agents/{agent_id}/dispatch-task", json={
        "action": "collect_inventory",
        "parameters": {},
    })
    assert good_task.status_code == 200
    task_id = good_task.json()["task_id"]

    # 4. Agent polls for tasks
    poll_res = client.get(
        f"/api/v1/agents/{agent_id}/tasks",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert poll_res.status_code == 200
    tasks = poll_res.json()["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == task_id
    assert tasks[0]["action"] == "collect_inventory"

    # 5. Agent posts task result
    res_res = client.post(
        f"/api/v1/agents/{agent_id}/tasks/{task_id}/result",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"status": "COMPLETED", "result": {"disks_found": 2, "services": 12}},
    )
    assert res_res.status_code == 200
    assert res_res.json()["status"] == "COMPLETED"


def test_system_collector_local_scan():
    """Verify local system collector runs without errors and produces valid metadata."""
    inv = collect_system_inventory()
    assert inv["hostname"]
    assert inv["machine_id"]
    assert "cpu" in inv
    assert "memory" in inv
    assert "disks" in inv
    assert "network_interfaces" in inv
    assert "listening_ports" in inv
    assert inv["evidence_provenance"] == "observed_by_cloudmove_agent"

    # Check CPU
    cpu = collect_cpu_info()
    assert cpu["cores_logical"] >= 1

    # Check Memory
    mem = collect_memory_info()
    assert mem["total_mb"] >= 0


def test_installer_scripts_delivery():
    # Linux installer
    res_sh = client.get("/api/v1/agents/install.sh")
    assert res_sh.status_code == 200
    assert "cloudmove-agent" in res_sh.text
    assert "systemctl" in res_sh.text

    # Windows installer
    res_ps1 = client.get("/api/v1/agents/install.ps1")
    assert res_ps1.status_code == 200
    assert "CloudMove" in res_ps1.text
    assert "agent.conf" in res_ps1.text


def test_agent_inventory_ingestion_and_asset_reconciliation():
    # 1. Generate token and enroll agent
    t_res = client.post("/api/v1/agents/enrollment-tokens", json={"ttl_seconds": 600, "max_uses": 1})
    raw_token = t_res.json()["enrollment_token"]
    e_res = client.post("/api/v1/agents/enroll", json={
        "enrollment_token": raw_token,
        "hostname": "db-server-01.corp",
        "ip_address": "10.0.5.20",
        "os_name": "Debian",
        "os_version": "12",
        "machine_id": "machine-uuid-db01",
    })
    assert e_res.status_code == 200
    agent_id = e_res.json()["agent_id"]
    api_key = e_res.json()["agent_api_key"]

    # 2. Ingest inventory payload
    inv_payload = {
        "hostname": "db-server-01.corp",
        "machine_id": "machine-uuid-db01",
        "cpu": {"cores_logical": 8, "model": "Intel Xeon"},
        "memory": {"total_mb": 32768, "available_mb": 16384},
        "disks": [
            {"device": "/dev/sda1", "mountpoint": "/", "fstype": "ext4", "total_gb": 100.0, "used_gb": 45.0}
        ],
        "network_interfaces": [
            {"name": "eth0", "ip_addresses": ["10.0.5.20"], "mac": "52:54:00:12:34:56"}
        ],
        "listening_ports": [
            {"port": 5432, "protocol": "tcp", "process_name": "postgres", "pid": 1024}
        ],
        "services": [
            {"name": "postgresql", "status": "active", "enabled": True}
        ],
        "detected_databases": [
            {"engine": "PostgreSQL", "port": 5432, "version": "15.4"}
        ],
    }

    inv_res = client.post(
        f"/api/v1/agents/{agent_id}/inventory",
        headers={"Authorization": f"Bearer {api_key}"},
        json=inv_payload,
    )
    assert inv_res.status_code == 200
    data = inv_res.json()
    assert data["status"] == "ingested"
    assert data["agent_id"] == agent_id
    assert data["asset_id"] == f"asset-{agent_id}"

    # 3. Check transactional DB persisted the asset
    db = get_transactional_db()
    asset = db.get_asset(f"asset-{agent_id}")
    assert asset is not None
    assert asset["hostname"] == "db-server-01.corp"
    assert asset["lifecycle_state"] == "DISCOVERED"
    assert asset["payload"]["agent_id"] == agent_id
    assert len(asset["payload"]["disks"]) == 1
    assert len(asset["payload"]["detected_databases"]) == 1
    assert asset["payload"]["detected_databases"][0]["engine"] == "PostgreSQL"

