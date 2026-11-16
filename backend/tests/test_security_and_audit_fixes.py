"""
Regression tests for security, multi-user isolation, SSRF, archive extraction,
persistence, Terraform hardening, and agent endpoint fixes.
"""

from __future__ import annotations

import http.server
import io
import socket
import tarfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.security import (
    SSRFBlockedError,
    open_url_no_redirects,
    validate_public_target_host,
    validate_safe_id,
)
from app.discovery.cloud_live_discovery import AWSLiveDiscoveryConnector
from app.discovery.connectors import SecurityPolicyViolationError, validate_endpoint_against_ssrf
from app.discovery.github_connector import GitHubConnector
from app.generators.ai_translator import (
    generate_auto_dockerfile_and_compose,
    generate_cheap_infrastructure,
    prepare_ai_payload,
)
from app.generators.terraform import generate_aws_terraform_files
from app.main import app
from app.migration.cloud_deployer import CloudDeploymentRunner
from app.migration.external_services import validate_external_credentials
from app.migration.orchestrator import MigrationOrchestrator
from app.persistence.transactional_db import TransactionalDatabase


# ==============================================================================
# 1. Credential Isolation, Env Injection Prevention & Path Safety
# ==============================================================================


def test_deployer_env_allowlist_and_cross_request_isolation(tmp_path: Path, monkeypatch):
    runner = CloudDeploymentRunner(workspace_root=tmp_path / "deployments")

    # Contaminate server process env with host/admin credentials that must NEVER leak
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIASERVERLEAKEDKEY")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "server_leaked_secret")
    monkeypatch.setenv("AWS_PROFILE", "admin-profile")

    # Explicit user A credentials plus forbidden process-hijack env vars
    user_a_env = runner._build_env({
        "aws_access_key_id": "AKIAUSERAKEY1234567",
        "aws_secret_access_key": "user_a_secret_key",
        "aws_region": "us-west-2",
        "LD_PRELOAD": "/tmp/evil.so",
        "BASH_ENV": "/tmp/evil.sh",
        "PATH": "/tmp/malicious_bin",
    })
    assert user_a_env["AWS_ACCESS_KEY_ID"] == "AKIAUSERAKEY1234567"
    assert user_a_env["AWS_SECRET_ACCESS_KEY"] == "user_a_secret_key"
    assert user_a_env["AWS_DEFAULT_REGION"] == "us-west-2"
    assert "LD_PRELOAD" not in user_a_env
    assert "BASH_ENV" not in user_a_env
    assert user_a_env["PATH"] != "/tmp/malicious_bin"

    # Subsequent user B request without credentials must NEVER inherit user A or server env
    user_b_env = runner._build_env(None)
    assert "AWS_ACCESS_KEY_ID" not in user_b_env
    assert "AWS_SECRET_ACCESS_KEY" not in user_b_env
    assert "AWS_PROFILE" not in user_b_env
    assert user_b_env.get("AWS_EC2_METADATA_DISABLED") == "true"

    # Verify & Audit without credentials require user input (unless explicitly opted in)
    verify_res = runner.verify_cloud_provider_credentials("aws", credentials=None)
    assert verify_res["valid"] is False
    assert verify_res.get("requires_input") is True

    audit_res = runner.audit_aws_account(credentials=None)
    assert audit_res["authenticated"] is False
    assert audit_res.get("requires_credentials") is True


def test_deployer_path_traversal_and_protected_control_plane(tmp_path: Path):
    runner = CloudDeploymentRunner(workspace_root=tmp_path / "deployments")

    with pytest.raises(ValueError):
        runner.resolve_job_dir("../../etc")

    with pytest.raises(ValueError):
        validate_safe_id("../escape")

    bad_del = runner.delete_aws_audit_resource("workspace", "../../etc")
    assert bad_del["success"] is False

    protected_del = runner.delete_aws_audit_resource("workspace", "deploy/aws")
    assert protected_del["success"] is False


# ==============================================================================
# 2. SSRF Protection (Literal IPs, DNS Resolution & Redirect Blocking)
# ==============================================================================


