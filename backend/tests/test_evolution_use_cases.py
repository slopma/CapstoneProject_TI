import json
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.cmir.normalizer import migrate_cmir_schema, normalize_inventory
from app.cmir.validator import validate_cmir
from app.graph.builder import build_graph
from app.dependencies.resolver import resolve_dependencies
from app.adapters.gcp_adapter import GCPAdapter
from app.generators.terraform import generate_gcp_terraform_files


client = TestClient(app)


def test_cmir_v2_1_schema_migration_and_provenance():
    legacy_payload = {
        "name": "legacy-v1-arch",
        "provider": "onprem",
        "version": "1.0",
        "resources": [
            {
                "id": "vm-legacy-01",
                "name": "Legacy App VM",
                "type": "virtual_machine",
                "metadata": {"data_state": "observed", "provenance": "ssh_collector"},
            },
            {
                "id": "db-legacy-01",
                "name": "Legacy Shared DB",
                "type": "database_instance",
                "is_shared": True,
            },
        ],
        "relationships": [
            {
                "source": "vm-legacy-01",
                "target": "db-legacy-01",
                "type": "inferred_relation",
                "metadata": {"reason": "Observed TCP 5432 socket"},
            }
        ],
    }

    migrated = migrate_cmir_schema(legacy_payload, target_version="2.1")
    assert migrated["version"] == "2.1"
    assert migrated["metadata"]["migrated_from_version"] == "1.0"

    cmir = normalize_inventory(legacy_payload)
    assert cmir.version == "2.1"
    vm_node = cmir.get_node("vm-legacy-01")
    assert vm_node is not None
    assert vm_node.canonical_id == "vm-legacy-01"
    assert vm_node.epistemic_state == "observed"
    assert vm_node.source_connector == "ssh_collector"

    rel = cmir.relationships[0]
    assert rel.epistemic_state == "inferred"
    assert rel.confidence < 1.0

    val = validate_cmir(cmir)
    assert val["valid"] is True
    assert val["inferred_relationships_count"] == 1
    assert any("inferida" in w for w in val["warnings"])


def test_dependency_resolver_separates_inferred_and_protects_shared():
    payload = {
        "name": "dep-test-arch",
        "provider": "aws",
        "version": "2.1",
        "resources": [
            {"id": "app-a", "name": "App A", "type": "application"},
            {"id": "app-b", "name": "App B", "type": "application"},
            {"id": "db-shared", "name": "Shared Postgres", "type": "database_instance", "is_shared": True},
            {"id": "cache-inferred", "name": "Inferred Redis", "type": "cache", "epistemic_state": "inferred"},
        ],
        "relationships": [
            {"source": "app-a", "target": "db-shared", "type": "depends_on", "epistemic_state": "observed"},
            {"source": "app-b", "target": "db-shared", "type": "depends_on", "epistemic_state": "observed"},
            {"source": "app-a", "target": "cache-inferred", "type": "inferred_relation", "epistemic_state": "inferred"},
        ],
    }
    cmir = normalize_inventory(payload)
    graph = build_graph(cmir)

    # 1. Without validating shared or including inferred
    res = resolve_dependencies(graph, ["app-a"], validated_shared_resources=None, include_inferred=False)
    assert "db-shared" in res["required_direct"]
    assert "db-shared" in res["confirmed_dependencies"]
    assert "db-shared" in res["shared_dependencies"]
    assert "cache-inferred" in res["inferred_dependencies"]
    assert "cache-inferred" not in res["required_direct"]

    # Shared resource must NOT be auto-migrated without validation
    policy = res["shared_dependency_policies"]["db-shared"]
    assert policy["auto_migrate"] is False
    assert policy["requires_validation"] is True
    assert "app-b" in policy["consumers_outside_selection"]
    assert "db-shared" not in res["auto_migratable_resources"]

    # 2. When shared resource is explicitly validated
    res_validated = resolve_dependencies(graph, ["app-a"], validated_shared_resources=["db-shared"])
    assert res_validated["shared_dependency_policies"]["db-shared"]["auto_migrate"] is True
    assert "db-shared" in res_validated["auto_migratable_resources"]


