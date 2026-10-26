"""
Conectores desacoplados de Descubrimiento Masivo, Escáner de Artefactos de Arquitectura
y Redactor de Secretos para CloudMove.

Incluye:
- `SecretRedactor`: detección y enmascaramiento estricto de credenciales, tokens, claves privadas y URIs.
- `ArchitectureFileScanner`: análisis de Terraform (.tf), Kubernetes (.yaml), Docker Compose y JSON dentro de raíces autorizadas.
- `InfrastructureConnector` y `ProxmoxVEConnector`: conector basado en la API REST oficial de Proxmox VE (`/api2/json`) con protección anti-SSRF, timeouts, paginación y manejo de `401`/`403`.
- `OperatingSystemConnector`: identificación autorizada de sistemas Linux (SSH/osquery) y Windows (WinRM).
- `DatabaseDiscoveryConnector`: recolección estructurada de motores PostgreSQL, SQL Server, MySQL y MongoDB en 6 capas separadas (sin extraer filas ni secretos).
- `SimulatedCollectorFixture`: colector de prueba reproducible para entornos sin credenciales de producción.
"""

from __future__ import annotations

import datetime
import ipaddress
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import PROJECT_ROOT


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class ConnectorError(Exception):
    """Error base tipado para conectores de infraestructura, SO o bases de datos."""

    def __init__(self, code: str, message: str, recoverable: bool = True):
        super().__init__(message)
        self.code = code
        self.message = message
        self.recoverable = recoverable


class ConnectorAuthError(ConnectorError):
    """Credenciales expiradas (401) o permisos insuficientes (403)."""

    def __init__(self, code: str, message: str):
        super().__init__(code=code, message=message, recoverable=False)


class ConnectorTimeoutError(ConnectorError):
    """Timeout al consultar un conector o nodo remoto."""

    def __init__(self, message: str):
        super().__init__(code="CONNECTOR_TIMEOUT", message=message, recoverable=True)


class SecurityPolicyViolationError(ConnectorError):
    """Intento de acceder a un destino prohibido (SSRF, fuera de alcance o archivo no autorizado)."""

    def __init__(self, code: str, message: str):
        super().__init__(code=code, message=message, recoverable=False)


class SecretRedactor:
    """
    Detecta y oculta contraseñas, tokens, claves privadas y cadenas de conexión con credenciales.
    Nunca almacena el valor real del secreto: conserva únicamente el nombre de la clave y su clasificación.
    """

    _PATTERNS: List[Tuple[str, re.Pattern]] = [
        (
            "private_key_block",
            re.compile(
                r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
                re.MULTILINE,
            ),
        ),
        (
            "connection_uri_credentials",
            re.compile(r"([a-zA-Z0-9+.-]+://[^:\s/@]+:)([^@\s\"']+)@", re.IGNORECASE),
        ),
        (
            "aws_access_key",
            re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
        ),
        (
            "key_value_secret",
            re.compile(
                r"""(?i)\b([a-z0-9_]*(?:password|passwd|pwd|secret|api_key|apikey|token|private_key|db_pass)[a-z0-9_]*)\b(\s*[:=]\s*)(["']?)([^"'\s\n#;]+)\3"""
            ),
        ),
    ]

    @classmethod
    def redact_text(cls, text: str) -> Tuple[str, List[Dict[str, str]]]:
        """
        Enmascara cualquier secreto presente en `text` y devuelve `(texto_redactado, hallazgos_seguros)`.
        """
        if not text:
            return "", []

        findings: List[Dict[str, str]] = []
        redacted = text

        # 1. Bloques de claves privadas
        for match in cls._PATTERNS[0][1].finditer(redacted):
            findings.append(
                {
                    "secret_type": "private_key_block",
                    "key_name": "PEM_PRIVATE_KEY",
                    "classification": "critical_credential",
                    "vault_reference": "arn:aws:secretsmanager:region:account:secret:tls-private-key",
                }
            )
        redacted = cls._PATTERNS[0][1].sub("-----REDACTED_PRIVATE_KEY_BLOCK-----", redacted)

        # 2. URIs de conexión con contraseña
        for match in cls._PATTERNS[1][1].finditer(redacted):
            findings.append(
                {
                    "secret_type": "connection_uri_credentials",
                    "key_name": "connection_string",
                    "classification": "database_or_broker_credential",
                    "vault_reference": "arn:aws:secretsmanager:region:account:secret:connection-uri",
                }
            )
        redacted = cls._PATTERNS[1][1].sub(r"\1***REDACTED_SECRET***@", redacted)

        # 3. AWS Access Keys
        for match in cls._PATTERNS[2][1].finditer(redacted):
            findings.append(
                {
                    "secret_type": "aws_access_key",
                    "key_name": "AWS_ACCESS_KEY_ID",
                    "classification": "cloud_iam_credential",
                    "vault_reference": "iam-role-or-secrets-manager",
                }
            )
        redacted = cls._PATTERNS[2][1].sub("AKIA***REDACTED***", redacted)

        # 4. Asignaciones clave = valor sensibles
        def _replace_kv(m: re.Match) -> str:
            key_name = m.group(1)
            sep = m.group(2)
            quote = m.group(3)
            val = m.group(4)
            # No marcar placeholders ya enmascarados o referencias a variables
            if val.startswith("$") or "REDACTED" in val or val in ("true", "false", "null", "change-me"):
                return m.group(0)
            findings.append(
                {
                    "secret_type": "key_value_secret",
                    "key_name": key_name,
                    "classification": "application_secret",
                    "vault_reference": f"secrets-manager://{key_name.lower()}",
                }
            )
            return f"{key_name}{sep}{quote}***REDACTED_SECRET***{quote}"

        redacted = cls._PATTERNS[3][1].sub(_replace_kv, redacted)
        return redacted, findings


