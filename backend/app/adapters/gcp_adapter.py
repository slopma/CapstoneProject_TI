import os
import shutil
from typing import Dict, Any, List, Optional
from app.adapters.base import BaseProviderAdapter
from app.cmir.models import CMIR, CMIRNode
from app.generators.terraform import generate_gcp_terraform_files, generate_gcp_terraform


GCP_RESOURCE_MAP = {
    "datacenter": "google_compute_network",
    "physical_host": "google_compute_instance",
    "hypervisor": "google_compute_instance",
    "virtual_machine": "google_compute_instance",
    "vm": "google_compute_instance",
    "host": "google_compute_instance",
    "compute": "google_compute_instance",
    "workload": "google_compute_instance",
    "service": "google_compute_instance",
    "system_service": "in_guest_service",
    "process": "in_guest_process",
    "application": "google_compute_instance",
    "application_component": "google_cloud_run_v2_service",
    "machine_image": "google_compute_image",
    "disk_image": "google_compute_image",
    "operating_system": "google_compute_image",
    "os": "google_compute_image",
    "container": "google_cloud_run_v2_service",
    "database": "google_sql_database_instance",
    "database_instance": "google_sql_database_instance",
    "database_schema": "google_sql_database_instance",
    "cache": "google_redis_instance",
    "storage": "google_storage_bucket",
    "file_share": "google_storage_bucket",
    "shared_file": "google_storage_bucket",
    "san_storage": "google_compute_disk",
    "volume": "google_compute_disk",
    "disk": "google_compute_disk",
    "block_device": "google_compute_disk",
    "partition": "google_compute_disk",
    "filesystem": "google_compute_disk",
    "bucket": "google_storage_bucket",
    "network": "google_compute_network",
    "vpc": "google_compute_network",
    "subnet": "google_compute_subnetwork",
    "vlan": "google_compute_subnetwork",
    "network_interface": "google_compute_subnetwork",
    "security_boundary": "google_compute_firewall",
    "security_group": "google_compute_firewall",
    "firewall": "google_compute_firewall",
    "connectivity_rule": "google_compute_firewall",
    "listening_port": "google_compute_firewall",
    "port": "google_compute_firewall",
    "network_connection": "google_compute_firewall",
    "cluster": "google_container_cluster",
    "kubernetes_cluster": "google_container_cluster",
    "kubernetes_namespace": "google_container_node_pool",
    "namespace": "google_container_node_pool",
    "load_balancer": "google_compute_forwarding_rule",
    "ingress": "google_compute_forwarding_rule",
    "queue": "google_pubsub_topic",
    "topic": "google_pubsub_topic",
    "identity": "google_service_account",
    "role": "google_service_account",
    "permission": "google_project_iam_member",
    "secret": "google_secret_manager_secret",
}

VALID_GCP_REGIONS = {
    "us-central1", "us-east1", "us-east4", "us-west1", "us-west2",
    "southamerica-east1", "europe-west1", "europe-west3", "asia-east1",
}