def test_ssrf_blocks_metadata_private_ips_and_dns_rebinding(monkeypatch):
    for blocked in ("169.254.169.254", "127.0.0.1", "10.0.0.5", "fd00:ec2::254", "metadata.google.internal"):
        with pytest.raises(SSRFBlockedError):
            validate_public_target_host(blocked, allow_private=False)

    # Simulate a DNS name resolving to EC2 IMDS (e.g. rebinding / nip.io style attack)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, type=0: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))],
    )
    with pytest.raises(SSRFBlockedError):
        validate_public_target_host("evil-rebind.example.com", allow_private=False)

    # Proxmox connector allows private RFC1918 when authorized, but always blocks IMDS/loopback
    assert validate_endpoint_against_ssrf("https://10.10.1.50:8006", allow_private_datacenter=True).hostname == "10.10.1.50"
    with pytest.raises(SecurityPolicyViolationError):
        validate_endpoint_against_ssrf("http://169.254.169.254/latest/meta-data", allow_private_datacenter=True)
    with pytest.raises(SecurityPolicyViolationError):
        validate_endpoint_against_ssrf("https://user:pass@10.10.1.50:8006", allow_private_datacenter=True)

    # External Supabase validator uses strict public URL check (blocks IMDS & private networks)
    supa_res = validate_external_credentials(
        "supabase",
        {"supabase_url": "http://169.254.169.254/latest/meta-data", "supabase_key": "dummy-key"},
    )
    assert supa_res["valid"] is False


def test_open_url_no_redirects_blocks_302_to_internal():
    class RedirectHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()

        def log_message(self, format, *args):
            return

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(f"http://127.0.0.1:{port}/redirect")
        with pytest.raises((SSRFBlockedError, urllib.error.HTTPError)):
            open_url_no_redirects(req, timeout=2.0)
    finally:
        srv.shutdown()
        srv.server_close()


# ==============================================================================
# 3. GitHub Tar-Slip & Symlink Extraction Hardening
# ==============================================================================


def test_github_tarball_blocks_traversal_and_symlinks(tmp_path: Path):
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w:gz") as tf:
        # 1. Valid file inside repo root
        good_data = b"print('ok')\n"
        ti_good = tarfile.TarInfo("org-repo-abc1234/main.py")
        ti_good.size = len(good_data)
        tf.addfile(ti_good, io.BytesIO(good_data))

        # 2. Path traversal entry
        evil_data = b"pwned"
        ti_evil = tarfile.TarInfo("org-repo-abc1234/../../outside_pwned.txt")
        ti_evil.size = len(evil_data)
        tf.addfile(ti_evil, io.BytesIO(evil_data))

        # 3. Malicious symlink pointing outside extraction root
        ti_sym = tarfile.TarInfo("org-repo-abc1234/secret_link")
        ti_sym.type = tarfile.SYMTYPE
        ti_sym.linkname = "/etc/passwd"
        tf.addfile(ti_sym)

    connector = GitHubConnector()
    connector._request = MagicMock(return_value=tar_buf.getvalue())

    checkout_dir = connector.download_and_extract_tarball(
        url="https://github.com/org/repo",
        commit_sha="a" * 40,
        target_dir=tmp_path,
    )

    assert (checkout_dir / "main.py").is_file()
    assert not (checkout_dir / "secret_link").exists()
    assert not (tmp_path / "outside_pwned.txt").exists()
    assert not (tmp_path.parent / "outside_pwned.txt").exists()


# ==============================================================================
# 4. Transient Token Passing, Multi-Region AWS & Route Integration
# ==============================================================================