def test_gcp_adapter_and_exclusive_aws_gcp_provider_enforcement():
    # 1. Verify /api/v1/migration/providers lists only AWS and GCP and excludes Azure
    prov_resp = client.get("/api/v1/migration/providers")
    assert prov_resp.status_code == 200
    prov_data = prov_resp.json()
    assert prov_data["supported_providers"] == ["aws", "gcp"]
    assert "azure" in prov_data["excluded_providers"]

    # 2. Verify Azure is rejected in migration endpoints
    az_resp = client.post(
        "/api/v1/migration/generate",
        json={"resources": ["payment-api"], "target_provider": "azure"},
    )
    assert az_resp.status_code == 400
    assert "aws" in az_resp.json()["detail"].lower()
    assert "gcp" in az_resp.json()["detail"].lower()

    # 3. Verify GCP generation works end-to-end on the enterprise inventory
    gcp_resp = client.post(
        "/api/v1/migration/generate",
        json={"resources": ["backend-api-vm"], "target_provider": "gcp"},
    )
    assert gcp_resp.status_code == 200
    gcp_body = gcp_resp.json()
    assert gcp_body["target"] == "gcp"
    assert gcp_body["completed_in_real_cloud"] is False
    assert "hashicorp/google" in gcp_body["files"]["provider.tf"]
    assert "google_compute_network" in gcp_body["files"]["main.tf"]
    assert "google_compute_instance" in gcp_body["files"]["main.tf"]

    # 4. Verify Discovery Session -> GCP Terraform bridge
    import_resp = client.post("/api/v1/discovery/import-local")
    assert import_resp.status_code == 200
    sid = import_resp.json()["session_id"]

    tf_gcp_resp = client.get(f"/api/v1/discovery/sessions/{sid}/terraform?target_provider=gcp&strategy=replatform")
    assert tf_gcp_resp.status_code == 200
    tf_gcp = tf_gcp_resp.json()
    assert tf_gcp["target_provider"] == "gcp"
    assert "google_compute_instance" in tf_gcp["iac_code"]
    assert len(tf_gcp["traceability"]) >= 3


def test_use_case_1_application_guided_migration_and_secret_redaction():
    # Inspect default in-memory application for AWS
    insp_resp = client.post(
        "/api/v1/migration/use-case-1/inspect",
        json={"target_provider": "aws", "deployment_mode": "vm_rehost"},
    )
    assert insp_resp.status_code == 200
    data = insp_resp.json()
    app_info = data["application"]

    assert app_info["app_name"] == "app"
    assert app_info["language"] == "Python"
    assert app_info["framework"] == "FastAPI"
    assert 8080 in app_info["exposed_ports"]
    assert app_info["secrets_redacted_count"] >= 3

    # Verify secret values from docker-compose.yml NEVER appear in the response
    raw_dump = json.dumps(data)
    assert "SuperSecretPgPass99!" not in raw_dump
    assert "SuperSecretPassword123!" not in raw_dump
    assert "example-stripe-secret-key" not in raw_dump
    assert "ultra-confidential-jwt-signing-secret-do-not-leak" not in raw_dump
    assert "[REDACTED_SECRET]" in raw_dump

    # Verify dependency classification (confirmed, inferred, unknown)
    dep_sum = app_info["dependency_summary"]
    assert dep_sum["confirmed_count"] >= 2
    assert dep_sum["inferred_count"] >= 1
    assert dep_sum["unknown_count"] >= 1

    # Create full 12-stage orchestrated migration job for GCP
    mig_resp = client.post(
        "/api/v1/migration/use-case-1/migrate",
        json={"target_provider": "gcp", "deployment_mode": "container"},
    )
    assert mig_resp.status_code == 200
    job = mig_resp.json()
    assert job["use_case"] == "app_source"
    assert job["target_provider"] == "gcp"
    assert job["state"] == "PLAN_READY"
    assert len(job["ordered_stages"]) == 12
    assert "app.service" in job["generated_artifacts"]["files"]
    assert ".env.cloud.template" in job["generated_artifacts"]["files"]
    assert "smoke_test.sh" in job["generated_artifacts"]["files"]