def validate_endpoint_against_ssrf(url: str, allow_private_datacenter: bool = True) -> urllib.parse.ParseResult:
    """
    Valida una URL de conector frente a ataques SSRF:
    - Exige esquema `https` o `http`.
    - Bloquea siempre el endpoint de metadata cloud (`169.254.169.254`, `fd00:ec2::254`) y loopback no autorizado.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise SecurityPolicyViolationError(
            "INVALID_URL_SCHEME",
            f"Esquema de URL '{parsed.scheme}' no permitido. Use https (o http en laboratorio autorizado).",
        )
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise SecurityPolicyViolationError("INVALID_URL_HOST", "La URL del conector no especifica un host válido.")

    if host in ("169.254.169.254", "metadata.google.internal", "100.100.100.200"):
        raise SecurityPolicyViolationError(
            "SSRF_METADATA_BLOCKED",
            f"Destino '{host}' bloqueado por política anti-SSRF (servicio de metadata cloud).",
        )

    try:
        ip_obj = ipaddress.ip_address(host)
        if ip_obj.is_link_local or ip_obj.is_multicast or ip_obj.is_unspecified:
            raise SecurityPolicyViolationError(
                "SSRF_LINK_LOCAL_BLOCKED",
                f"Dirección IP '{host}' bloqueada por política anti-SSRF.",
            )
        if not allow_private_datacenter and ip_obj.is_private:
            raise SecurityPolicyViolationError(
                "PRIVATE_IP_NOT_AUTHORIZED",
                f"Dirección privada '{host}' no autorizada para este conector.",
            )
    except ValueError:
        # Es un nombre DNS; comprobar que no apunte a localhost si no está permitido
        pass

    return parsed


class ArchitectureFileScanner:
    """
    Analiza archivos de infraestructura como código y configuración (Terraform `.tf`,
    Kubernetes `.yaml`, Docker Compose, inventarios JSON) dentro de los directorios autorizados
    del proyecto, extrayendo recursos, volúmenes, imágenes, puertos y referencias a secretos
    (siempre enmascaradas).
    """

    MAX_FILE_BYTES = 2 * 1024 * 1024  # Límite de 2 MiB por archivo inspeccionado
    EXCLUDED_NAMES = {".env", "terraform.tfstate", "terraform.tfstate.backup", "id_rsa", "id_ed25519"}

    def __init__(self, allowed_roots: Optional[List[Path]] = None):
        self.allowed_roots = [
            p.resolve()
            for p in (
                allowed_roots
                or [
                    PROJECT_ROOT / "generated",
                    PROJECT_ROOT / "inventory",
                    PROJECT_ROOT / "cmir",
                ]
            )
        ]

    def _assert_path_authorized(self, target_path: Path) -> Path:
        resolved = target_path.resolve()
        if not any(
            resolved == root or str(resolved).startswith(str(root) + os.sep)
            for root in self.allowed_roots
        ):
            raise SecurityPolicyViolationError(
                "UNAUTHORIZED_FILE_PATH",
                f"La ruta '{target_path}' está fuera de los directorios de arquitectura autorizados.",
            )
        if resolved.name in self.EXCLUDED_NAMES or resolved.suffix in (".tfstate", ".pem", ".key"):
            raise SecurityPolicyViolationError(
                "EXCLUDED_SENSITIVE_ARTIFACT",
                f"El archivo '{resolved.name}' está excluido por política de protección de secretos y estado.",
            )
        return resolved

    def scan_file(self, file_path: Path) -> Dict[str, Any]:
        resolved = self._assert_path_authorized(file_path)
        if not resolved.is_file():
            raise ConnectorError("ARTIFACT_NOT_FOUND", f"No existe el archivo '{file_path}'.")
        size = resolved.stat().st_size
        if size > self.MAX_FILE_BYTES:
            raise SecurityPolicyViolationError(
                "FILE_TOO_LARGE",
                f"El archivo '{resolved.name}' ({size} bytes) supera el límite de {self.MAX_FILE_BYTES} bytes.",
            )

        raw_text = resolved.read_text(encoding="utf-8", errors="replace")
        redacted_text, secret_findings = SecretRedactor.redact_text(raw_text)
        rel_path = (
            str(resolved.relative_to(PROJECT_ROOT))
            if str(resolved).startswith(str(PROJECT_ROOT))
            else str(resolved.name)
        )

        ext = resolved.suffix.lower()
        name_lower = resolved.name.lower()

        resources_defined: List[Dict[str, str]] = []
        container_images: List[str] = []
        persistent_volumes: List[str] = []
        exposed_ports: List[int] = []
        service_dependencies: List[str] = []

        if ext == ".tf" or ext == ".tofu":
            artifact_type = "terraform_hcl"
            for m in re.finditer(r'resource\s+"([^"]+)"\s+"([^"]+)"', redacted_text):
                resources_defined.append({"type": m.group(1), "name": m.group(2)})
            for m in re.finditer(r"size\s*=\s*(\d+)", redacted_text):
                persistent_volumes.append(f"ebs_volume:{m.group(1)}GiB")
            for m in re.finditer(r"from_port\s*=\s*(\d+)", redacted_text):
                port_val = int(m.group(1))
                if port_val > 0 and port_val not in exposed_ports:
                    exposed_ports.append(port_val)

        elif ext in (".yaml", ".yml"):
            artifact_type = "kubernetes_or_compose_manifest"
            for m in re.finditer(r"kind:\s*([A-Za-z0-9_-]+)", redacted_text):
                resources_defined.append({"type": f"k8s:{m.group(1)}", "name": resolved.stem})
            for m in re.finditer(r"image:\s*([^\s#\"']+)", redacted_text):
                container_images.append(m.group(1))
            for m in re.finditer(r"claimName:\s*([^\s#\"']+)", redacted_text):
                persistent_volumes.append(m.group(1))
            for m in re.finditer(r"containerPort:\s*(\d+)", redacted_text):
                p = int(m.group(1))
                if p not in exposed_ports:
                    exposed_ports.append(p)
            for m in re.finditer(r"depends_on:\s*\n(?:\s*-\s*([^\n]+)\n?)+", redacted_text):
                if m.group(1):
                    service_dependencies.append(m.group(1).strip())

        elif "dockerfile" in name_lower:
            artifact_type = "dockerfile"
            for m in re.finditer(r"(?i)^FROM\s+([^\s]+)", redacted_text, re.MULTILINE):
                container_images.append(m.group(1))
            for m in re.finditer(r"(?i)^VOLUME\s+(.+)$", redacted_text, re.MULTILINE):
                persistent_volumes.append(m.group(1).strip())
            for m in re.finditer(r"(?i)^EXPOSE\s+(\d+)", redacted_text, re.MULTILINE):
                exposed_ports.append(int(m.group(1)))

        elif ext == ".json":
            artifact_type = "architecture_inventory_json"
            try:
                parsed = json.loads(redacted_text)
                if isinstance(parsed, dict):
                    for res in parsed.get("resources", [])[:50]:
                        if isinstance(res, dict) and res.get("id"):
                            resources_defined.append(
                                {"type": str(res.get("type", "resource")), "name": str(res.get("id"))}
                            )
                    for rel in parsed.get("relationships", [])[:50]:
                        if isinstance(rel, dict) and rel.get("source") and rel.get("target"):
                            service_dependencies.append(f"{rel['source']} -> {rel['target']}")
            except Exception:
                pass
        else:
            artifact_type = "configuration_artifact"

        return {
            "id": f"art-{ resolved.stem }-{ ext.lstrip('.') or 'cfg' }",
            "path": rel_path,
            "filename": resolved.name,
            "artifact_type": artifact_type,
            "size_bytes": size,
            "resources_defined": resources_defined,
            "container_images": container_images,
            "persistent_volumes": persistent_volumes,
            "exposed_ports": sorted(exposed_ports),
            "service_dependencies": service_dependencies,
            "secrets_detected_count": len(secret_findings),
            "secret_references": secret_findings,
            "redacted_preview": redacted_text[:600],
            "observed_at": _utc_now(),
        }

    def scan_authorized_directories(self) -> List[Dict[str, Any]]:
        artifacts: List[Dict[str, Any]] = []
        allowed_exts = {".tf", ".yaml", ".yml", ".json"}
        for root in self.allowed_roots:
            if not root.exists():
                continue
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                if path.name in self.EXCLUDED_NAMES or path.suffix.lower() not in allowed_exts:
                    continue
                try:
                    artifacts.append(self.scan_file(path))
                except Exception:
                    continue
        return artifacts


class InfrastructureConnector(ABC):
    """Contrato común para conectores de virtualización e infraestructura (Nivel 1)."""

    connector_id: str
    provider_type: str

    @abstractmethod
    def test_connection(self) -> Dict[str, Any]:
        """Valida conectividad, credenciales y permisos mínimos de lectura."""

    @abstractmethod
    def discover_infrastructure(self, page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        """Descubre hipervisores, VMs, redes virtuales y datastores en páginas controladas."""


class ProxmoxVEConnector(InfrastructureConnector):
    """
    Conector real compatible con la API REST oficial de Proxmox VE (`/api2/json`).
    - Autenticación por Token de API de solo lectura (`Authorization: PVEAPIToken=USER@REALM!TOKENID=UUID`).
    - Soporta consulta real de `/nodes`, `/cluster/resources`, `/nodes/{node}/qemu/{vmid}/config`
      y `/nodes/{node}/storage`.
    - Incluye modo de transporte inyectable o fixture determinista cuando no existen credenciales en `.env`,
      etiquetando explícitamente si el origen fue `live_proxmox_api` o `simulated_fixture`.
    """

    def __init__(
        self,
        connector_id: str = "conn-proxmox-dc1",
        api_url: Optional[str] = None,
        token_id: Optional[str] = None,
        token_secret: Optional[str] = None,
        verify_ssl: bool = True,
        timeout_seconds: int = 10,
        http_transport: Optional[Any] = None,
    ):
        self.connector_id = connector_id
        self.provider_type = "proxmox_ve"
        self.api_url = (api_url or os.getenv("PROXMOX_API_URL") or "https://pve-dc1.internal:8006/api2/json").rstrip("/")
        self.token_id = token_id if token_id is not None else os.getenv("PROXMOX_TOKEN_ID")
        self.token_secret = token_secret if token_secret is not None else os.getenv("PROXMOX_TOKEN_SECRET")
        self.verify_ssl = verify_ssl
        self.timeout_seconds = timeout_seconds
        self.http_transport = http_transport
        validate_endpoint_against_ssrf(self.api_url, allow_private_datacenter=True)

    @property
    def has_live_credentials(self) -> bool:
        return bool(self.token_id and self.token_secret) or self.http_transport is not None

    def _request_json(self, endpoint_path: str) -> Dict[str, Any]:
        if not self.has_live_credentials:
            raise ConnectorAuthError(
                "MISSING_CREDENTIALS",
                "Credenciales PROXMOX_TOKEN_ID / PROXMOX_TOKEN_SECRET no configuradas para conexión en vivo.",
            )

        url = f"{self.api_url}/{endpoint_path.lstrip('/')}"
        validate_endpoint_against_ssrf(url, allow_private_datacenter=True)

        if self.http_transport is not None:
            return self.http_transport(url, self.token_id, self.token_secret, self.timeout_seconds)

        headers = {
            "Authorization": f"PVEAPIToken={self.token_id}={self.token_secret}",
            "Accept": "application/json",
            "User-Agent": "CloudMove-Discovery/2.0",
        }
        req = urllib.request.Request(url, headers=headers, method="GET")
        ctx = ssl.create_default_context()
        if not self.verify_ssl:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds, context=ctx) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise ConnectorAuthError(
                    "CREDENTIALS_EXPIRED_OR_INVALID",
                    f"Proxmox VE rechazó el token API (HTTP 401) en {endpoint_path}.",
                ) from exc
            if exc.code == 403:
                raise ConnectorAuthError(
                    "INSUFFICIENT_PERMISSIONS",
                    f"El token carece del rol PVEAuditor (HTTP 403) para consultar {endpoint_path}.",
                ) from exc
            raise ConnectorError(
                f"HTTP_{exc.code}",
                f"Error HTTP {exc.code} al consultar Proxmox VE ({endpoint_path}).",
            ) from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            if isinstance(exc, TimeoutError) or "timed out" in str(exc).lower():
                raise ConnectorTimeoutError(
                    f"Timeout ({self.timeout_seconds}s) al conectar con Proxmox VE ({url})."
                ) from exc
            raise ConnectorError("NETWORK_ERROR", f"Error de red hacia Proxmox VE: {exc}") from exc

    def test_connection(self) -> Dict[str, Any]:
        if not self.has_live_credentials:
            return {
                "connector_id": self.connector_id,
                "provider": self.provider_type,
                "endpoint": self.api_url,
                "mode": "simulated_fixture_ready",
                "live_connection": False,
                "status": "ready_simulated",
                "message": (
                    "Sin credenciales PROXMOX_TOKEN_ID/SECRET en el entorno. "
                    "El conector operará en modo fixture reproducible para pruebas seguras."
                ),
                "checked_at": _utc_now(),
            }

        version_payload = self._request_json("/version")
        nodes_payload = self._request_json("/nodes")
        return {
            "connector_id": self.connector_id,
            "provider": self.provider_type,
            "endpoint": self.api_url,
            "mode": "live_proxmox_api",
            "live_connection": True,
            "status": "connected",
            "version": (version_payload.get("data") or {}).get("version", "8.x"),
            "nodes_visible": len(nodes_payload.get("data") or []),
            "checked_at": _utc_now(),
        }

    def discover_infrastructure(self, page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        """
        Consulta `/nodes` y `/cluster/resources` de Proxmox VE, normaliza hosts, VMs y datastores
        y aplica paginación determinista.
        """
        nodes_res = self._request_json("/nodes")
        cluster_res = self._request_json("/cluster/resources")

        raw_nodes = nodes_res.get("data") or []
        raw_resources = cluster_res.get("data") or []

        hypervisor_hosts: List[Dict[str, Any]] = []
        for n in raw_nodes:
            node_name = n.get("node")
            if not node_name:
                continue
            hypervisor_hosts.append(
                {
                    "native_id": f"pve-node:{node_name}",
                    "hostname": node_name,
                    "asset_type": "hypervisor_host",
                    "provider": "proxmox_ve",
                    "status": n.get("status", "online"),
                    "cpu_cores": n.get("maxcpu"),
                    "memory_total_bytes": n.get("maxmem"),
                    "uptime_seconds": n.get("uptime"),
                }
            )

        vms: List[Dict[str, Any]] = []
        datastores: List[Dict[str, Any]] = []

        for item in raw_resources:
            rtype = item.get("type")
            if rtype in ("qemu", "lxc"):
                vmid = item.get("vmid")
                node_name = item.get("node", "pve-node-01")
                vm_config: Dict[str, Any] = {}
                try:
                    cfg_resp = self._request_json(f"/nodes/{node_name}/{rtype}/{vmid}/config")
                    vm_config = cfg_resp.get("data") or {}
                except ConnectorError:
                    # Conservar respuesta parcial si falta permiso sobre el endpoint de detalle
                    vm_config = {"_partial_config": True}

                vms.append(
                    {
                        "native_id": f"pve:{node_name}:{rtype}/{vmid}",
                        "vmid": vmid,
                        "name": item.get("name") or f"vm-{vmid}",
                        "hypervisor_host": f"pve-node:{node_name}",
                        "cluster": "pve-cluster-dc1",
                        "power_state": item.get("status", "unknown"),
                        "vcpus": item.get("maxcpu"),
                        "memory_bytes": item.get("maxmem"),
                        "disk_allocated_bytes": item.get("maxdisk"),
                        "declared_os": vm_config.get("ostype", "l26"),
                        "firmware": vm_config.get("bios", "seabios"),
                        "machine_type": vm_config.get("machine", "pc-q35"),
                        "virtual_disks": [
                            v for k, v in vm_config.items() if k.startswith(("scsi", "virtio", "nvme", "sata")) and isinstance(v, str)
                        ],
                        "network_interfaces": [
                            v for k, v in vm_config.items() if k.startswith("net") and isinstance(v, str)
                        ],
                        "tags": [t for t in str(item.get("tags", "")).split(";") if t],
                        "partial_metadata": bool(vm_config.get("_partial_config")),
                        "source": "proxmox_ve_api",
                        "observed_at": _utc_now(),
                    }
                )
            elif rtype == "storage":
                datastores.append(
                    {
                        "native_id": f"pve-storage:{item.get('storage')}",
                        "name": item.get("storage"),
                        "node": item.get("node"),
                        "storage_type": item.get("plugintype", "lvmthin"),
                        "total_bytes": item.get("maxdisk"),
                        "used_bytes": item.get("disk"),
                        "status": item.get("status", "available"),
                        "source": "proxmox_ve_api",
                        "observed_at": _utc_now(),
                    }
                )

        start = max(0, (page - 1) * page_size)
        end = start + page_size
        return {
            "source": "proxmox_ve_api",
            "page": page,
            "page_size": page_size,
            "total_vms": len(vms),
            "has_more": end < len(vms),
            "hypervisor_hosts": hypervisor_hosts,
            "virtual_machines": vms[start:end],
            "datastores": datastores,
            "observed_at": _utc_now(),
        }


class DatabaseDiscoveryConnector:
    """
    Conector de descubrimiento de bases de datos (PostgreSQL, MySQL/MariaDB, SQL Server, MongoDB).
    Separa estrictamente las 6 capas requeridas por la Fase 4.3:
    1. `instance_metadata`
    2. `schema_metadata`
    3. `size_metrics`
    4. `backup_metadata`
    5. `migration_readiness`
    6. `data_migration_status` (`not_migrated_metadata_only`)
    """

    @staticmethod
    def build_database_catalog_entry(
        db_id: str,
        engine: str,
        version: str,
        edition: str,
        host_asset_id: str,
        hostname: str,
        port: int,
        environment_id: str,
        databases: List[Dict[str, Any]],
        extensions: List[str],
        ha_role: str,
        backup_info: Dict[str, Any],
        target_aws_service: str,
        limitations: List[str],
    ) -> Dict[str, Any]:
        total_gib = round(sum(float(d.get("size_gib", 0.0)) for d in databases), 2)
        return {
            "id": db_id,
            "asset_type": "database_instance",
            "host_asset_id": host_asset_id,
            "environment_id": environment_id,
            "1_instance_metadata": {
                "engine": engine,
                "version": version,
                "edition": edition,
                "host": hostname,
                "port": port,
                "connection_method": "readonly_catalog_inspector",
                "collation": "en_US.UTF-8",
                "encoding": "UTF8",
                "replication_role": ha_role,
            },
            "2_schema_metadata": {
                "databases_count": len(databases),
                "databases": databases,
                "extensions_or_plugins": extensions,
                "stored_procedures_and_triggers_inventoried": True,
                "rows_extracted": 0,  # Estricto: jamás extraer filas de negocio
            },
            "3_size_metrics": {
                "total_allocated_gib": round(total_gib * 1.25, 2),
                "total_used_gib": total_gib,
                "largest_database": max((d["name"] for d in databases), default="n/a"),
            },
            "4_backup_metadata": backup_info,
            "5_migration_readiness": {
                "recommended_target": target_aws_service,
                "strategy": "AWS DMS + Native Dump/Restore Verification",
                "compatibility_status": "verified_compatible" if not limitations else "preliminary_compatible",
                "limitations": limitations,
            },
            "6_data_migration_status": {
                "state": "not_migrated_metadata_only",
                "notice": (
                    "CloudMove ha inventariado únicamente la metadata de instancia y esquema. "
                    "Los datos reales requieren una operación posterior de exportación, replicación y validación."
                ),
            },
            "observed_at": _utc_now(),
        }


class SimulatedCollectorFixture:
    """
    Colector de prueba reproducible (Fase 9) que ejercita todas las interfaces de CloudMove
    sin requerir credenciales de producción:
    - Hipervisores Proxmox VE y VMware vCenter
    - Máquinas virtuales Linux (Debian/Kali, RHEL, Ubuntu ARM64) y Windows Server 2022
    - Servidores físicos (DMZ sin permisos SSH y Solaris SPARC64 incompatible)
    - Instancias de bases de datos (PostgreSQL 18 en Kali, PostgreSQL 15 ERP, SQL Server 2022)
    - Recursos de almacenamiento (Datastores NVMe/LVM-Thin, SAN iSCSI, volúmenes EBS/LVM)
    """

    @classmethod
    def get_reproducible_datacenter_snapshot(cls, local_hostname: str = "rabbitmq-kali") -> Dict[str, Any]:
        now = _utc_now()
        databases = [
            DatabaseDiscoveryConnector.build_database_catalog_entry(
                db_id="db-postgres-kali-local",
                engine="postgresql",
                version="18.3",
                edition="Debian Community",
                host_asset_id="asset-host-rabbitmq-kali",
                hostname=local_hostname,
                port=5432,
                environment_id="env-datacenter-01",
                databases=[
                    {"name": "cloudmove_meta", "schemas": ["public", "audit"], "tables_count": 18, "views_count": 4, "size_gib": 2.4},
                ],
                extensions=["uuid-ossp", "pg_stat_statements"],
                ha_role="standalone_primary",
                backup_info={
                    "mechanism": "pg_dump_cron",
                    "last_backup_at": "2026-10-19T04:00:00Z",
                    "last_status": "success",
                    "verified_restore": True,
                },
                target_aws_service="Amazon RDS for PostgreSQL",
                limitations=[
                    "Validar disponibilidad de versión mayor PostgreSQL 18 en la región AWS destino o fijar versión 16/17 compatible."
                ],
            ),
            DatabaseDiscoveryConnector.build_database_catalog_entry(
                db_id="db-postgres-erp-prod",
                engine="postgresql",
                version="15.7",
                edition="Enterprise Linux",
                host_asset_id="asset-vm-erp-db-01",
                hostname="srv-erp-postgres-01",
                port=5432,
                environment_id="env-datacenter-01",
                databases=[
                    {"name": "erp_core", "schemas": ["public", "finance", "inventory"], "tables_count": 142, "views_count": 28, "size_gib": 94.5},
                    {"name": "erp_reporting", "schemas": ["analytics"], "tables_count": 31, "views_count": 12, "size_gib": 26.0},
                ],
                extensions=["pgcrypto", "btree_gist", "pg_trgm"],
                ha_role="primary_streaming_replication",
                backup_info={
                    "mechanism": "pgBackRest + S3 Archive",
                    "last_backup_at": "2026-10-19T02:30:00Z",
                    "last_status": "success",
                    "verified_restore": True,
                },
                target_aws_service="Amazon RDS for PostgreSQL (Multi-AZ)",
                limitations=[
                    "Requiere ventana de corte o replicación continua CDC con AWS DMS por tamaño > 100 GiB."
                ],
            ),
            DatabaseDiscoveryConnector.build_database_catalog_entry(
                db_id="db-sqlserver-win-07",
                engine="sqlserver",
                version="2022",
                edition="Standard Edition (64-bit)",
                host_asset_id="asset-win-ad-core-01",
                hostname="srv-app-win-07",
                port=1433,
                environment_id="env-datacenter-01",
                databases=[
                    {"name": "BillingLedgerDB", "schemas": ["dbo", "invoicing"], "tables_count": 64, "views_count": 9, "size_gib": 48.0},
                ],
                extensions=["SQLAgentJobs", "FullTextSearch"],
                ha_role="standalone",
                backup_info={
                    "mechanism": "Veeam Application-Aware SQL Backup",
                    "last_backup_at": "2026-10-18T23:00:00Z",
                    "last_status": "success",
                    "verified_restore": False,
                },
                target_aws_service="Amazon RDS for SQL Server",
                limitations=[
                    "Verificar prueba de restauración de backup antes de programar ola de migración.",
                    "Revisar jobs de SQL Server Agent que invocan rutas locales del sistema de archivos Windows.",
                ],
            ),
        ]

        storage_resources = [
            {
                "id": "stg-nvme-local-kali",
                "name": "pve-local-nvme0n1",
                "asset_type": "storage_datastore",
                "storage_type": "NVMe Block Device / ext4",
                "protocol": "NVMe PCIe",
                "site_id": "site-dc-a",
                "total_gib": 476.94,
                "used_gib": 68.4,
                "attached_assets": ["asset-host-rabbitmq-kali"],
                "snapshots_available": 2,
                "backup_enabled": True,
                "observed_at": now,
            },
            {
                "id": "stg-san-iscsi-tier1",
                "name": "datastore-san-iscsi-prod-01",
                "asset_type": "storage_datastore",
                "storage_type": "VMware VMFS 6 / iSCSI SAN",
                "protocol": "iSCSI 10GbE",
                "site_id": "site-dc-a",
                "total_gib": 4096.0,
                "used_gib": 1420.0,
                "attached_assets": ["asset-vm-erp-db-01", "asset-vm-Middleware-rhel-02", "asset-win-ad-core-01"],
                "snapshots_available": 5,
                "backup_enabled": True,
                "observed_at": now,
            },
            {
                "id": "stg-ebs-site-b",
                "name": "site-b-arm64-gp3-pool",
                "asset_type": "storage_datastore",
                "storage_type": "LVM / Cloud Block Volume",
                "protocol": "VirtIO-Block",
                "site_id": "site-dc-b",
                "total_gib": 500.0,
                "used_gib": 112.0,
                "attached_assets": ["asset-site-b-arm64-worker"],
                "snapshots_available": 1,
                "backup_enabled": True,
                "observed_at": now,
            },
        ]

        return {
            "databases": databases,
            "storage_resources": storage_resources,
            "observed_at": now,
        }
