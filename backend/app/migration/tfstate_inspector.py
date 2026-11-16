"""
Terraform State & Diagnostics Inspector for CloudMove.

Isolated module responsible for:
- Parsing `terraform.tfstate` into normalized CloudMove resources & outputs.
- Safe JSON mutation when syncing dynamic EC2 public IPs.
- Classifying Terraform CLI failure logs into actionable user remediations.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


_TERRAFORM_DIAGNOSIS_RULES: List[tuple[re.Pattern[str], str, str, str, str, bool]] = [
    (
        re.compile(
            r'first character of "identifier" must be a letter|only lowercase alphanumeric characters and hyphens|name_prefix.*cannot be longer|RFC1035|InvalidParameterValue.*(?:identifier|cluster|bucket|name)|Identificador (?:RDS|ElastiCache|HCL) inválido|Nombre de bucket inválido|name_prefix.*excede el límite',
            re.IGNORECASE,
        ),
        "INVALID_CLOUD_IDENTIFIER",
        "Identificador de recurso inválido para AWS",
        "Un nombre generado (por ejemplo desde un repositorio que inicia con dígito como '2026-2' o excede el límite de caracteres) incumple las reglas de nomenclatura de AWS.",
        "Haz clic en 'Reparar y Regenerar Manifiestos' para normalizar automáticamente los identificadores con prefijos válidos y volver a validar antes de desplegar.",
        True,
    ),
    (
        re.compile(
            r"Reference to undeclared resource|Reference to undeclared input variable|Unsupported block type|Unsupported argument",
            re.IGNORECASE,
        ),
        "HCL_SYNTAX_OR_REF_ERROR",
        "Inconsistencia sintáctica o referencia HCL en los manifiestos",
        "Existe una referencia o bloque en main.tf/outputs.tf generado con una versión anterior o configuración inconsistente.",
        "Ejecuta 'Reparar y Regenerar Manifiestos' para resintetizar la plantilla Terraform y vuelve a ejecutar Dry-Run.",
        True,
    ),
    (
        re.compile(
            r"ExpiredToken|InvalidClientTokenId|security token included in the request is expired|AuthFailure|No valid credential sources found",
            re.IGNORECASE,
        ),
        "AWS_CREDENTIALS_EXPIRED",
        "Credenciales o Session Token de AWS expirados o inválidos",
        "Las credenciales temporales (AWS Academy / STS) caducaron o son incorrectas.",
        "Actualiza AWS Access Key ID, Secret Access Key y Session Token en el Paso 1, pulsa 'Comprobar Identidad AWS / STS' y reintenta con 'Continuar / Aplicar'.",
        False,
    ),
    (
        re.compile(r"AccessDenied|UnauthorizedOperation|is not authorized to perform", re.IGNORECASE),
        "AWS_PERMISSION_DENIED",
        "Permiso IAM insuficiente en la cuenta AWS destino",
        "El rol o usuario STS actual no tiene permiso para crear uno de los recursos planificados (frecuente en AWS Academy con IAM Roles personalizados).",
        "Si falla creando aws_iam_role, selecciona 'Omitir IAM personalizado (skip_custom_iam)' en las decisiones de arquitectura y regenera los manifiestos.",
        True,
    ),
    (
        re.compile(
            r"DBInstanceAlreadyExists|BucketAlreadyExists|BucketAlreadyOwnedByYou|InvalidGroup\.Duplicate|EntityAlreadyExists",
            re.IGNORECASE,
        ),
        "RESOURCE_ALREADY_EXISTS",
        "El recurso ya existe previamente en AWS",
        "Un intento previo dejó el recurso creado en AWS fuera de terraform.tfstate (o el nombre de bucket ya está en uso globalmente).",
        "Usa 'terraform refresh' / 'Continuar / Aplicar' o ejecuta 'Reparar y Regenerar Manifiestos' para asignar identificadores únicos e importar estado.",
        True,
    ),
    (
        re.compile(r"Error acquiring the state lock", re.IGNORECASE),
        "STATE_LOCKED",
        "Estado de Terraform bloqueado por ejecución previa",
        "Un proceso anterior dejó el archivo .terraform.tfstate.lock.info activo.",
        "Pulsa 'Desbloquear Estado' en la barra de comandos y luego reintenta el despliegue.",
        False,
    ),
    (
        re.compile(
            r"VcpuLimitExceeded|InsufficientInstanceCapacity|DBSubnetGroupDoesNotCoverEnoughAZs|QuotaExceeded|LimitExceeded",
            re.IGNORECASE,
        ),
        "QUOTA_OR_CAPACITY",
        "Límite de cuota o disponibilidad de zona en AWS",
        "La región o cuenta sandbox alcanzó un límite de instancias, subredes o vCPUs.",
        "Cambia el perfil de cómputo a Free-Tier ('single_instance_containerized' / t3.micro) o cambia de región AWS y reintenta.",
        False,
    ),
]


def diagnose_terraform_failure(logs: List[str], provider: str = "aws") -> Optional[Dict[str, Any]]:
    """Classify the latest Terraform error block into an actionable remediation summary."""
    tail_blob = "\n".join(logs[-100:])
    if not tail_blob.strip():
        return None
    for pat, code, title, cause, remediation, can_regen in _TERRAFORM_DIAGNOSIS_RULES:
        m = pat.search(tail_blob)
        if m:
            return {
                "code": code,
                "provider": provider.upper(),
                "title": title,
                "matched_snippet": m.group(0)[:220],
                "cause": cause,
                "remediation": remediation,
                "can_auto_regenerate": can_regen,
            }
    err_lines = [ln.strip() for ln in logs[-40:] if "Error:" in ln or "[ERROR]" in ln]
    return {
        "code": "TERRAFORM_EXECUTION_ERROR",
        "provider": provider.upper(),
        "title": "Fallo en la ejecución de Terraform",
        "matched_snippet": err_lines[0][:220] if err_lines else "",
        "cause": err_lines[0] if err_lines else "Terraform retornó un código de salida distinto de cero.",
        "remediation": "Revisa el detalle en la terminal de logs o regenera los manifiestos si realizaste cambios recientes.",
        "can_auto_regenerate": True,
    }


def inspect_tfstate(job_dir: Path) -> Dict[str, Any]:
    """
    Parse `terraform.tfstate` directly to extract live provisioned resources,
    IDs, public IPs, DNS hostnames, and synthesized outputs.
    """
    tfstate_path = job_dir / "terraform.tfstate"
    result: Dict[str, Any] = {
        "has_state_file": tfstate_path.is_file(),
        "serial": 0,
        "terraform_version": None,
        "resource_count": 0,
        "resources": [],
        "outputs": {},
        "primary_instance": None,
    }
    if not tfstate_path.is_file():
        return result

    try:
        raw = json.loads(tfstate_path.read_text(encoding="utf-8"))
        result["serial"] = raw.get("serial", 0)
        result["terraform_version"] = raw.get("terraform_version")

        raw_outputs = raw.get("outputs") or {}
        for k, v in raw_outputs.items():
            if isinstance(v, dict):
                result["outputs"][k] = {
                    "value": v.get("value"),
                    "type": v.get("type", "string"),
                }

        resources_list: List[Dict[str, Any]] = []
        for r in raw.get("resources") or []:
            mode = r.get("mode", "managed")
            r_type = r.get("type", "")
            r_name = r.get("name", "")
            address = f"{'data.' if mode == 'data' else ''}{r_type}.{r_name}"
            for idx, inst in enumerate(r.get("instances") or []):
                attrs = inst.get("attributes") or {}
                res_id = attrs.get("id") or attrs.get("arn") or ""
                item = {
                    "address": address if idx == 0 else f"{address}[{idx}]",
                    "mode": mode,
                    "type": r_type,
                    "name": r_name,
                    "id": res_id,
                    "arn": attrs.get("arn"),
                    "public_ip": attrs.get("public_ip"),
                    "private_ip": attrs.get("private_ip"),
                    "public_dns": attrs.get("public_dns"),
                    "instance_state": attrs.get("instance_state"),
                    "instance_type": attrs.get("instance_type"),
                    "cidr_block": attrs.get("cidr_block"),
                    "availability_zone": attrs.get("availability_zone"),
                    "dns_name": attrs.get("dns_name"),
                    "tags": attrs.get("tags") or {},
                }
                resources_list.append(item)

                if mode == "managed" and r_type == "aws_instance":
                    result["primary_instance"] = item
                    pub_ip = attrs.get("public_ip")
                    pub_dns = attrs.get("public_dns")
                    if res_id and "instance_id" not in result["outputs"]:
                        result["outputs"]["instance_id"] = {"value": res_id, "type": "string"}
                    if pub_ip:
                        result["outputs"].setdefault("instance_public_ip", {"value": pub_ip, "type": "string"})
                        result["outputs"].setdefault("frontend_url", {"value": f"http://{pub_ip}:3000", "type": "string"})
                        result["outputs"].setdefault("backend_api_url", {"value": f"http://{pub_ip}:8000", "type": "string"})
                        result["outputs"].setdefault("app_endpoint", {"value": f"http://{pub_ip}:3000", "type": "string"})
                        result["outputs"].setdefault("ssh_command", {"value": f"ssh ubuntu@{pub_ip}", "type": "string"})
                    if pub_dns:
                        result["outputs"].setdefault("instance_public_dns", {"value": pub_dns, "type": "string"})
                elif mode == "managed" and r_type == "aws_vpc" and res_id:
                    result["outputs"].setdefault("vpc_id", {"value": res_id, "type": "string"})
                elif mode == "managed" and r_type == "aws_security_group" and res_id:
                    result["outputs"].setdefault("security_group_id", {"value": res_id, "type": "string"})

        managed_resources = [x for x in resources_list if x["mode"] == "managed"]
        result["resources"] = resources_list
        result["managed_resources"] = managed_resources
        result["resource_count"] = len(managed_resources)
    except Exception as exc:
        result["parse_error"] = str(exc)

    return result


def sync_tfstate_instance_ips(
    deployment_roots: List[Path],
    live_ip_by_instance_id: Dict[str, str],
) -> List[Dict[str, str]]:
    """Safely update mutated EC2 `public_ip` values in parsed `terraform.tfstate` JSON files."""
    ip_sync_events: List[Dict[str, str]] = []
    for root in deployment_roots:
        if not root.is_dir():
            continue
        for child in root.iterdir():
            tfstate_file = child / "terraform.tfstate"
            if not tfstate_file.is_file():
                continue
            try:
                tf_json = json.loads(tfstate_file.read_text(encoding="utf-8"))
                dirty = False
                for res_block in tf_json.get("resources") or []:
                    if res_block.get("mode") == "managed" and res_block.get("type") == "aws_instance":
                        for inst_entry in res_block.get("instances") or []:
                            attrs = inst_entry.get("attributes") or {}
                            tf_iid = attrs.get("id")
                            tf_old_ip = attrs.get("public_ip")
                            live_ip = live_ip_by_instance_id.get(tf_iid or "")
                            if tf_iid and live_ip and tf_old_ip and tf_old_ip != live_ip:
                                attrs["public_ip"] = live_ip
                                for out_obj in (tf_json.get("outputs") or {}).values():
                                    if isinstance(out_obj, dict) and isinstance(out_obj.get("value"), str) and tf_old_ip in out_obj["value"]:
                                        out_obj["value"] = out_obj["value"].replace(tf_old_ip, live_ip)
                                dirty = True
                                ip_sync_events.append({
                                    "migration_id": child.name,
                                    "instance_id": tf_iid,
                                    "old_ip": tf_old_ip,
                                    "new_ip": live_ip,
                                })
                if dirty:
                    tfstate_file.write_text(json.dumps(tf_json, indent=2), encoding="utf-8")
            except Exception:
                pass
    return ip_sync_events
