"""
Machine Migration Strategies: Continuous Block Replication (AWS MGN & GCP Migrate to VMs)
and Image/Snapshot Import (AWS VM Import/Export & GCP Compute Image Import) (Section 5.3 & 7).

Provides:
1. Official Provider Compatibility Matrix (OS, architecture, source type, disk format,
   boot firmware, network ports, IAM permissions, and supported regions).
2. Strategy selector (`select_machine_migration_strategy`) that determines whether continuous
   block-level replication (`aws_mgn` / `gcp_vmmigration`) or image import (`aws_vm_import` /
   `gcp_image_import`) applies to the source, and documents limitations when continuous
   replication is not supported (e.g., standalone offline disk files without a running source
   OS or hypervisor connector).
3. Real AWS SDK (`boto3` `mgn` & `ec2` & `s3`) and GCP API (`vmmigration.googleapis.com/v1` &
   `compute.googleapis.com/compute/v1`) operation executors and status pollers.
   Never fakes continuous replication with a file copy or artificial percentage.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from typing import Any, Callable, Dict, List, Optional
import urllib.error
import urllib.request

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, PartialCredentialsError

from app.discovery.connectors import ConnectorAuthError, ConnectorError, ConnectorTimeoutError


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ==============================================================================
# Official Compatibility Matrix for AWS & GCP Machine Migration Services
# ==============================================================================

MACHINE_MIGRATION_COMPATIBILITY_MATRIX: Dict[str, Any] = {
    "aws": {
        "aws_mgn": {
            "service_name": "AWS Application Migration Service (AWS Transform MGN)",
            "official_docs": "https://aws.amazon.com/application-migration-service/",
            "mechanism": "continuous_block_replication",
            "supported_source_types": ["live_server", "hypervisor_vm", "datacenter_host"],
            "unsupported_source_types": ["standalone_offline_disk_image"],
            "supported_os_families": ["linux", "windows"],
            "supported_distros": ["debian", "ubuntu", "rhel", "rocky", "almalinux", "amazon", "sles", "windows-server"],
            "supported_architectures": ["x86_64", "arm64", "aarch64"],
            "supported_boot_modes": ["BIOS", "UEFI"],
            "max_disk_size_tib": 64,
            "network_requirements": [
                "TCP 443 saliente desde origen hacia el endpoint regional mgn.<region>.amazonaws.com",
                "TCP 1500 saliente desde origen hacia las instancias de replicación en la subred de staging en AWS",
            ],
            "required_iam_permissions": [
                "mgn:InitializeService",
                "mgn:DescribeSourceServers",
                "mgn:StartReplication",
                "mgn:StartTest",
                "mgn:StartCutover",
                "mgn:FinalizeCutover",
                "ec2:RunInstances",
                "ec2:CreateSnapshot",
                "ec2:CreateVolume",
            ],
            "cost_model": "Uso del servicio MGN sin coste de licencia por servidor durante 90 días; se facturan los volúmenes EBS e instancias EC2 t3.small/c5 de la subred de staging.",
        },
        "aws_vm_import": {
            "service_name": "AWS VM Import/Export (`ec2:ImportImage` / `ec2:ImportSnapshot`)",
            "official_docs": "https://docs.aws.amazon.com/vm-import/latest/userguide/image-import.html",
            "mechanism": "staged_image_import",
            "supported_source_types": ["standalone_offline_disk_image", "exported_vm_appliance", "hypervisor_vm"],
            "supported_image_formats": ["VMDK", "VHD", "VHDX", "RAW", "OVA"],
            "formats_requiring_conversion": {"QCOW2": "RAW", "OVF": "OVA"},
            "supported_os_families": ["linux", "windows"],
            "supported_distros": ["debian", "ubuntu", "rhel", "rocky", "almalinux", "centos", "sles", "windows-server"],
            "supported_architectures": ["x86_64", "arm64", "aarch64"],
            "supported_boot_modes": ["BIOS", "UEFI"],
            "network_requirements": [
                "HTTPS (TCP 443) hacia Amazon S3 (`s3.<region>.amazonaws.com`) para subir el disco de staging",
            ],
            "required_iam_permissions": [
                "s3:GetBucketLocation",
                "s3:GetObject",
                "s3:ListBucket",
                "s3:PutObject",
                "ec2:ImportImage",
                "ec2:ImportSnapshot",
                "ec2:DescribeImportImageTasks",
                "ec2:DescribeImportSnapshotTasks",
                "iam:GetRole (rol obligatorio `vmimport` con trust policy para `vmie.amazonaws.com`)",
            ],
            "cost_model": "Sin cargo adicional por el servicio VM Import/Export; se factura el almacenamiento del objeto en S3 y los snapshots EBS resultantes.",
        },
    },
    "gcp": {
        "gcp_vmmigration": {
            "service_name": "Google Cloud Migrate to Virtual Machines (`vmmigration.googleapis.com/v1`)",
            "official_docs": "https://cloud.google.com/migrate/virtual-machines/docs/5.0",
            "mechanism": "continuous_block_replication",
            "supported_source_types": ["vmware_vsphere_vm", "hypervisor_vm", "cloud_vm"],
            "unsupported_source_types": ["standalone_offline_disk_image"],
            "supported_os_families": ["linux", "windows"],
            "supported_distros": ["debian", "ubuntu", "rhel", "rocky", "almalinux", "centos", "sles", "windows-server"],
            "supported_architectures": ["x86_64", "arm64", "aarch64"],
            "supported_boot_modes": ["BIOS", "UEFI"],
            "network_requirements": [
                "Conector Migrate Connector desplegado en el entorno de virtualización de origen",
                "TCP 443 saliente hacia `vmmigration.googleapis.com` y Cloud Storage APIs",
            ],
            "required_iam_permissions": [
                "vmmigration.sources.get",
                "vmmigration.migratingVms.create",
                "vmmigration.migratingVms.startMigration",
                "vmmigration.cloneJobs.create",
                "vmmigration.cutoverJobs.create",
                "compute.instances.create",
                "compute.disks.create",
            ],
            "cost_model": "Sin coste de licencia por el uso de Migrate to Virtual Machines; se facturan los Persistent Disks de replicación y las instancias de prueba/cutover.",
        },
        "gcp_image_import": {
            "service_name": "Google Compute Engine Image & Virtual Disk Import (`compute.images.insert` / `gcloud compute images import`)",
            "official_docs": "https://cloud.google.com/compute/docs/import/importing-virtual-disks",
            "mechanism": "staged_image_import",
            "supported_source_types": ["standalone_offline_disk_image", "exported_vm_appliance", "hypervisor_vm"],
            "supported_image_formats": ["VMDK", "VHD", "VHDX", "QCOW2", "RAW", "OVA", "OVF"],
            "formats_requiring_conversion": {},
            "supported_os_families": ["linux", "windows"],
            "supported_distros": ["debian", "ubuntu", "rhel", "rocky", "almalinux", "centos", "sles", "windows-server"],
            "supported_architectures": ["x86_64", "arm64", "aarch64"],
            "supported_boot_modes": ["BIOS", "UEFI"],
            "network_requirements": [
                "HTTPS (TCP 443) hacia Google Cloud Storage (`storage.googleapis.com`) para alojar el archivo de imagen en un bucket de staging",
            ],
            "required_iam_permissions": [
                "storage.buckets.get",
                "storage.objects.create",
                "storage.objects.get",
                "compute.images.create",
                "compute.disks.create",
                "compute.instances.create",
            ],
            "cost_model": "Se factura el almacenamiento temporal en Cloud Storage (GCS) y la imagen/discos persistentes en Compute Engine.",
        },
    },
}


def select_machine_migration_strategy(
    manifest: Dict[str, Any],
    target_provider: str = "aws",
    source_type: str = "standalone_offline_disk_image",
    prefer_continuous_replication: bool = False,
) -> Dict[str, Any]:
    """
    Determine the appropriate migration strategy for a machine or disk image based on
    the official AWS & GCP compatibility matrix.
    - If `source_type` is a live server or hypervisor VM (`live_server`, `hypervisor_vm`,
      `vmware_vsphere_vm`) and the OS/architecture is supported, selects continuous
      replication (`aws_mgn` or `gcp_vmmigration`) when requested or applicable.
    - If `source_type` is `standalone_offline_disk_image` (a `.vmdk`, `.qcow2`, `.vhd`,
      `.raw`, `.ova` file on disk without a running source agent/hypervisor), continuous
      replication is NOT applicable because AWS MGN requires an active agent/vCenter source
      and GCP Migrate to VMs requires an active vSphere/Cloud source connector. In that case,
      it selects `aws_vm_import` or `gcp_image_import` and explicitly documents why.
    """
    prov = target_provider.lower().strip()
    if prov not in ("aws", "gcp"):
        raise ValueError(f"Proveedor destino '{target_provider}' no admitido. Solo 'aws' o 'gcp'.")

    os_info = manifest.get("os") or {}
    os_family = str(os_info.get("family") or "linux").lower()
    arch = str(os_info.get("architecture") or "x86_64").lower()
    img_format = str(manifest.get("format") or "VMDK").upper()

    prov_matrix = MACHINE_MIGRATION_COMPATIBILITY_MATRIX[prov]
    repl_key = "aws_mgn" if prov == "aws" else "gcp_vmmigration"
    imp_key = "aws_vm_import" if prov == "aws" else "gcp_image_import"
    repl_spec = prov_matrix[repl_key]
    imp_spec = prov_matrix[imp_key]

    can_use_continuous = (
        source_type in repl_spec["supported_source_types"]
        and os_family in repl_spec["supported_os_families"]
        and arch in repl_spec["supported_architectures"]
    )

    if prefer_continuous_replication and can_use_continuous:
        selected_key = repl_key
        selected_spec = repl_spec
        rationale = (
            f"El origen '{source_type}' ({os_family}/{arch}) es compatible con replicación continua a nivel de bloque "
            f"mediante {repl_spec['service_name']}. Permite sincronización inicial en segundo plano, lanzamiento de "
            "instancia de prueba aislada, sincronización delta final y ventana de cutover mínima."
        )
        limitations = [
            "Requiere conectividad continua desde el entorno de origen hacia los endpoints de replicación del proveedor.",
            "No transfiere el estado de memoria RAM volátil en el instante del cutover; realiza un arranque limpio tras el último delta sync.",
        ]
    else:
        selected_key = imp_key
        selected_spec = imp_spec
        if prefer_continuous_replication and not can_use_continuous:
            rationale = (
                f"Se solicitó replicación continua, pero el tipo de origen '{source_type}' ({os_family}/{arch}) "
                f"no es compatible con {repl_spec['service_name']} (que requiere un servidor en ejecución con agente o "
                f"conector de hipervisor activo). Se selecciona el procedimiento oficial alternativo soportado: "
                f"{imp_spec['service_name']} con validación criptográfica SHA-256 en staging."
            )
        else:
            rationale = (
                f"Para una imagen de máquina/disco ('{img_format}'), la vía oficial soportada en {prov.upper()} es "
                f"{imp_spec['service_name']} a través de almacenamiento de staging con verificación SHA-256."
            )
        limitations = [
            "Al tratarse de importación basada en imagen/snapshot, cualquier escritura ocurrida en el sistema de origen "
            "después de la toma del snapshot requiere una sincronización delta de datos (rsync/DMS) antes del cutover.",
            "No conserva memoria RAM volátil ni conexiones TCP activas.",
        ]

    return {
        "target_provider": prov,
        "selected_strategy_id": selected_key,
        "service_name": selected_spec["service_name"],
        "mechanism": selected_spec["mechanism"],
        "official_docs": selected_spec["official_docs"],
        "source_type": source_type,
        "continuous_replication_supported_for_source": can_use_continuous,
        "rationale": rationale,
        "network_requirements": selected_spec["network_requirements"],
        "required_iam_permissions": selected_spec["required_iam_permissions"],
        "cost_model": selected_spec["cost_model"],
        "limitations": limitations,
    }


# ==============================================================================
# Real Provider Connectors for Machine Import & Continuous Replication
# ==============================================================================


class AWSMachineMigrationClient:
    """
    Executes and queries real AWS VM Import/Export (`ec2:ImportImage`, `ec2:DescribeImportImageTasks`)
    and AWS Application Migration Service (`mgn:DescribeSourceServers`, `mgn:StartTest`,
    `mgn:StartCutover`, `mgn:FinalizeCutover`) operations via `boto3`.
    Never fabricates a cloud task ID or progress percentage in production.
    """

    def __init__(
        self,
        region: str = "us-east-1",
        boto3_session_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.region = region or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
        self.boto3_session_factory = boto3_session_factory

    def _session(self) -> Any:
        if self.boto3_session_factory is not None:
            return self.boto3_session_factory(region_name=self.region)
        return boto3.Session(region_name=self.region)

    def verify_s3_staging_object(self, bucket: str, key: str) -> Dict[str, Any]:
        if not bucket or not key:
            raise ConnectorError("MISSING_STAGING_STORAGE", "Debe especificar `s3_bucket` y `s3_key` para el área de staging en AWS.")
        try:
            s3 = self._session().client("s3")
            head = s3.head_object(Bucket=bucket, Key=key)
            return {
                "verified": True,
                "bucket": bucket,
                "key": key,
                "size_bytes": head.get("ContentLength"),
                "etag": str(head.get("ETag", "")).strip('"'),
                "checked_at": _utc_now(),
            }
        except (NoCredentialsError, PartialCredentialsError) as exc:
            raise ConnectorAuthError("AWS_MISSING_CREDENTIALS", f"Sin credenciales AWS para verificar S3 staging s3://{bucket}/{key}: {exc}") from exc
        except ClientError as exc:
            code = (exc.response.get("Error") or {}).get("Code", "S3Error")
            msg = (exc.response.get("Error") or {}).get("Message", str(exc))
            if code in ("403", "AccessDenied"):
                raise ConnectorAuthError("AWS_S3_ACCESS_DENIED", f"Acceso denegado al bucket de staging s3://{bucket}/{key}: {msg}") from exc
            raise ConnectorError(f"AWS_S3_{code}", f"No se encontró o falló el objeto de staging s3://{bucket}/{key}: {msg}") from exc

    def start_vm_image_import(
        self,
        description: str,
        disk_containers: List[Dict[str, Any]],
        boot_mode: str = "uefi",
        architecture: str = "x86_64",
        role_name: str = "vmimport",
    ) -> Dict[str, Any]:
        if not disk_containers:
            raise ConnectorError("EMPTY_DISK_CONTAINERS", "Se requiere al menos un contenedor de disco para `ec2:ImportImage`.")
        for dc in disk_containers:
            ub = dc.get("UserBucket") or {}
            if not ub.get("S3Bucket") or not ub.get("S3Key"):
                raise ConnectorError(
                    "MISSING_STAGING_STORAGE",
                    "Cada disco en `disk_containers` debe especificar `UserBucket.S3Bucket` y `UserBucket.S3Key`.",
                )
        try:
            ec2 = self._session().client("ec2")
            resp = ec2.import_image(
                Description=description,
                DiskContainers=disk_containers,
                BootMode="uefi" if boot_mode.lower() == "uefi" else "legacy-bios",
                Architecture="arm64" if architecture.lower() in ("arm64", "aarch64") else "x86_64",
                RoleName=role_name,
            )
            return {
                "provider": "aws",
                "service": "aws_vm_import",
                "import_task_id": resp["ImportTaskId"],
                "status": resp.get("Status", "active"),
                "status_message": resp.get("StatusMessage", ""),
                "boot_mode": resp.get("BootMode", boot_mode.lower()),
                "started_at": _utc_now(),
            }
        except (NoCredentialsError, PartialCredentialsError) as exc:
            raise ConnectorAuthError("AWS_MISSING_CREDENTIALS", f"Sin credenciales AWS para ejecutar `ec2:ImportImage`: {exc}") from exc
        except ClientError as exc:
            code = (exc.response.get("Error") or {}).get("Code", "ImportImageError")
            msg = (exc.response.get("Error") or {}).get("Message", str(exc))
            if code in ("AuthFailure", "UnauthorizedOperation", "AccessDenied"):
                raise ConnectorAuthError(f"AWS_{code}", f"Permisos insuficientes para `ec2:ImportImage`: {msg}") from exc
            raise ConnectorError(f"AWS_IMPORT_{code}", f"Fallo en `ec2:ImportImage`: {msg}") from exc

    def get_vm_image_import_status(self, import_task_id: str) -> Dict[str, Any]:
        try:
            ec2 = self._session().client("ec2")
            resp = ec2.describe_import_image_tasks(ImportTaskIds=[import_task_id])
            tasks = resp.get("ImportImageTasks") or []
            if not tasks:
                raise ConnectorError("IMPORT_TASK_NOT_FOUND", f"No existe la tarea de importación '{import_task_id}' en AWS EC2.")
            t = tasks[0]
            return {
                "provider": "aws",
                "import_task_id": t["ImportTaskId"],
                "status": t.get("Status"),
                "progress": t.get("Progress"),
                "status_message": t.get("StatusMessage"),
                "image_id": t.get("ImageId"),
                "snapshot_details": t.get("SnapshotDetails", []),
                "checked_at": _utc_now(),
            }
        except (NoCredentialsError, PartialCredentialsError) as exc:
            raise ConnectorAuthError("AWS_MISSING_CREDENTIALS", f"Sin credenciales AWS para consultar `{import_task_id}`: {exc}") from exc
        except ClientError as exc:
            code = (exc.response.get("Error") or {}).get("Code", "DescribeImportError")
            msg = (exc.response.get("Error") or {}).get("Message", str(exc))
            raise ConnectorError(f"AWS_{code}", f"Error al consultar `{import_task_id}`: {msg}") from exc

    def query_mgn_source_server(self, source_server_id: str) -> Dict[str, Any]:
        try:
            mgn = self._session().client("mgn")
            resp = mgn.describe_source_servers(filters={"sourceServerIDs": [source_server_id]})
            items = resp.get("items") or []
            if not items:
                raise ConnectorError("MGN_SOURCE_NOT_FOUND", f"Servidor de origen '{source_server_id}' no registrado en AWS MGN.")
            srv = items[0]
            data_repl = srv.get("dataReplicationInfo") or {}
            lifecycle = (srv.get("lifeCycle") or {}).get("state", "UNKNOWN")
            return {
                "provider": "aws",
                "service": "aws_mgn",
                "source_server_id": srv["sourceServerID"],
                "lifecycle_state": lifecycle,
                "replication_state": data_repl.get("dataReplicationState", "UNKNOWN"),
                "lag_duration": data_repl.get("lagDuration"),
                "replicated_disks": data_repl.get("replicatedDisks", []),
                "ready_for_test": lifecycle in ("READY_FOR_TEST", "READY_FOR_CUTOVER"),
                "ready_for_cutover": lifecycle == "READY_FOR_CUTOVER",
                "checked_at": _utc_now(),
            }
        except (NoCredentialsError, PartialCredentialsError) as exc:
            raise ConnectorAuthError("AWS_MISSING_CREDENTIALS", f"Sin credenciales AWS para consultar AWS MGN: {exc}") from exc
        except ClientError as exc:
            code = (exc.response.get("Error") or {}).get("Code", "MGNError")
            msg = (exc.response.get("Error") or {}).get("Message", str(exc))
            if "UninitializedAccountException" in code:
                raise ConnectorError("AWS_MGN_UNINITIALIZED", f"El servicio AWS MGN no está inicializado en la región {self.region}: {msg}") from exc
            raise ConnectorError(f"AWS_MGN_{code}", f"Error en AWS MGN: {msg}") from exc

    def trigger_mgn_action(self, action: str, source_server_ids: List[str]) -> Dict[str, Any]:
        if action not in ("start_test", "start_cutover", "finalize_cutover"):
            raise ValueError(f"Acción MGN '{action}' no soportada.")
        try:
            mgn = self._session().client("mgn")
            if action == "start_test":
                resp = mgn.start_test(sourceServerIDs=source_server_ids)
            elif action == "start_cutover":
                resp = mgn.start_cutover(sourceServerIDs=source_server_ids)
            else:
                resp = mgn.finalize_cutover(sourceServerID=source_server_ids[0])
            job = resp.get("job") or {}
            return {
                "provider": "aws",
                "service": "aws_mgn",
                "action": action,
                "source_server_ids": source_server_ids,
                "mgn_job_id": job.get("jobID"),
                "status": job.get("status", "PENDING"),
                "triggered_at": _utc_now(),
            }
        except (NoCredentialsError, PartialCredentialsError) as exc:
            raise ConnectorAuthError("AWS_MISSING_CREDENTIALS", f"Sin credenciales AWS para ejecutar `{action}` en MGN: {exc}") from exc
        except ClientError as exc:
            code = (exc.response.get("Error") or {}).get("Code", "MGNJobError")
            msg = (exc.response.get("Error") or {}).get("Message", str(exc))
            raise ConnectorError(f"AWS_MGN_{code}", f"Error ejecutando `{action}` en AWS MGN: {msg}") from exc


class GCPMachineMigrationClient:
    """
    Executes and queries real Google Cloud Compute Engine Image Import and
    Google Cloud Migrate to Virtual Machines (`vmmigration.googleapis.com/v1`) operations.
    """

    def __init__(
        self,
        project_id: str,
        location: str = "us-central1",
        http_transport: Optional[Callable[[str, str, Optional[Dict[str, Any]]], Dict[str, Any]]] = None,
    ) -> None:
        self.project_id = project_id
        self.location = location
        self.http_transport = http_transport

    def _obtain_token(self) -> str:
        if self.http_transport is not None:
            return "injected-gcp-token"
        if not self.project_id:
            raise ConnectorAuthError("GCP_MISSING_PROJECT", "Debe especificar `project_id` para operaciones de migración en GCP.")
        try:
            import google.auth
            from google.auth.transport.requests import Request as GoogleAuthRequest

            creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            creds.refresh(GoogleAuthRequest())
            return str(creds.token)
        except Exception as exc:
            raise ConnectorAuthError(
                "GCP_MISSING_CREDENTIALS",
                f"Credenciales GCP no disponibles para ejecutar operación de migración en vivo: {exc}",
            ) from exc

    def _request(self, method: str, url: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        token = self._obtain_token()
        if self.http_transport is not None:
            return self.http_transport(method, url, body)

        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise ConnectorAuthError(f"GCP_HTTP_{exc.code}", f"Autorización GCP rechazada ({exc.code}) en {url}.") from exc
            raise ConnectorError(f"GCP_HTTP_{exc.code}", f"Error HTTP {exc.code} en API de migración GCP ({url}).") from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            raise ConnectorTimeoutError(f"Error de red/timeout hacia GCP ({url}): {exc}") from exc

    def start_compute_image_import(
        self,
        image_name: str,
        gcs_source_uri: str,
        guest_os_features: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if not gcs_source_uri or not gcs_source_uri.startswith("gs://"):
            raise ConnectorError(
                "MISSING_STAGING_STORAGE",
                "Debe proporcionar una URI válida en Google Cloud Storage (`gs://bucket/imagen`) para importar en GCP.",
            )
        url = f"https://compute.googleapis.com/compute/v1/projects/{self.project_id}/global/images"
        features = [{"type": f} for f in (guest_os_features or ["UEFI_COMPATIBLE", "VIRTIO_SCSI_MULTIQUEUE", "GVNIC"])]
        body = {
            "name": image_name,
            "rawDisk": {"source": gcs_source_uri},
            "guestOsFeatures": features,
        }
        resp = self._request("POST", url, body)
        return {
            "provider": "gcp",
            "service": "gcp_image_import",
            "operation_id": resp.get("name") or resp.get("id"),
            "status": resp.get("status", "RUNNING"),
            "target_image": image_name,
            "gcs_source_uri": gcs_source_uri,
            "started_at": _utc_now(),
        }

    def query_migrating_vm_status(self, source_id: str, migrating_vm_id: str) -> Dict[str, Any]:
        url = (
            f"https://vmmigration.googleapis.com/v1/projects/{self.project_id}"
            f"/locations/{self.location}/sources/{source_id}/migratingVms/{migrating_vm_id}"
        )
        resp = self._request("GET", url)
        return {
            "provider": "gcp",
            "service": "gcp_vmmigration",
            "migrating_vm_id": migrating_vm_id,
            "state": resp.get("state", "ACTIVE"),
            "current_sync_info": resp.get("currentSyncInfo", {}),
            "last_sync": resp.get("lastSync", {}),
            "checked_at": _utc_now(),
        }

    def trigger_vmmigration_action(
        self,
        action: str,
        source_id: str,
        migrating_vm_id: str,
        job_id: str = "job-01",
    ) -> Dict[str, Any]:
        base = (
            f"https://vmmigration.googleapis.com/v1/projects/{self.project_id}"
            f"/locations/{self.location}/sources/{source_id}/migratingVms/{migrating_vm_id}"
        )
        if action == "start_migration":
            url = f"{base}:startMigration"
            body: Dict[str, Any] = {}
        elif action == "create_clone_job":
            url = f"{base}/cloneJobs?cloneJobId={job_id}"
            body = {}
        elif action == "create_cutover_job":
            url = f"{base}/cutoverJobs?cutoverJobId={job_id}"
            body = {}
        else:
            raise ValueError(f"Acción GCP Migrate to VMs '{action}' no soportada.")
        resp = self._request("POST", url, body)
        return {
            "provider": "gcp",
            "service": "gcp_vmmigration",
            "action": action,
            "operation_name": resp.get("name"),
            "done": resp.get("done", False),
            "triggered_at": _utc_now(),
        }