def test_use_case_2_vm_image_migration_fidelity_qcow2_and_live_ram_blocker():
    # 1. Standard VMDK UEFI image migration to AWS
    mig_resp = client.post(
        "/api/v1/migration/use-case-2/migrate",
        json={"target_provider": "aws"},
    )
    assert mig_resp.status_code == 200
    job = mig_resp.json()
    assert job["use_case"] == "vm_image"
    assert job["state"] == "PLAN_READY"
    assert len(job["ordered_stages"]) == 13

    manifest = job["source_environment"]
    assert manifest["format"] == "VMDK"
    assert manifest["boot_mode"] == "UEFI"
    assert manifest["source_modified"] is False
    assert len(manifest["sha256"]) == 64
    assert len(manifest["disks"]) == 2

    compat = job["compatibility_assessment"]
    assert compat["compatible"] is True
    assert compat["source_image_untouched"] is True
    assert len(compat["fidelity_dimensions"]) >= 5

    diff_report = job["generated_artifacts"]["diff_report"]
    assert diff_report["parity_score_percent"] == 100.0
    assert len(diff_report["comparisons"]) >= 7

    # 2. QCOW2 format on AWS must flag format conversion (`qemu-img convert`)
    qcow2_resp = client.post(
        "/api/v1/migration/use-case-2/inspect",
        json={
            "target_provider": "aws",
            "manifest_override": {"format": "QCOW2", "drivers_present": ["virtio_blk"]},
        },
    )
    assert qcow2_resp.status_code == 200
    qcow2_compat = qcow2_resp.json()["compatibility"]
    assert qcow2_compat["requires_format_conversion"] is True
    assert "qemu-img convert" in qcow2_compat["conversion_plan"]["command"]
    assert "ena" in qcow2_compat["missing_cloud_drivers"]

    # 3. Requesting volatile live RAM transfer in disk image migration must block and transition to FAILED
    live_ram_resp = client.post(
        "/api/v1/migration/use-case-2/migrate",
        json={"target_provider": "aws", "require_live_memory_state": True},
    )
    assert live_ram_resp.status_code == 200
    blocked_job = live_ram_resp.json()
    assert blocked_job["state"] == "FAILED"
    assert len(blocked_job["blockers"]) >= 1
    assert "RAM" in blocked_job["blockers"][0]

    # 4. Operator remediation of volatile RAM blocker via quiesced snapshot advances cleanly to PLAN_READY
    rem_resp = client.post(
        f"/api/v1/migration/jobs/{blocked_job['migration_id']}/remediate-blocker",
        json={"action": "apply_quiesced_snapshot"},
    )
    assert rem_resp.status_code == 200
    remediated_job = rem_resp.json()
    assert remediated_job["state"] == "PLAN_READY"
    assert len(remediated_job["blockers"]) == 0
    assert remediated_job["source_config"]["require_live_memory_state"] is False


