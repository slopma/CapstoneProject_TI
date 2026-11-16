"""
Pydantic request schemas and shared input types for `/api/v1/migration`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SelectionRequest(BaseModel):
    resources: List[str]
    target_provider: str = "aws"
    validated_shared_resources: Optional[List[str]] = Field(
        default=None,
        description="Optional list of shared resource IDs explicitly validated by the architect",
    )
    include_inferred: bool = Field(
        default=True,
        description="Whether heuristically inferred dependencies should be included after validation",
    )


class CreateMigrationJobRequest(BaseModel):
    name: Optional[str] = Field(None, description="Human-readable name for the migration job")
    use_case: str = Field(..., description="app_source | vm_image")
    target_provider: str = Field("aws", description="Target cloud provider: 'aws' exclusively")
    target_config: Optional[Dict[str, Any]] = None
    source_config: Optional[Dict[str, Any]] = None
    auto_assess_and_plan: bool = True


class ApproveMigrationJobRequest(BaseModel):
    approved_by: str = Field("architect@cloudmove.local")
    notes: str = Field("")
    validated_shared_resources: Optional[List[str]] = None
    expected_version: Optional[int] = Field(None, description="Optimistic locking version")


class AdvanceMigrationJobRequest(BaseModel):
    dry_run: bool = Field(True)
    simulate_failure: bool = Field(False, description="Simulate stage execution failure")
    simulate_startup_failure: bool = Field(False, description="Simulate CloudMove target container/VM startup failure")
    simulate_health_failure: bool = Field(False, description="Simulate HTTP /health readiness probe failure")
    failure_reason: str = Field("Fallo simulado de conectividad o cuota en etapa de ejecución")
    operator_id: str = Field("operator@cloudmove.local")
    idempotency_key: Optional[str] = Field(None, description="Unique retry-safe idempotency key")
    expected_version: Optional[int] = Field(None, description="Optimistic locking version")


class RollbackOrCancelRequest(BaseModel):
    reason: str = Field("Rollback solicitado por el operador")
    expected_version: Optional[int] = None


class MarkIrreversibleRequest(BaseModel):
    operation_reason: str = Field("Migración final de esquema / cutover DNS con escritura activa en destino")
    recovery_procedure: Optional[str] = None


class RemediateBlockerRequest(BaseModel):
    action: str = Field("quiesce_snapshot", description="quiesce_snapshot | continuous_replication")
    operator_id: str = Field("architect@cloudmove.local")


class GitHubValidateRequest(BaseModel):
    github_url: str = Field(..., description="Public or private GitHub repository URL")
    github_token: Optional[str] = Field(None, description="Optional GitHub Personal Access Token for private repos")


class AppInspectRequest(BaseModel):
    source_path: Optional[str] = None
    github_url: Optional[str] = Field(None, description="Optional GitHub repo URL instead of local path")
    github_ref: Optional[str] = Field(None, description="Branch, tag, or commit SHA to pin")
    github_token: Optional[str] = Field(None, description="Optional GitHub PAT")
    inline_files: Optional[Dict[str, str]] = None
    runtime_metadata: Optional[Dict[str, Any]] = None
    target_provider: str = Field("aws")
    deployment_mode: str = Field("vm_rehost", description="vm_rehost | container")
    app_name: Optional[str] = None
    selected_components: Optional[List[str]] = None
    user_decisions: Optional[Dict[str, str]] = Field(None, description="User interactive choices from transformation catalog")


class UpdateArchitectureDecisionsRequest(BaseModel):
    user_decisions: Dict[str, str] = Field(default_factory=dict)


class ImageInspectRequest(BaseModel):
    image_path: Optional[str] = None
    manifest_override: Optional[Dict[str, Any]] = None
    target_provider: str = Field("aws")
    require_live_memory_state: bool = Field(False)
    require_authentic_binary: bool = Field(False, description="If true, rejects small simulated text stubs missing binary extents")
    source_type: str = Field("standalone_offline_disk_image", description="standalone_offline_disk_image | live_server | hypervisor_vm")
    prefer_continuous_replication: bool = Field(False)
    capture_live_host: bool = Field(False, description="Capture live host operating system where CloudMove/agent runs")
    output_format: str = Field("QCOW2", description="QCOW2 | RAW | VMDK")
    agent_id: Optional[str] = Field(None, description="Enrolled agent identifier if capturing remotely")
    user_decisions: Optional[Dict[str, str]] = Field(None, description="User choices for EBS volume sizing, compute mode, instance type, and SG ports")


class ValidateExternalCredentialRequest(BaseModel):
    service_type: str = "supabase"
    credentials: Dict[str, str] = Field(default_factory=dict)


class VerifyCloudCredentialsRequest(BaseModel):
    provider: str = "aws"
    credentials: Optional[Dict[str, str]] = None


class DeployLiveJobRequest(BaseModel):
    dry_run: bool = Field(False)
    credentials: Optional[Dict[str, str]] = None
    secrets: Optional[Dict[str, str]] = None


class ExecuteTerraformCommandRequest(BaseModel):
    action: str = Field(..., description="init | validate | plan | apply | continue | refresh | destroy | output | state | unlock | full_deploy | dry_run")
    credentials: Optional[Dict[str, str]] = None
    secrets: Optional[Dict[str, str]] = None
    async_exec: bool = Field(
        True,
        description="Run in background thread to allow live log streaming and immediate cancellation",
    )


class Uc2StageInitRequest(BaseModel):
    stage_id: Optional[str] = None
    selected_paths: List[str] = Field(default_factory=list)
    migration_id: Optional[str] = None
    agent_id: Optional[str] = None


class Uc2StageCommitRequest(BaseModel):
    selected_paths: List[str] = Field(default_factory=list)
    migration_id: Optional[str] = None
    ec2_ip: Optional[str] = None


class Uc2DispatchAgentStageRequest(BaseModel):
    selected_paths: List[str] = Field(default_factory=list)
    migration_id: Optional[str] = None
    agent_id: Optional[str] = None
    max_total_mb: int = Field(1500, ge=10, le=2048)


class Uc2BrowserFileItem(BaseModel):
    rel_path: str
    content_b64: str


class Uc2BrowserBatchRequest(BaseModel):
    files: List[Uc2BrowserFileItem] = Field(default_factory=list)
    selected_paths: List[str] = Field(default_factory=list)


class AwsAccountAuditRequest(BaseModel):
    credentials: Optional[Dict[str, str]] = None


class AwsAuditDeleteResourceRequest(BaseModel):
    resource_type: str = Field(..., description="ec2_instance | ebs_volume | vpc | security_group | terraform_workspace")
    resource_id: str = Field(..., description="Resource ID (e.g. i-..., vol-..., vpc-..., sg-..., mig-...)")
    cleanup_vpc: bool = True
    credentials: Optional[Dict[str, str]] = None
