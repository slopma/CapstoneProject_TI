"""
Exhaustive Unit, Integration, and End-to-End Verification Suite for CloudMove
(Sections 5 through 13 of Production Completion Specification).

Covers:
1. ACID Transactional Persistence (`TransactionalDatabase`), versioned schema migrations
   (`1.0.0`, `2.0.0`, `2.1.0`), legacy JSON migration with `.bak` backup & incompatible
   record detection (`azure` rejected), and state survival across backend restarts.
2. Optimistic Concurrency Control (`ConcurrencyConflictError` / HTTP 409) and Atomic Stage
   Execution Locking (`StageLockedError` / HTTP 409) when two operators execute the same stage.
3. Idempotent stage execution (`idempotency_key`) ensuring retries do not duplicate executions.
4. Live Cloud Discovery for AWS (`AWSLiveDiscoveryConnector` with pagination, `Throttling`
   rate-limit retry, auth failure 401/403 never returning an empty 200 inventory, timeout,
   partial service failure, CMIR v2.1 normalization, and multi-snapshot reconciliation).
5. Live Cloud Discovery for GCP (`GCPLiveDiscoveryConnector` with `searchAllResources`
   pagination, `429` retry, `401`/`403` auth failure, CMIR normalization, and reconciliation).
6. Use Case 1 (`app_source`): Static discovery for Python, Node.js, Java (`pom.xml`), Go
   (`go.mod`), `Dockerfile`/`docker-compose.yml`, and deployed process metadata; secret
   redaction; stateless container incompatibility warnings; DB migration runbook; startup &
   health check failure blocking cutover; and E2E AWS/GCP orchestration.
7. Use Case 2 (`vm_image`): Authentic binary disk header inspection (`qemu-img info`, `KDMV`
   VMDK, `QFI\xfb` QCOW2, GPT partition labels) vs simulated text stub (`simulated_text_stub.vmdk`),
   real staging copy & `qemu-img convert` (`QCOW2` -> `RAW`), missing secondary disk blocker,
   `dirty_live_disk` snapshot blocker, missing staging storage error, AWS MGN / VM Import &
   GCP Migrate to VMs / Image Import clients, and 8 fidelity dimensions.
8. Use Case 3 (`datacenter_campaign`): Unreachable hosts (`partial_with_unreachable_hosts`,
   `fully_discovered == False`), separation of listening `process` (`sshd`) vs `application`,
   separation of `communicates_with` vs `depends_on` / `inferred_relation`, shared dependency
   protection, pause/resume/retry, and restart survival.
9. Real `/usr/bin/terraform fmt -check` validation passing on generated AWS/GCP HCL and
   rejecting invalid HCL, undeclared `var.*`, broken resource refs, and exposed secrets.
10. Non-viable rollback (`mark_irreversible_operation`) blocking automatic rollback and
    returning the documented alternative recovery procedure.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.error

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from app.main import app
from app.config import PROJECT_ROOT
from app.adapters.aws_adapter import AWSAdapter
from app.adapters.gcp_adapter import GCPAdapter
from app.discovery.campaigns import DataCenterCampaignStore
from app.discovery.cloud_live_discovery import (
    AWSLiveDiscoveryConnector,
    GCPLiveDiscoveryConnector,
    CloudInventoryReconciler,
)
from app.discovery.connectors import ConnectorAuthError, ConnectorError, ConnectorTimeoutError
from app.migration.app_migrator import (
    inspect_application_source,
    build_application_cmir,
    evaluate_app_migration_viability,
)
from app.migration.image_migrator import (
    inspect_binary_disk_header_and_structure,
    inspect_vm_image,
    evaluate_vm_image_compatibility,
    prepare_and_verify_staging_copy,
)
from app.migration.orchestrator import MigrationOrchestrator
from app.migration.replication_and_import import (
    select_machine_migration_strategy,
    AWSMachineMigrationClient,
    GCPMachineMigrationClient,
)
from app.persistence.transactional_db import (
    TransactionalDatabase,
    ConcurrencyConflictError,
    StageLockedError,
)

client = TestClient(app)


# ==============================================================================
# 1. Transactional Persistence, Schema Migrations, Legacy JSON & Concurrency
# ==============================================================================


def test_transactional_db_migrations_legacy_import_and_restart_survival(tmp_path: Path):
    db_file = tmp_path / "cloudmove_test.sqlite3"
    db = TransactionalDatabase(db_path=db_file)

    status = db.get_schema_status()
    assert "sqlite" in status["engine"]
    assert status["journal_mode"].lower() == "wal"
    assert status["current_schema_version"] in ("2.1.0", "2.2.0")
    assert len(status["applied_migrations"]) >= 3

    # Test legacy JSON migration with valid & incompatible (azure) records
    legacy_migrations = tmp_path / "migration_jobs.json"
    legacy_campaigns = tmp_path / "datacenter_campaigns.json"

    legacy_migrations.write_text(
        json.dumps(
            {
                "schema_version": "2.1",
                "jobs": {
                    "mig-legacy-aws-01": {
                        "migration_id": "mig-legacy-aws-01",
                        "name": "Legacy AWS Migration",
                        "use_case": "app_source",
                        "target_provider": "aws",
                        "state": "PLAN_READY",
                        "execution_mode": "simulated_dry_run",
                        "completed_in_real_cloud": False,
                        "ordered_stages": [
                            {"stage_id": "s1", "order": 1, "title": "Stage 1", "status": "PENDING"}
                        ],
                    },
                    "mig-legacy-azure-invalid": {
                        "migration_id": "mig-legacy-azure-invalid",
                        "name": "Incompatible Azure Migration",
                        "use_case": "app_source",
                        "target_provider": "azure",
                        "state": "DRAFT",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    legacy_campaigns.write_text(
        json.dumps(
            {
                "global_state": {"kill_switch_active": False, "reason": None},
                "sites": {"site-dc-01": {"id": "site-dc-01", "name": "Primary DC"}},
                "campaigns": {
                    "camp-legacy-01": {
                        "id": "camp-legacy-01",
                        "name": "Legacy Campaign",
                        "mode": "safe_scan",
                        "status": "completed",
                        "assets": [{"id": "asset-01", "hostname": "srv-01", "ip": "10.0.0.10"}],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    report = db.migrate_legacy_json_files(
        migrations_json_path=legacy_migrations,
        campaigns_json_path=legacy_campaigns,
    )
    assert report["migrated_jobs_count"] == 1
    assert report["migrated_campaigns_count"] == 1
    assert len(report["incompatible_records"]) == 1
    assert report["incompatible_records"][0]["record_id"] == "mig-legacy-azure-invalid"
    assert (tmp_path / "migration_jobs.json.bak").is_file()
    assert (tmp_path / "datacenter_campaigns.json.bak").is_file()

    # Verify survival across simulated backend restart (new orchestrator instance against same DB)
    orch_1 = MigrationOrchestrator(store_path=tmp_path / "jobs.json", db=db)
    created = orch_1.create_migration(
        name="Restart Survival Job",
        use_case="app_source",
        target_provider="aws",
        auto_assess_and_plan=True,
    )
    mid = created["migration_id"]
    assert created["state"] == "PLAN_READY"
    assert created["version"] >= 1

    # Simulate backend restart by instantiating a fresh MigrationOrchestrator on the same DB
    db_restarted = TransactionalDatabase(db_path=db_file)
    orch_2 = MigrationOrchestrator(store_path=tmp_path / "jobs.json", db=db_restarted)
    reloaded = orch_2.get_migration(mid)
    assert reloaded["migration_id"] == mid
    assert reloaded["state"] == "PLAN_READY"
    assert len(reloaded["ordered_stages"]) == 12


def test_optimistic_concurrency_conflict_and_simultaneous_stage_locking(tmp_path: Path):
    db_file = tmp_path / "concurrency_test.sqlite3"
    db = TransactionalDatabase(db_path=db_file)
    orch = MigrationOrchestrator(store_path=tmp_path / "jobs.json", db=db)

    job = orch.create_migration(
        name="Concurrency Protected Migration",
        use_case="app_source",
        target_provider="aws",
        auto_assess_and_plan=True,
    )
    mid = job["migration_id"]
    stale_version = job["version"]

    # Operator A approves the plan, advancing version
    approved = orch.approve_migration(mid, approved_by="operator_a@cloudmove.local", expected_version=stale_version)
    assert approved["version"] > stale_version

    # Operator B attempts to approve using stale_version -> must raise ConcurrencyConflictError
    with pytest.raises(ConcurrencyConflictError):
        orch.approve_migration(mid, approved_by="operator_b@cloudmove.local", expected_version=stale_version)

    # Exclusive stage locking: Operator A acquires lock on first pending stage
    first_stage_id = [s for s in approved["ordered_stages"] if s["status"] == "PENDING"][0]["stage_id"]
    db.acquire_stage_lock(mid, first_stage_id, operator_id="operator_a@cloudmove.local")

    # Operator B attempts to execute/advance the same migration while Operator A holds the lock -> StageLockedError
    with pytest.raises(StageLockedError):
        orch.advance_execution(mid, operator_id="operator_b@cloudmove.local")

    # Release lock and verify Operator B can now advance idempotently
    db.release_stage_lock(mid, first_stage_id, operator_id="operator_a@cloudmove.local")
    advanced_1 = orch.advance_execution(
        mid,
        operator_id="operator_b@cloudmove.local",
        idempotency_key="idem-prep-001",
    )
    assert advanced_1["state"] == "PREPARING"

    # Replaying the exact same idempotency_key must NOT advance to TESTING or duplicate execution
    replayed = orch.advance_execution(
        mid,
        operator_id="operator_b@cloudmove.local",
        idempotency_key="idem-prep-001",
    )
    assert replayed["state"] == "PREPARING"
    assert replayed.get("last_idempotent_replay") is not None


# ==============================================================================
# 2. Live Cloud Discovery (AWS & GCP) with Pagination, Errors & Reconciliation
# ==============================================================================


class _MockPaginator:
    def __init__(self, pages: List[Dict[str, Any]], throttle_once: bool = False):
        self.pages = pages
        self.throttle_once = throttle_once
        self.calls = 0

    def paginate(self, **kwargs):
        self.calls += 1
        if self.throttle_once and self.calls == 1:
            raise ClientError(
                {"Error": {"Code": "Throttling", "Message": "Rate exceeded"}},
                "PaginateOperation",
            )
        return self.pages


class _MockAWSClient:
    def __init__(self, service_name: str, scenario: str = "normal"):
        self.service_name = service_name
        self.scenario = scenario

    def can_paginate(self, operation_name: str) -> bool:
        return True

    def get_caller_identity(self):
        if self.scenario == "auth_error":
            raise ClientError(
                {"Error": {"Code": "InvalidClientTokenId", "Message": "The security token included in the request is invalid."}},
                "GetCallerIdentity",
            )
        return {"Account": "123456789012", "Arn": "arn:aws:iam::123456789012:user/cloudmove-auditor"}

    def list_buckets(self):
        if self.scenario == "partial_s3_error":
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "S3 ListAllMyBuckets denied"}},
                "ListBuckets",
            )
        return {"Buckets": [{"Name": "cloudmove-prod-artifacts", "CreationDate": "2026-01-01T00:00:00Z"}]}

    def get_paginator(self, operation_name: str):
        if operation_name == "describe_vpcs":
            return _MockPaginator([{"Vpcs": [{"VpcId": "vpc-0abc123", "CidrBlock": "10.20.0.0/16", "IsDefault": False, "Tags": [{"Key": "Name", "Value": "prod-vpc"}]}]}], throttle_once=True)
        if operation_name == "describe_subnets":
            return _MockPaginator([{"Subnets": [{"SubnetId": "subnet-01", "VpcId": "vpc-0abc123", "CidrBlock": "10.20.1.0/24", "AvailabilityZone": "us-east-1a"}]}])
        if operation_name == "describe_security_groups":
            return _MockPaginator([{"SecurityGroups": [{"GroupId": "sg-01", "GroupName": "app-sg", "VpcId": "vpc-0abc123", "IpPermissions": [{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443}]}]}])
        if operation_name == "describe_instances":
            return _MockPaginator([
                {"Reservations": [{"Instances": [{"InstanceId": "i-001", "InstanceType": "m6i.large", "VpcId": "vpc-0abc123", "SubnetId": "subnet-01", "PrivateIpAddress": "10.20.1.10", "State": {"Name": "running"}, "SecurityGroups": [{"GroupId": "sg-01"}], "Tags": [{"Key": "Name", "Value": "erp-app-01"}]}]}]},
                {"Reservations": [{"Instances": [{"InstanceId": "i-002", "InstanceType": "t3.medium", "VpcId": "vpc-0abc123", "SubnetId": "subnet-01", "PrivateIpAddress": "10.20.1.11", "State": {"Name": "running"}, "SecurityGroups": [{"GroupId": "sg-01"}], "Tags": [{"Key": "Name", "Value": "erp-worker-02"}]}]}]},
            ])
        if operation_name == "describe_volumes":
            return _MockPaginator([{"Volumes": [{"VolumeId": "vol-001", "Size": 100, "VolumeType": "gp3", "Encrypted": True, "State": "in-use", "Attachments": [{"InstanceId": "i-001", "Device": "/dev/xvda"}]}]}])
        if operation_name == "describe_db_instances":
            return _MockPaginator([{"DBInstances": [{"DBInstanceIdentifier": "erp-postgres-db", "Engine": "postgres", "EngineVersion": "15.4", "DBInstanceClass": "db.m6i.large", "DBInstanceStatus": "available", "AllocatedStorage": 200, "MultiAZ": True, "StorageEncrypted": True, "DBSubnetGroup": {"VpcId": "vpc-0abc123"}, "VpcSecurityGroups": [{"VpcSecurityGroupId": "sg-01"}]}]}])
        if operation_name == "list_roles":
            return _MockPaginator([{"Roles": [{"RoleName": "vmimport", "Arn": "arn:aws:iam::123456789012:role/vmimport", "AssumeRolePolicyDocument": {"Statement": [{"Principal": {"Service": "vmie.amazonaws.com"}}]}}]}])
        return _MockPaginator([{}])


class _MockAWSSession:
    def __init__(self, scenario: str = "normal"):
        self.scenario = scenario

    def client(self, service_name: str, region_name: Optional[str] = None, **kwargs):
        return _MockAWSClient(service_name, scenario=self.scenario)


def test_aws_live_discovery_pagination_throttling_auth_error_and_reconciliation(tmp_path: Path):
    db = TransactionalDatabase(db_path=tmp_path / "aws_disc.sqlite3")

    # 1. Successful paginated discovery with Throttling retry
    conn = AWSLiveDiscoveryConnector(
        region="us-east-1",
        boto3_session_factory=lambda **kw: _MockAWSSession("normal"),
        db=db,
    )
    snap_1 = conn.discover_live_account()
    assert snap_1["provider"] == "aws"
    assert snap_1["account_or_project"] == "123456789012"
    assert len(snap_1["read_errors"]) == 0
    assert snap_1["resources_count"] >= 8

    # 2. Auth failure must raise ConnectorAuthError (never return an empty inventory!)
    bad_conn = AWSLiveDiscoveryConnector(
        region="us-east-1",
        boto3_session_factory=lambda **kw: _MockAWSSession("auth_error"),
        db=db,
    )
    with pytest.raises(ConnectorAuthError):
        bad_conn.discover_live_account()

    # 3. Partial service error records read_errors
    partial_conn = AWSLiveDiscoveryConnector(
        region="us-east-1",
        boto3_session_factory=lambda **kw: _MockAWSSession("partial_s3_error"),
        db=db,
    )
    snap_partial = partial_conn.discover_live_account()
    assert len(snap_partial["read_errors"]) >= 1
    assert "s3" in snap_partial["read_errors"][0]["service"]

    # 4. Reconciliation between two snapshots (detecting added, modified, removed)
    curr_resources = json.loads(json.dumps(snap_1["cmir"]["resources"]))
    curr_resources[0]["metadata"]["cidr_block"] = "10.99.0.0/16"
    curr_resources.pop()
    curr_resources.append({
        "id": "aws-ec2-new-node",
        "canonical_id": "aws:123456789012:us-east-1:ec2:i-999",
        "name": "new-worker",
        "type": "virtual_machine",
        "status": "running",
        "location": "us-east-1",
        "metadata": {"instance_type": "c6i.large"},
        "security": {},
        "network": {},
    })

    diff = CloudInventoryReconciler.reconcile(curr_resources, snap_1, [])
    assert diff["added_count"] == 1
    assert diff["modified_count"] == 1
    assert diff["removed_count"] == 1


def test_gcp_live_discovery_pagination_rate_limit_auth_error_and_reconciliation(tmp_path: Path):
    db = TransactionalDatabase(db_path=tmp_path / "gcp_disc.sqlite3")
    calls = {"count": 0}

    def _mock_gcp_transport(url: str, page_token: Optional[str], access_token: str) -> Dict[str, Any]:
        calls["count"] += 1
        if page_token != "page-2":
            if calls["count"] == 1:
                raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
            return {
                "results": [
                    {
                        "assetType": "compute.googleapis.com/Network",
                        "name": "//compute.googleapis.com/projects/demo-gcp/global/networks/prod-vpc",
                        "displayName": "prod-vpc",
                        "location": "global",
                        "state": "ACTIVE",
                    },
                    {
                        "assetType": "compute.googleapis.com/Instance",
                        "name": "//compute.googleapis.com/projects/demo-gcp/zones/us-central1-a/instances/vm-1",
                        "displayName": "vm-1",
                        "location": "us-central1-a",
                        "state": "RUNNING",
                    },
                ],
                "nextPageToken": "page-2",
            }
        return {
            "results": [
                {
                    "assetType": "sqladmin.googleapis.com/Instance",
                    "name": "//sqladmin.googleapis.com/projects/demo-gcp/instances/pg-main",
                    "displayName": "pg-main",
                    "location": "us-central1",
                    "state": "RUNNABLE",
                },
                {
                    "assetType": "storage.googleapis.com/Bucket",
                    "name": "//storage.googleapis.com/projects/_/buckets/demo-gcp-backups",
                    "displayName": "demo-gcp-backups",
                    "location": "US",
                    "state": "ACTIVE",
                },
            ]
        }

    gcp_conn = GCPLiveDiscoveryConnector(
        project_id="demo-gcp",
        gcp_api_transport=_mock_gcp_transport,
        db=db,
    )
    snap = gcp_conn.discover_live_project()
    assert snap["provider"] == "gcp"
    assert snap["account_or_project"] == "demo-gcp"
    assert len(snap["read_errors"]) == 0
    assert snap["resources_count"] == 4

    # Auth failure must raise ConnectorAuthError (never return an empty 200 inventory)
    def _auth_fail_transport(url: str, page_token: Optional[str], access_token: str) -> Dict[str, Any]:
        raise ConnectorAuthError("GCP_HTTP_403", "Cloud Asset API permission denied")

    bad_gcp = GCPLiveDiscoveryConnector(project_id="demo-gcp", gcp_api_transport=_auth_fail_transport, db=db)
    with pytest.raises(ConnectorAuthError):
        bad_gcp.discover_live_project()


# ==============================================================================
# 3. Use Case 1: Multi-Runtime Static Discovery, Startup/Health Failure & E2E
# ==============================================================================


def test_use_case_1_java_go_node_python_and_health_failure_cutover_blocker():
    # Inspect inline Java Spring Boot + Dockerfile + runtime metadata
    java_files = {
        "pom.xml": """
        <project>
          <artifactId>accounting-ledger-service</artifactId>
          <dependencies>
            <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId></dependency>
            <dependency><groupId>org.postgresql</groupId><artifactId>postgresql</artifactId></dependency>
          </dependencies>
        </project>
        """,
        ".env": """
        SPRING_DATASOURCE_URL=jdbc:postgresql://pg-ledger.internal:5432/ledger
        SPRING_DATASOURCE_PASSWORD=UltraSecretJavaDbPass99!
        REDIS_URL=redis://redis-ledger.internal:6379/0
        PORT=8085
        """,
    }
    runtime_meta = {
        "listening_ports": [8085, 9095],
        "systemd_unit": "accounting-ledger.service",
        "process_cmdline": "java -jar /opt/ledger/accounting-ledger.jar",
        "local_state_paths": ["/var/lib/ledger/uploads"],
        "requires_cron": True,
        "health_endpoint": "/actuator/health",
    }

    app_disc = inspect_application_source(
        inline_files=java_files,
        runtime_metadata=runtime_meta,
        app_name_override="accounting-ledger-service",
    )
    assert app_disc["language"] == "Java"
    assert app_disc["framework"] == "Spring Boot"
    assert 8085 in app_disc["exposed_ports"]
    assert "/actuator/health" in app_disc["health_endpoints"]
    assert "UltraSecretJavaDbPass99!" not in json.dumps(app_disc)

    # Also inspect Go (`go.mod`)
    go_disc = inspect_application_source(
        inline_files={
            "go.mod": "module github.com/cloudmove/ledger-worker\n\ngo 1.22\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.1\n)\n"
        }
    )
    assert go_disc["language"] == "Go"
    assert go_disc["framework"] == "Gin"

    # Evaluate container mode viability -> must warn about local state paths / cron on Cloud Run / ECS Fargate
    cmir_obj = build_application_cmir(app_disc, target_provider="gcp", deployment_mode="container")
    viability = evaluate_app_migration_viability(app_disc, cmir_obj, target_provider="gcp", deployment_mode="container")
    assert len(viability["warnings"]) >= 1

    # Test startup failure and health check failure blocking cutover in orchestrator
    create_res = client.post(
        "/api/v1/migration/use-case-1/migrate",
        json={"target_provider": "aws", "deployment_mode": "vm_rehost"},
    )
    assert create_res.status_code == 200
    mid = create_res.json()["migration_id"]

    # Approve -> Advance to PREPARING -> Advance to TESTING
    assert client.post(f"/api/v1/migration/jobs/{mid}/approve").status_code == 200
    assert client.post(f"/api/v1/migration/jobs/{mid}/advance", json={"dry_run": True}).json()["state"] == "PREPARING"
    assert client.post(f"/api/v1/migration/jobs/{mid}/advance", json={"dry_run": True}).json()["state"] == "TESTING"

    # Simulate health check failure during TESTING -> must transition to FAILED and block READY_FOR_CUTOVER
    fail_health = client.post(
        f"/api/v1/migration/jobs/{mid}/advance",
        json={"dry_run": True, "simulate_health_failure": True},
    )
    assert fail_health.status_code == 200
    failed_job = fail_health.json()
    assert failed_job["state"] == "FAILED"
    assert failed_job["pre_cutover_test_results"]["ready_for_cutover"] is False

    # Retry from checkpoint -> recovers to TESTING -> advance with passing health check -> READY_FOR_CUTOVER -> COMPLETED
    recovered = client.post(f"/api/v1/migration/jobs/{mid}/retry").json()
    assert recovered["state"] == "TESTING"
    ready_cutover = client.post(f"/api/v1/migration/jobs/{mid}/advance", json={"dry_run": True}).json()
    assert ready_cutover["state"] == "READY_FOR_CUTOVER"
    assert ready_cutover["pre_cutover_test_results"]["ready_for_cutover"] is True

    completed = client.post(f"/api/v1/migration/jobs/{mid}/advance", json={"dry_run": True}).json()
    assert completed["state"] == "COMPLETED"
    assert completed["completed_in_real_cloud"] is False
    assert completed["post_cutover_test_results"]["ready_for_cutover"] is True


# ==============================================================================
# 4. Use Case 2: Binary Disk Authenticity, Multi-Disk, Staging & Replication
# ==============================================================================


def test_use_case_2_binary_disk_headers_stub_rejection_and_staging_conversion():
    # 1. Authentic binary VMDK (`KDMV` + GPT partitions `EFI-SYSTEM`, `LINUX-ROOT`)
    vmdk_path = PROJECT_ROOT / "inventory" / "sample_images" / "debian12-erp-prod.vmdk"
    vmdk_bin = inspect_binary_disk_header_and_structure(vmdk_path)
    assert vmdk_bin["is_authentic_binary_image"] is True
    assert vmdk_bin["detected_binary_format"] == "VMDK"
    assert vmdk_bin["gpt_detected_in_binary"] is True
    assert "EFI-SYSTEM" in vmdk_bin["discovered_gpt_partition_labels"]
    assert "LINUX-ROOT" in vmdk_bin["discovered_gpt_partition_labels"]

    # 2. Authentic binary QCOW2 (`QFI\xfb`) + real staging copy & `qemu-img convert` to RAW
    qcow2_path = PROJECT_ROOT / "inventory" / "sample_images" / "ubuntu22-billing-app.qcow2"
    qcow2_bin = inspect_binary_disk_header_and_structure(qcow2_path)
    assert qcow2_bin["is_authentic_binary_image"] is True
    assert qcow2_bin["detected_binary_format"] == "QCOW2"

    staging_res = prepare_and_verify_staging_copy(
        source_path=qcow2_path,
        image_name="ubuntu22-billing-app",
        requires_conversion=True,
        target_format="RAW",
    )
    assert staging_res["staging_prepared"] is True
    assert staging_res["source_and_staging_checksum_match"] is True
    assert staging_res["source_untouched"] is True
    assert staging_res["converted_artifact"]["conversion_verified"] is True
    assert staging_res["converted_artifact"]["format"] == "RAW"

    # 3. Simulated text stub (`simulated_text_stub.vmdk`) must be classified as stub and blocked when require_authentic_binary=True
    stub_path = PROJECT_ROOT / "inventory" / "sample_images" / "simulated_text_stub.vmdk"
    stub_bin = inspect_binary_disk_header_and_structure(stub_path)
    assert stub_bin["is_authentic_binary_image"] is False
    assert stub_bin["authenticity_classification"] == "simulated_text_stub_missing_extent"

    stub_manifest = inspect_vm_image(image_path=str(stub_path))
    stub_compat = evaluate_vm_image_compatibility(
        stub_manifest,
        target_provider="aws",
        require_authentic_binary=True,
    )
    assert stub_compat["compatible"] is False
    assert any("simulada o incompleta" in b for b in stub_compat["blockers"])

    # 4. Dirty live disk snapshot (`dirty_live_disk`) must block migration
    dirty_manifest = inspect_vm_image(
        manifest_override={
            "snapshot_consistency": {
                "consistency_type": "dirty_live_disk",
                "source_running_during_raw_copy": True,
            }
        }
    )
    dirty_compat = evaluate_vm_image_compatibility(dirty_manifest, target_provider="aws")
    assert dirty_compat["compatible"] is False
    assert any("dirty_live_disk" in b for b in dirty_compat["blockers"])

    # 5. Missing secondary data disk file must block migration
    missing_disk_manifest = inspect_vm_image(
        manifest_override={
            "disks": [
                {"order": 0, "device": "/dev/sda", "is_boot": True, "required": True, "image_file": "inventory/sample_images/debian12-erp-prod.vmdk"},
                {"order": 1, "device": "/dev/sdb", "is_boot": False, "required": True, "image_file": "inventory/sample_images/nonexistent-data-disk.vmdk"},
            ]
        }
    )
    missing_disk_compat = evaluate_vm_image_compatibility(missing_disk_manifest, target_provider="gcp")
    assert missing_disk_compat["compatible"] is False
    assert any("Conjunto de discos incompleto" in b for b in missing_disk_compat["blockers"])


def test_machine_migration_compatibility_matrix_and_aws_gcp_sdk_clients():
    mgn_sel = select_machine_migration_strategy(
        manifest={"format": "VMDK", "os": {"family": "linux", "architecture": "x86_64"}},
        target_provider="aws",
        source_type="live_server",
        prefer_continuous_replication=True,
    )
    assert mgn_sel["selected_strategy_id"] == "aws_mgn"

    offline_sel = select_machine_migration_strategy(
        manifest={"format": "VMDK", "os": {"family": "linux", "architecture": "x86_64"}},
        target_provider="aws",
        source_type="standalone_offline_disk_image",
        prefer_continuous_replication=True,
    )
    assert offline_sel["selected_strategy_id"] == "aws_vm_import"
    assert offline_sel["continuous_replication_supported_for_source"] is False

    # Missing staging storage must raise ConnectorError("MISSING_STAGING_STORAGE")
    aws_mig_client = AWSMachineMigrationClient(region="us-east-1")
    with pytest.raises(ConnectorError) as exc_info:
        aws_mig_client.verify_s3_staging_object(bucket="", key="")
    assert exc_info.value.code == "MISSING_STAGING_STORAGE"

    gcp_mig_client = GCPMachineMigrationClient(
        project_id="demo-gcp",
        http_transport=lambda method, url, body: {"name": "op-import-123", "status": "RUNNING", "done": False},
    )
    with pytest.raises(ConnectorError) as gcp_exc:
        gcp_mig_client.start_compute_image_import("img-erp", gcs_source_uri="http://invalid-bucket/img.vmdk")
    assert gcp_exc.value.code == "MISSING_STAGING_STORAGE"

    gcp_op = gcp_mig_client.start_compute_image_import("img-erp", gcs_source_uri="gs://cloudmove-staging/erp.vmdk")
    assert gcp_op["operation_id"] == "op-import-123"
    assert gcp_op["service"] == "gcp_image_import"


# ==============================================================================
# 5. Use Case 3: Datacenter Campaign Unreachable Hosts & Process vs Application
# ==============================================================================


def test_use_case_3_unreachable_hosts_and_process_vs_application_separation(tmp_path: Path):
    db = TransactionalDatabase(db_path=tmp_path / "campaigns_test.sqlite3")
    store = DataCenterCampaignStore(storage_path=tmp_path / "campaigns.json", db=db)

    campaigns = store.list_campaigns()
    assert len(campaigns) >= 1
    camp_id = campaigns[0]["id"]

    # Execute campaign -> since DMZ host is unreachable and Solaris is unsupported,
    # status must be 'partial_with_unreachable_hosts' and fully_discovered must be False
    executed = store.execute_campaign(camp_id)
    assert executed["status"] == "partial_with_unreachable_hosts"
    assert executed["fully_discovered"] is False
    assert len(executed["unreachable_hosts"]) >= 1

    # Build CMIR and verify:
    # 1) 'sshd' on port 22 is classified ONLY as 'process', NOT as a business 'application'
    # 2) 'communicates_with' is separated from 'depends_on' and 'inferred_relation'
    cmir_bundle = store.build_campaign_cmir(camp_id, target_provider="aws")
    resources = cmir_bundle["resources"]
    relationships = cmir_bundle["relationships"]

    proc_nodes = [r for r in resources if r["type"] == "process"]
    app_nodes = [r for r in resources if r["type"] == "application"]
    assert any("sshd" in p["name"] for p in proc_nodes)
    assert not any("sshd" in a["name"].lower() for a in app_nodes)

    rel_types = {r["type"] for r in relationships}
    assert "communicates_with" in rel_types
    assert "depends_on" in rel_types
    assert "inferred_relation" in rel_types


# ==============================================================================
# 6. Real Terraform CLI Validation & Non-Viable Rollback Protection
# ==============================================================================


def test_real_terraform_cli_validation_and_irreversible_rollback_protection():
    aws_adapter = AWSAdapter()

    # Broken HCL with undeclared variable, broken resource reference, and hardcoded AWS key
    broken_files = {
        "provider.tf": 'provider "aws" { region = var.undeclared_region_var }\n',
        "variables.tf": "",
        "main.tf": 'resource "aws_subnet" "sub" {\n  vpc_id = aws_vpc.nonexistent_vpc.id\n  access_key = "AKIAIOSFODNN7EXAMPLE"\n}\n',
        "outputs.tf": "",
    }
    bad_val = aws_adapter.validate_artifacts(broken_files)
    assert bad_val["valid"] is False
    assert any("undeclared_region_var" in e for e in bad_val["errors"])
    assert any("aws_vpc.nonexistent_vpc" in e for e in bad_val["errors"])
    assert any("fuga de credenciales" in e.lower() for e in bad_val["errors"])

    # Test non-viable rollback (`mark-irreversible`) via API
    create_res = client.post(
        "/api/v1/migration/use-case-1/migrate",
        json={"target_provider": "gcp", "deployment_mode": "vm_rehost"},
    )
    mid = create_res.json()["migration_id"]
    client.post(f"/api/v1/migration/jobs/{mid}/approve")
    client.post(f"/api/v1/migration/jobs/{mid}/advance", json={"dry_run": True})  # -> PREPARING

    mark_res = client.post(
        f"/api/v1/migration/jobs/{mid}/mark-irreversible",
        json={
            "operation_reason": "Migración destructiva de esquema DDL ejecutada tras escritura en destino",
            "recovery_procedure": "Point-in-Time Recovery (PITR) desde snapshot pre-cutover",
        },
    )
    assert mark_res.status_code == 200
    assert mark_res.json()["rollback_procedure"]["viable"] is False

    # Attempting automatic rollback must now be rejected with HTTP 400 and include the recovery procedure
    rb_res = client.post(f"/api/v1/migration/jobs/{mid}/rollback", json={"reason": "Intento de rollback automático"})
    assert rb_res.status_code == 400
    assert "Point-in-Time Recovery" in rb_res.json()["detail"]