def test_use_case_3_datacenter_campaign_pause_resume_retry_cmir_and_migration():
    camps_resp = client.get("/api/v1/campaigns")
    assert camps_resp.status_code == 200
    campaign_id = camps_resp.json()["campaigns"][0]["id"]

    # 1. Pause campaign
    pause_resp = client.post(f"/api/v1/campaigns/{campaign_id}/pause?reason=Ventana_Mantenimiento")
    assert pause_resp.status_code == 200
    assert pause_resp.json()["status"] == "paused"

    # 2. Resume campaign without losing or duplicating assets
    resume_resp = client.post(f"/api/v1/campaigns/{campaign_id}/resume")
    assert resume_resp.status_code == 200
    resumed_data = resume_resp.json()
    assert resumed_data["resume_summary"]["preserved_assets_count"] == 7

    # 3. Retry discovery on unreachable DMZ host (`dmz-proxy-isolated-03`) and verify partial results preserved
    retry_resp = client.post(f"/api/v1/campaigns/{campaign_id}/assets/dmz-proxy-isolated-03/retry")
    assert retry_resp.status_code == 200
    retry_data = retry_resp.json()
    assert retry_data["reachable"] is False
    assert retry_data["partial_results_preserved"] is True

    # 4. Get full hierarchical CMIR v2.1 for the campaign
    cmir_resp = client.get(f"/api/v1/campaigns/{campaign_id}/cmir?target_provider=gcp")
    assert cmir_resp.status_code == 200
    cmir_data = cmir_resp.json()
    assert cmir_data["version"] == "2.1"
    node_types = {r["type"] for r in cmir_data["resources"]}
    assert "datacenter" in node_types
    assert "physical_host" in node_types
    assert "hypervisor" in node_types
    assert "virtual_machine" in node_types
    assert "operating_system" in node_types
    assert "database_instance" in node_types

    # 5. Plan workload migration to GCP
    mig_resp = client.post(
        f"/api/v1/campaigns/{campaign_id}/migrate",
        json={
            "target_provider": "gcp",
            "selected_resources": ["asset-vm-Middleware-rhel-02"],
        },
    )
    assert mig_resp.status_code == 200
    mig_bundle = mig_resp.json()
    assert mig_bundle["target_provider"] == "gcp"
    assert mig_bundle["migration_job"]["state"] == "PLAN_READY"
    assert "google_compute_instance" in mig_bundle["generated_iac"]["iac_code"]


def test_orchestrator_state_machine_approval_gate_failure_retry_and_rollback():
    # Create a new Use Case 1 job in PLAN_READY state
    create_resp = client.post(
        "/api/v1/migration/jobs",
        json={
            "name": "Test State Machine Lifecycle",
            "use_case": "app_source",
            "target_provider": "aws",
        },
    )
    assert create_resp.status_code == 200
    job = create_resp.json()
    mid = job["migration_id"]
    assert job["state"] == "PLAN_READY"

    # 1. Attempting to advance execution BEFORE approval must fail with 403
    premature_adv = client.post(f"/api/v1/migration/jobs/{mid}/advance", json={"dry_run": True})
    assert premature_adv.status_code == 403

    # 2. Approve migration -> APPROVED
    app_resp = client.post(
        f"/api/v1/migration/jobs/{mid}/approve",
        json={"approved_by": "lead-architect@cloudmove.local", "notes": "Aprobado para dry-run"},
    )
    assert app_resp.status_code == 200
    assert app_resp.json()["state"] == "APPROVED"

    # 3. Advance: APPROVED -> PREPARING
    prep_resp = client.post(f"/api/v1/migration/jobs/{mid}/advance", json={"dry_run": True})
    assert prep_resp.status_code == 200
    assert prep_resp.json()["state"] == "PREPARING"

    # 4. Simulate stage failure during PREPARING -> FAILED
    fail_resp = client.post(
        f"/api/v1/migration/jobs/{mid}/advance",
        json={"dry_run": True, "simulate_failure": True, "failure_reason": "Timeout simulado en S3/EBS staging"},
    )
    assert fail_resp.status_code == 200
    assert fail_resp.json()["state"] == "FAILED"

    # 5. Retry failed stage from checkpoint -> resumes PREPARING
    retry_resp = client.post(f"/api/v1/migration/jobs/{mid}/retry")
    assert retry_resp.status_code == 200
    assert retry_resp.json()["state"] == "PREPARING"

    # 6. Advance: PREPARING -> TESTING -> READY_FOR_CUTOVER -> COMPLETED (Dry-Run)
    test_resp = client.post(f"/api/v1/migration/jobs/{mid}/advance", json={"dry_run": True})
    assert test_resp.status_code == 200
    assert test_resp.json()["state"] == "TESTING"

    cut_resp = client.post(f"/api/v1/migration/jobs/{mid}/advance", json={"dry_run": True})
    assert cut_resp.status_code == 200
    assert cut_resp.json()["state"] == "READY_FOR_CUTOVER"

    comp_resp = client.post(f"/api/v1/migration/jobs/{mid}/advance", json={"dry_run": True})
    assert comp_resp.status_code == 200
    completed_job = comp_resp.json()
    assert completed_job["state"] == "COMPLETED"
    # Crucial honesty check: dry-run completion must NEVER claim real cloud completion
    assert completed_job["execution_mode"] == "simulated_dry_run"
    assert completed_job["completed_in_real_cloud"] is False

    # 7. Test Rollback on another job in TESTING state
    job2 = client.post(
        "/api/v1/migration/jobs",
        json={"name": "Rollback Test", "use_case": "vm_image", "target_provider": "gcp"},
    ).json()
    mid2 = job2["migration_id"]
    client.post(f"/api/v1/migration/jobs/{mid2}/approve")
    client.post(f"/api/v1/migration/jobs/{mid2}/advance", json={"dry_run": True})
    rb_resp = client.post(
        f"/api/v1/migration/jobs/{mid2}/rollback",
        json={"reason": "Diferencia detectada en prueba de humo"},
    )
    assert rb_resp.status_code == 200
    assert rb_resp.json()["state"] == "ROLLED_BACK"