class GCPAdapter(BaseProviderAdapter):
    @property
    def provider_name(self) -> str:
        return "gcp"

    def translate_node(self, node: CMIRNode) -> Dict[str, Any]:
        node_type_lower = node.type.lower()
        target_type = GCP_RESOURCE_MAP.get(node_type_lower, "google_compute_instance")

        safe_name = node.name.lower().replace(" ", "-").replace("_", "-").replace("/", "-").replace(".", "-")
        safe_id = node.id.lower().replace("-", "_").replace(".", "_").replace(":", "_").replace("/", "_")

        location = node.location if node.location in VALID_GCP_REGIONS else "us-central1"

        return {
            "id": node.id,
            "canonical_id": node.canonical_id or node.id,
            "safe_id": safe_id,
            "name": node.name,
            "safe_name": safe_name,
            "cmir_type": node.type,
            "type": target_type,
            "engine": node.engine,
            "platform": node.platform,
            "location": location,
            "environment": node.environment or "production",
            "epistemic_state": node.epistemic_state,
            "confidence": node.confidence,
            "security": node.security or {},
            "network": node.network or {},
            "metadata": node.metadata or {},
        }

    def translate_cmir(self, cmir: CMIR) -> List[Dict[str, Any]]:
        return [self.translate_node(node) for node in cmir.resources]

    def validate_target_config(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        cfg = dict(config or {})
        errors: List[str] = []
        warnings: List[str] = []
        project_id = cfg.get("project_id") or cfg.get("gcp_project_id") or "cloudmove-target-project"
        region = cfg.get("region") or cfg.get("gcp_region") or "us-central1"
        zone = cfg.get("zone") or cfg.get("gcp_zone") or f"{region}-a"
        cfg["project_id"] = project_id
        cfg["region"] = region
        cfg["zone"] = zone
        if region not in VALID_GCP_REGIONS:
            warnings.append(f"La región GCP '{region}' no está en el catálogo estándar; verifique disponibilidad.")
        return {
            "provider": "gcp",
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "normalized_config": cfg,
            "capabilities": {
                "compute": ["Compute Engine (google_compute_instance)", "Cloud Run v2", "Google Kubernetes Engine (GKE)"],
                "vm_image_import": [
                    "Compute Engine Image Import (gcloud compute images import)",
                    "Google Cloud Migrate to Virtual Machines",
                ],
                "storage": ["Persistent Disk (pd-balanced / pd-ssd)", "Cloud Storage (GCS)", "Filestore"],
                "database": ["Cloud SQL (PostgreSQL / MySQL)", "Memorystore for Redis", "Cloud Pub/Sub"],
                "SupportedImageFormats": ["VMDK", "VHD", "VHDX", "QCOW2", "RAW", "OVA", "OVF"],
                "GuestOSFeatures": ["VIRTIO_SCSI_MULTIQUEUE", "UEFI_COMPATIBLE", "GVNIC"],
            },
        }

    def check_permissions_and_prerequisites(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        cfg = config or {}
        has_gcp_creds = bool(
            os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            or os.getenv("CLOUDSDK_CONFIG")
            or cfg.get("google_application_credentials")
            or cfg.get("gcp_service_account_key")
        )
        gcloud_cli = shutil.which("gcloud") is not None
        terraform_cli = shutil.which("terraform") is not None
        live_verified = (bool(cfg.get("live_credentials_verified")) or has_gcp_creds) and not cfg.get("dry_run", False)
        return {
            "provider": "gcp",
            "live_credentials_verified": live_verified,
            "gcp_credentials_detected": has_gcp_creds,
            "gcloud_cli_installed": gcloud_cli,
            "terraform_cli_installed": terraform_cli,
            "execution_mode": "live_cloud" if live_verified else "simulated_dry_run",
            "required_permissions": [
                "compute.images.create",
                "compute.instances.create",
                "compute.disks.create",
                "compute.networks.create",
                "compute.subnetworks.create",
                "compute.firewalls.create",
                "storage.buckets.create",
                "storage.objects.create",
                "cloudsql.instances.create",
                "iam.serviceAccounts.create",
            ],
            "required_apis": [
                "compute.googleapis.com",
                "sqladmin.googleapis.com",
                "redis.googleapis.com",
                "run.googleapis.com",
                "vmmigration.googleapis.com",
            ],
            "prerequisites_met": True,
            "notes": [
                "Para importar imágenes de VM reales en GCP se requiere un bucket de Cloud Storage (GCS) de staging y habilitar compute.googleapis.com / vmmigration.googleapis.com.",
                "Terraform aprovisiona redes VPC, instancias Compute Engine, discos persistentes y Cloud SQL; la transferencia de bloques de disco se realiza vía 'gcloud compute images import' o Migrate to Virtual Machines.",
            ],
        }

    def generate_iac(self, cmir: CMIR, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        translated = self.translate_cmir(cmir)
        files = generate_gcp_terraform_files(translated)
        code = generate_gcp_terraform(translated)
        validation = self.validate_artifacts(files)
        return {
            "provider": "gcp",
            "translated_resources": translated,
            "files": files,
            "iac_code": code,
            "validation": validation,
        }