def test_uc1_migrate_passes_transient_github_token_without_persisting(tmp_path: Path, monkeypatch):
    from contextlib import contextmanager

    repo_dir = tmp_path / "private_repo"
    repo_dir.mkdir(parents=True)
    (repo_dir / "requirements.txt").write_text("fastapi==0.110.0\nuvicorn==0.27.0\n", encoding="utf-8")
    (repo_dir / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n@app.get('/health')\ndef ok(): return {'ok': True}\n", encoding="utf-8")

    captured_tokens = []

    @contextmanager
    def fake_checkout(self, url, ref=None, token=None):
        captured_tokens.append(token or self.token)
        yield repo_dir, {
            "owner": "org",
            "repo": "private-app",
            "commit_sha": "a" * 40,
            "short_sha": "aaaaaaaa",
            "ref": ref or "main",
            "repository_url": url,
            "author_name": "test-author",
            "author_date": "2026-11-16T00:00:00+00:00",
            "commit_message": "init",
            "pinned_at": "2026-11-16T00:00:00+00:00",
        }

    monkeypatch.setattr(GitHubConnector, "ephemeral_checkout", fake_checkout)
    monkeypatch.setattr(GitHubConnector, "get_repository_tree", lambda self, url, ref=None, token=None: {"directories": [], "files_sample": [], "key_manifests": [], "summary": {}})

    client = TestClient(app)
    resp = client.post(
        "/api/v1/migration/use-case-1/migrate",
        json={
            "github_url": "https://github.com/org/private-app",
            "github_ref": "main",
            "github_token": "ghp_superSecretTokenForInspectOnly123",
            "deployment_mode": "vm_rehost",
            "app_name": "private-app",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert captured_tokens == ["ghp_superSecretTokenForInspectOnly123"]

    stored_job = client.get(f"/api/v1/migration/jobs/{body['migration_id']}").json()
    stored_token = str((stored_job.get("source_config") or {}).get("github_token") or "")
    assert "ghp_superSecretTokenForInspectOnly123" not in stored_token


def test_aws_live_discovery_forwards_credentials_and_multi_region(monkeypatch):
    seen_init = {}

    class StubConnector:
        def __init__(self, **kwargs):
            seen_init.update(kwargs)

        def discover_live_account(self):
            return {"status": "ok", "regions": seen_init.get("regions"), "assets": []}

    monkeypatch.setattr("app.api.routers.discovery.AWSLiveDiscoveryConnector", StubConnector)

    client = TestClient(app)
    resp = client.post(
        "/api/v1/discovery/cloud/aws",
        json={
            "regions": ["us-east-1", "us-west-2"],
            "aws_access_key_id": "AKIA_CLIENT_KEY",
            "aws_secret_access_key": "CLIENT_SECRET",
            "aws_session_token": "SESSION_TOK",
        },
    )
    assert resp.status_code == 200
    assert seen_init["regions"] == ["us-east-1", "us-west-2"]
    assert seen_init["aws_access_key_id"] == "AKIA_CLIENT_KEY"
    assert seen_init["aws_secret_access_key"] == "CLIENT_SECRET"
    assert seen_init["aws_session_token"] == "SESSION_TOK"

    # Also verify AWSLiveDiscoveryConnector preserves multi-region list cleanly
    conn = AWSLiveDiscoveryConnector(region="us-east-1", regions=["us-east-1", "eu-west-1"])
    assert conn.regions == ["us-east-1", "eu-west-1"]


# ==============================================================================
# 5. Transactional DB & Orchestrator Concurrency / Integrity
# ==============================================================================


def test_transactional_db_postgres_guard_revocation_and_heartbeat_replay(tmp_path: Path):
    with pytest.raises(NotImplementedError):
        TransactionalDatabase(database_url="postgresql://user:pass@localhost:5432/cloudmove")

    db = TransactionalDatabase(db_path=tmp_path / "test_cm.db")
    status = db.get_schema_status()
    assert status["engine"] == "sqlite_wal"
    assert status["journal_mode"] == "WAL"

    enrolled = db.enroll_agent({
        "agent_id": "agt-test-001",
        "hostname": "web-01",
        "ip_address": "10.0.1.10",
        "os_family": "linux",
        "os_name": "Ubuntu 24.04",
        "os_version": "24.04",
        "architecture": "x86_64",
        "api_key_hash": "hash123",
    })
    assert enrolled["agent_id"] == "agt-test-001"

    # Enqueue a task before re-enrolling same active agent_id -> tasks must NOT be deleted (upsert)
    task = db.create_agent_task("agt-test-001", "collect_inventory", {}, "tester")
    db.enroll_agent({
        "agent_id": "agt-test-001",
        "hostname": "web-01-renamed",
        "ip_address": "10.0.1.10",
        "os_family": "linux",
        "api_key_hash": "hash456",
    })
    pending = db.get_pending_tasks_for_agent("agt-test-001")
    assert any(t["task_id"] == task["task_id"] for t in pending)

    # Fresh heartbeat + nonce succeeds; replaying same nonce fails; bad timestamp / huge skew fails
    now_iso = datetime.now(timezone.utc).isoformat()
    hb = db.record_agent_heartbeat("agt-test-001", {"cpu_percent": 5.0}, nonce="nonce-unique-1", timestamp=now_iso)
    assert hb["agent_id"] == "agt-test-001"

    with pytest.raises(ValueError):
        db.record_agent_heartbeat("agt-test-001", {"cpu_percent": 5.0}, nonce="nonce-unique-1", timestamp=now_iso)

    stale_iso = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError):
        db.record_agent_heartbeat("agt-test-001", {"cpu_percent": 5.0}, nonce="nonce-unique-2", timestamp=stale_iso)

    with pytest.raises(ValueError):
        db.record_agent_heartbeat("agt-test-001", {"cpu_percent": 5.0}, nonce="nonce-unique-3", timestamp="not-a-timestamp")

    # Revoked agent cannot be re-enrolled
    db.revoke_agent("agt-test-001", reason="compromised", revoked_by="secops")
    with pytest.raises(PermissionError):
        db.enroll_agent({
            "agent_id": "agt-test-001",
            "hostname": "web-01",
            "ip_address": "10.0.1.10",
            "api_key_hash": "hash789",
        })


def test_orchestrator_atomic_store_and_concurrent_writes(tmp_path: Path):
    orch = MigrationOrchestrator(store_path=tmp_path / "jobs.json")

    def worker(idx: int):
        job = orch.create_migration(
            name=f"Concurrent Migration {idx}",
            use_case="app_source",
            target_provider="aws",
            source_config={"selected_resources": [f"srv-{idx}"]},
            auto_assess_and_plan=False,
        )
        assert orch.get_migration(job["migration_id"]) is not None

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    concurrent_jobs = [j for j in orch.list_migrations() if str(j.get("name", "")).startswith("Concurrent Migration")]
    assert len(concurrent_jobs) == 6
    assert list(tmp_path.glob(".jobs_*.tmp")) == []


# ==============================================================================
# 6. Terraform Security, HA Parity, Zero Hardcoded Passwords & Agent Install
# ==============================================================================


def test_terraform_db_cidr_restriction_and_ha_without_orphan_ec2():
    resources = [
        {
            "cmir_id": "comp-web",
            "cmir_type": "container",
            "terraform_resource": "aws_instance",
            "name": "web-app",
            "instance_type": "t3.micro",
            "metadata": {
                "deployment_mode": "container",
                "high_availability": True,
                "enable_alb_asg": True,
                "exposed_ports": [80, 5432],
            },
        }
    ]
    tf_files = generate_aws_terraform_files(resources)
    main_tf = tf_files["main.tf"]
    vars_tf = tf_files["variables.tf"]
    outputs_tf = tf_files["outputs.tf"]

    # Port 5432 is restricted to var.db_ingress_cidr (defaults to VPC private CIDR 10.0.0.0/16)
    assert 'variable "db_ingress_cidr"' in vars_tf
    assert 'default     = "10.0.0.0/16"' in vars_tf
    assert "cidr_blocks = [var.db_ingress_cidr]" in main_tf
    assert 'cidr_blocks = ["0.0.0.0/0"] # db' not in main_tf

    # HA mode generates ALB + Launch Template + ASG without an orphan standalone aws_instance
    assert 'resource "aws_lb"' in main_tf
    assert 'resource "aws_autoscaling_group"' in main_tf
    assert 'resource "aws_instance"' not in main_tf
    assert "alb_dns_name" in outputs_tf


def test_ai_translator_no_hardcoded_db_passwords():
    payload = prepare_ai_payload(
        {
            "app_name": "OrdersService",
            "framework": "FastAPI",
            "language": "Python",
            "exposed_ports": [8000],
            "components": [
                {"name": "backend", "tier": "backend", "runtime": "python:3.11-slim", "ports": [8000]},
                {"name": "db", "tier": "database", "runtime": "postgres:16-alpine", "ports": [5432]},
            ],
        },
        repo_url="https://github.com/org/orders.git",
    )
    docker_files = generate_auto_dockerfile_and_compose(payload)
    infra = generate_cheap_infrastructure(payload, api_key="")

    combined = "\n".join([
        docker_files.get("Dockerfile.cloudmove", ""),
        docker_files.get("docker-compose.cloudmove.yml", ""),
        infra.get("user_data_sh", ""),
        infra.get("main_tf", ""),
    ])
    assert "CloudMoveDB2026!" not in combined
    assert "change_me_for_local_development" not in combined


def test_agent_install_sh_token_validation_and_safe_quoting():
    client = TestClient(app)

    bad_resp = client.get("/api/v1/agents/install.sh", params={"token": 'abc";id;#'})
    assert bad_resp.status_code == 400

    good_resp = client.get("/api/v1/agents/install.sh", params={"token": "cm_tok_valid_123456"})
    assert good_resp.status_code == 200
    assert "ENROLLMENT_TOKEN=cm_tok_valid_123456" in good_resp.text
    assert "CM_ENROLLMENT_TOKEN" in good_resp.text
    assert "os.environ.get('CM_ENROLLMENT_TOKEN'" in good_resp.text