def test_use_case_2_live_host_operating_system_capture_and_cloud_preparation():
    # 0. Live device probe query (real hardware inspection without preloads)
    dev_resp = client.get("/api/v1/migration/use-case-2/devices")
    assert dev_resp.status_code == 200
    dev_data = dev_resp.json()
    assert dev_data["queried_live"] is True
    assert "host" in dev_data
    assert "hostname" in dev_data["host"]
    assert len(dev_data["devices"]) >= 1
    assert dev_data["primary_boot_device"] is not None

    # 1. Capture live host operating system (files, /etc, fstab, services, packages, kernel)
    cap_resp = client.post(
        "/api/v1/migration/use-case-2/capture-live",
        json={"target_provider": "gcp", "output_format": "QCOW2"},
    )
    assert cap_resp.status_code == 200
    data = cap_resp.json()
    assert data["use_case"] == "vm_image"
    manifest = data["manifest"]
    assert manifest["is_live_capture"] is True
    assert manifest["source_type"] == "live_server"
    assert manifest["is_authentic_binary_image"] is True
    assert manifest["snapshot_consistency"]["consistency_type"] == "application_quiesced_snapshot"
    assert manifest["multi_disk_verification"]["all_volumes_accounted_for"] is True
    assert Path(manifest["source_file"]).is_file()
    assert Path(manifest["live_capture_details"]["config_archive"]).is_file()
    assert len(manifest["disks"]) >= 1

    # 2. Plan live OS migration into AWS orchestrator
    mig_resp = client.post(
        "/api/v1/migration/use-case-2/migrate",
        json={"target_provider": "aws", "capture_live_host": True, "output_format": "RAW"},
    )
    assert mig_resp.status_code == 200
    job = mig_resp.json()
    assert job["use_case"] == "vm_image"
    assert job["state"] == "PLAN_READY"
    assert len(job["ordered_stages"]) == 13
    assert job["source_environment"]["is_live_capture"] is True
    assert "diff_report" in job["generated_artifacts"]

    # 3. Verify Download Endpoints (bundle.zip, system-image, disk-image, deployment-guide)
    mid = job["migration_id"]
    bundle_resp = client.get(f"/api/v1/migration/jobs/{mid}/bundle.zip")
    assert bundle_resp.status_code == 200
    assert bundle_resp.headers["content-type"] == "application/zip"

    guide_resp = client.get(f"/api/v1/migration/jobs/{mid}/deployment-guide")
    assert guide_resp.status_code == 200
    guide_md = guide_resp.json()["deployment_guide_markdown"]
    assert "Paso 1: Descargar la Copia del SO" in guide_md
    assert "Paso 6: Restauracion de Configuraciones" in guide_md

    sys_img_resp = client.get(f"/api/v1/migration/jobs/{mid}/system-image")
    assert sys_img_resp.status_code == 200
    assert "gzip" in sys_img_resp.headers["content-type"]

    disk_img_resp = client.get(f"/api/v1/migration/jobs/{mid}/disk-image")
    assert disk_img_resp.status_code == 200


