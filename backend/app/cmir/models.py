import hashlib
import re
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


def deterministic_node_id(prefix: str, *parts: Any) -> str:
    """Generate a deterministic, idempotent CMIR node ID from stable attributes."""
    clean_parts = [re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(p or "").strip().lower()).strip("-") for p in parts if p]
    raw_key = ":".join([prefix, *clean_parts])
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:10]
    slug = "-".join(clean_parts[:2])[:28] or "node"
    return f"{prefix}-{slug}-{digest}"


SUPPORTED_ENTITY_TYPES = {
    "cloud",
    "provider",
    "region",
    "datacenter",
    "physical_host",
    "host",
    "hypervisor",
    "virtual_machine",
    "vm",
    "machine_image",
    "disk_image",
    "operating_system",
    "os",
    "firmware",
    "hardware_component",
    "cpu",
    "memory",
    "application",
    "application_component",
    "process",
    "system_service",
    "systemd_service",
    "kernel_module",
    "package_group",
    "port",
    "listening_port",
    "network_connection",
    "remote_endpoint",
    "container",
    "workload",
    "service",
    "compute",
    "database",
    "database_instance",
    "database_schema",
    "cache",
    "storage",
    "volume",
    "disk",
    "block_device",
    "partition",
    "filesystem",
    "file_share",
    "shared_file",
    "network",
    "vpc",
    "subnet",
    "network_interface",
    "route",
    "gateway",
    "security_boundary",
    "security_group",
    "connectivity_rule",
    "firewall",
    "cluster",
    "kubernetes_cluster",
    "namespace",
    "kubernetes_namespace",
    "load_balancer",
    "ingress",
    "queue",
    "topic",
    "identity",
    "permission",
    "role",
    "secret",
    "discovery_group",
    "target_aws_resource",
    "target_gcp_resource",
}

SUPPORTED_RELATIONSHIP_TYPES = {
    "contains",
    "parent_of",
    "hosts",
    "runs_on",
    "depends_on",
    "optional_depends_on",
    "recommends",
    "communicates_with",
    "connects_to",
    "reads_from",
    "writes_to",
    "mounts",
    "exposes",
    "requires_identity",
    "migrates_to",
    "uses",
    "stores",
    "has_interface",
    "routes_to",
    "listens_on",
    "observed_connection",
    "inferred_relation",
}


class CMIREvidence(BaseModel):
    source: str = Field(..., description="Connector, tool or file that produced the observation")
    observed_at: Optional[str] = Field(None, description="ISO-8601 timestamp of observation")
    epistemic_state: str = Field(
        "observed",
        description="observed | derived | inferred | unknown | error",
    )
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="Confidence score [0.0, 1.0]")
    detail: Optional[str] = Field(None, description="Human-readable evidence explanation")
    raw_reference: Optional[str] = Field(None, description="Table, file path, line or query reference")


class CMIRTargetMapping(BaseModel):
    provider: str = Field(..., description="Target cloud provider: aws | gcp")
    target_resource_type: str = Field(..., description="Terraform resource type in AWS or GCP")
    strategy: str = Field("rehost", description="Migration 6R strategy: rehost | replatform | retain | retire")
    configuration: Dict[str, Any] = Field(default_factory=dict)
    notes: List[str] = Field(default_factory=list)


class CMIRNode(BaseModel):
    id: str
    name: str
    type: str
    category: Optional[str] = "resource"
    parent_id: Optional[str] = None
    children_ids: List[str] = Field(default_factory=list)
    level: int = 0
    provider: Optional[str] = "aws"
    platform: Optional[str] = None
    engine: Optional[str] = None
    location: Optional[str] = "us-east-1"
    environment: Optional[str] = "production"
    status: str = "DISCOVERED"
    is_shared: bool = False
    security: Dict[str, Any] = Field(default_factory=dict)
    network: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # CMIR v2.1 extended provenance, identity & target mapping fields
    canonical_id: Optional[str] = None
    epistemic_state: str = "observed"  # observed | derived | inferred | unknown
    confidence: float = 1.0
    source_connector: Optional[str] = None
    discovered_at: Optional[str] = None
    evidence: List[CMIREvidence] = Field(default_factory=list)
    target_mapping: Dict[str, Any] = Field(default_factory=dict)


# Backward compatibility alias
Resource = CMIRNode


class CMIRRelationship(BaseModel):
    id: Optional[str] = None
    source: str
    target: str
    type: str = "depends_on"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # CMIR v2.1 extended provenance & confidence fields
    epistemic_state: str = "observed"  # observed | derived | inferred | unknown
    confidence: float = 1.0
    source_connector: Optional[str] = None
    discovered_at: Optional[str] = None
    evidence: List[CMIREvidence] = Field(default_factory=list)


# Backward compatibility alias
Relationship = CMIRRelationship


class CMIR(BaseModel):
    name: str
    provider: str
    version: str = "2.1"
    resources: List[CMIRNode]
    relationships: List[CMIRRelationship]
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def get_node(self, node_id: str) -> Optional[CMIRNode]:
        for res in self.resources:
            if res.id == node_id or (res.canonical_id and res.canonical_id == node_id):
                return res
        return None
