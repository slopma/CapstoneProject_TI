"""
Cloud Credentials Verification, Live Terraform Deployment, Instance Probes & AWS Account Audit Endpoints.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.routers.migration_helpers import (
    infer_public_api_url,
    probe_http_endpoint,
    probe_tcp_port,
    resolve_facade_probe_fn,
    resolve_probe_targets,
    sanitize_probe_host,
    sync_job_after_terraform,
)
from app.api.routers.migration_schemas import (
    AwsAccountAuditRequest,
    AwsAuditDeleteResourceRequest,
    DeployLiveJobRequest,
    ExecuteTerraformCommandRequest,
    ValidateExternalCredentialRequest,
    VerifyCloudCredentialsRequest,
)
from app.migration.orchestrator import migration_orchestrator

router = APIRouter()


@router.post("/credentials/validate-external")
def validate_external_credential_endpoint(request: ValidateExternalCredentialRequest):
    """Safely validate external BaaS or API credentials without storing secrets."""
    from app.migration.external_services import validate_external_credentials

    return validate_external_credentials(request.service_type, request.credentials)


@router.post("/credentials/verify-cloud")
def verify_cloud_credentials_endpoint(request: VerifyCloudCredentialsRequest):
    """Verify cloud provider authentication (e.g. AWS STS Caller Identity) for deployment."""
    from app.migration.cloud_deployer import cloud_deployer

    return cloud_deployer.verify_cloud_provider_credentials(request.provider, request.credentials)


@router.get("/jobs/{migration_id}/terraform/status")
def get_job_terraform_status_endpoint(migration_id: str):
    """Retrieve real-time Terraform execution status, logs, and live `terraform.tfstate` outputs."""
    try:
        job = migration_orchestrator.get_migration(migration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    from app.migration.cloud_deployer import cloud_deployer

    job_dir = cloud_deployer.resolve_job_dir(migration_id, job)
    artifacts = job.get("generated_artifacts") or {}
    files = artifacts.get("files") or {}
    if files and not (job_dir / "main.tf").exists():
        cloud_deployer.materialize_job_files(job_dir, artifacts_files=files)

    return cloud_deployer.get_terraform_status(migration_id, job_dir)


@router.post("/jobs/{migration_id}/terraform/command")
def execute_job_terraform_command_endpoint(
    migration_id: str,
    http_request: Request,
    request: Optional[ExecuteTerraformCommandRequest] = None,
):
    """Execute a specific Terraform CLI command in the job's workspace."""
    req = request or ExecuteTerraformCommandRequest(action="plan")
    try:
        job = migration_orchestrator.get_migration(migration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if job.get("use_case") == "vm_image" and req.action.lower().strip() in (
        "plan",
        "apply",
        "continue",
        "full_deploy",
        "dry_run",
    ):
        try:
            job = migration_orchestrator.refresh_uc2_stage_binding(
                migration_id,
                public_api_url=infer_public_api_url(http_request),
            )
        except Exception:
            pass

    from app.migration.cloud_deployer import cloud_deployer

    job_dir = cloud_deployer.resolve_job_dir(migration_id, job)
    artifacts = job.get("generated_artifacts") or {}
    files = artifacts.get("files") or {}

    return cloud_deployer.execute_terraform_command(
        migration_id=migration_id,
        job_dir=job_dir,
        action=req.action,
        provider=job.get("target_provider", "aws"),
        credentials=req.credentials,
        secrets=req.secrets,
        artifacts_files=files,
        async_exec=req.async_exec,
        on_complete=lambda res: sync_job_after_terraform(migration_id, res),
    )


@router.post("/jobs/{migration_id}/terraform/cancel")
def cancel_job_terraform_command_endpoint(migration_id: str):
    """Immediately cancel running Terraform subprocess and release stale lock."""
    try:
        job = migration_orchestrator.get_migration(migration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    from app.migration.cloud_deployer import cloud_deployer

    job_dir = cloud_deployer.resolve_job_dir(migration_id, job)
    return cloud_deployer.cancel_terraform_execution(migration_id, job_dir)


@router.delete("/jobs/{migration_id}/terraform/logs")
def clear_job_terraform_logs_endpoint(migration_id: str):
    """Clear persisted and in-memory Terraform execution logs for `migration_id`."""
    try:
        job = migration_orchestrator.get_migration(migration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    from app.migration.cloud_deployer import cloud_deployer

    job_dir = cloud_deployer.resolve_job_dir(migration_id, job)
    return cloud_deployer.clear_terraform_logs(migration_id, job_dir)


@router.post("/jobs/{migration_id}/regenerate")
def regenerate_job_artifacts_endpoint(migration_id: str, re_inspect: bool = Query(True)):
    """Regenerate CMIR and Terraform manifests and update the deployment workspace."""
    try:
        updated_job = migration_orchestrator.regenerate_job_artifacts(
            migration_id=migration_id,
            re_inspect=re_inspect,
        )
        from app.migration.cloud_deployer import cloud_deployer

        job_dir = cloud_deployer.resolve_job_dir(migration_id, updated_job)
        return {
            "success": True,
            "job": updated_job,
            "terraform_status": cloud_deployer.get_terraform_status(migration_id, job_dir),
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs/{migration_id}/deploy-live")
def deploy_live_migration_job_endpoint(
    migration_id: str,
    http_request: Request,
    request: Optional[DeployLiveJobRequest] = None,
):
    """Execute autonomous cloud deployment directly using Terraform & Cloud SDKs."""
    req = request or DeployLiveJobRequest()
    try:
        job = migration_orchestrator.get_migration(migration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if job.get("use_case") == "vm_image":
        try:
            job = migration_orchestrator.refresh_uc2_stage_binding(
                migration_id,
                public_api_url=infer_public_api_url(http_request),
            )
        except Exception:
            pass

    from app.migration.cloud_deployer import cloud_deployer

    job_dir = cloud_deployer.resolve_job_dir(migration_id, job)
    artifacts = job.get("generated_artifacts") or {}
    files = artifacts.get("files") or {}

    deploy_res = cloud_deployer.execute_job_deployment(
        job_dir=job_dir,
        provider=job.get("target_provider", "aws"),
        dry_run=req.dry_run,
        credentials=req.credentials,
        secrets=req.secrets,
        artifacts_files=files,
        migration_id=migration_id,
    )

    if deploy_res.get("success") and not req.dry_run:
        sync_job_after_terraform(migration_id, deploy_res)

    return deploy_res


@router.get("/probe-instance-status")
def probe_instance_status(
    ip: str = Query(..., description="Public IP address or hostname of the deployed instance"),
    migration_id: Optional[str] = Query(None, description="Optional migration job ID to derive application ports"),
    frontend_port: Optional[int] = Query(None, ge=1, le=65535, description="Target frontend TCP port"),
    backend_port: Optional[int] = Query(None, ge=1, le=65535, description="Target backend API TCP port"),
    health_path: Optional[str] = Query(None, description="Backend HTTP healthcheck path"),
):
    """Safely probe an external deployed instance endpoint from the CloudMove server."""
    clean_ip = sanitize_probe_host(ip)
    fe_port, be_port, clean_hp = resolve_probe_targets(
        migration_id=migration_id,
        frontend_port=frontend_port,
        backend_port=backend_port,
        health_path=health_path,
    )

    fe_url = f"http://{clean_ip}:{fe_port}"
    be_url = f"http://{clean_ip}:{be_port}{clean_hp}"

    tcp_fn = resolve_facade_probe_fn("_probe_tcp_port", probe_tcp_port)
    http_fn = resolve_facade_probe_fn("_probe_http_endpoint", probe_http_endpoint)

    with ThreadPoolExecutor(max_workers=3) as pool:
        ssh_fut = pool.submit(tcp_fn, clean_ip, 22, 2.0)
        fe_fut = pool.submit(http_fn, fe_url, 2.5)
        be_fut = pool.submit(http_fn, be_url, 2.5)
        ssh_ok = ssh_fut.result()
        fe_probe = fe_fut.result()
        be_probe = be_fut.result()

    all_ready = fe_probe["online"] and be_probe["online"]

    if all_ready:
        phase = "ready"
        summary = "Servicios en línea y respondiendo exitosamente (HTTP 200). Listo para acceder."
    elif ssh_ok:
        phase = "booting"
        summary = "Instancia EC2 activa. Cloud-Init está completando el aprovisionamiento (~1-2 min)..."
    else:
        phase = "offline"
        summary = "Instancia no accesible aún. Verifica que haya terminado de iniciar en AWS y la sesión del laboratorio esté activa."

    return {
        "ip": clean_ip,
        "ssh": {"port": 22, "open": ssh_ok},
        "frontend": {
            "port": fe_port,
            "url": fe_url,
            "online": fe_probe["online"],
            "status": fe_probe["status"],
            "message": fe_probe["message"],
        },
        "backend": {
            "port": be_port,
            "url": be_url,
            "online": be_probe["online"],
            "status": be_probe["status"],
            "message": be_probe["message"],
        },
        "phase": phase,
        "all_ready": all_ready,
        "summary": summary,
    }


def _run_and_sync_aws_audit(credentials: Optional[dict]) -> dict:
    from app.migration.cloud_deployer import cloud_deployer

    res = cloud_deployer.audit_aws_account(
        credentials=credentials,
        jobs_lookup_fn=migration_orchestrator.list_migrations,
    )
    for ev in res.get("ip_sync_events") or []:
        mig_id = ev.get("migration_id")
        if mig_id:
            try:
                job_dir = cloud_deployer.resolve_job_dir(mig_id)
                st = cloud_deployer.get_terraform_status(mig_id, job_dir)
                sync_job_after_terraform(mig_id, st)
            except Exception:
                pass
    return res


@router.get("/cloud-audit/aws")
def get_aws_account_audit():
    """Query active AWS account resources and local workspaces."""
    return _run_and_sync_aws_audit(credentials=None)


@router.post("/cloud-audit/aws")
def post_aws_account_audit(request: Optional[AwsAccountAuditRequest] = None):
    """Query active AWS account resources using explicitly provided session credentials."""
    req = request or AwsAccountAuditRequest()
    return _run_and_sync_aws_audit(credentials=req.credentials)


@router.post("/cloud-audit/aws/delete-resource")
def delete_aws_audit_resource_endpoint(request: AwsAuditDeleteResourceRequest):
    """Terminate or delete an AWS resource or Terraform workspace discovered in the audit."""
    from app.migration.cloud_deployer import cloud_deployer

    return cloud_deployer.delete_aws_audit_resource(
        resource_type=request.resource_type,
        resource_id=request.resource_id,
        credentials=request.credentials,
        cleanup_vpc=request.cleanup_vpc,
    )
