"""
AWS Live Account Audit & Resource Cleanup Service for CloudMove.

Decoupled from Terraform CLI process streaming (`cloud_deployer.py`). Operates on
per-request user credentials via injected session/workspace callbacks and dynamically
protects the hosting CloudMove control-plane infrastructure.
"""

from __future__ import annotations

import json
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.config import ALLOW_SERVER_AWS_FALLBACK
from app.core.security import get_control_plane_metadata, validate_safe_id
from app.migration.tfstate_inspector import sync_tfstate_instance_ips


def boto_config(read_timeout: int = 10):
    from botocore.config import Config as BotocoreConfig

    return BotocoreConfig(
        connect_timeout=5,
        read_timeout=read_timeout,
        retries={"max_attempts": 2},
    )


def create_boto3_session(
    build_env_fn: Callable[[Optional[Dict[str, str]]], Dict[str, str]],
    credentials: Optional[Dict[str, str]] = None,
) -> Tuple[Any, str]:
    import boto3

    env = build_env_fn(credentials)
    ak = env.get("AWS_ACCESS_KEY_ID", "").strip()
    sk = env.get("AWS_SECRET_ACCESS_KEY", "").strip()
    st = env.get("AWS_SESSION_TOKEN", "").strip() or None
    reg = env.get("AWS_DEFAULT_REGION", "us-east-1").strip() or "us-east-1"
    if ak and sk:
        return boto3.Session(
            aws_access_key_id=ak,
            aws_secret_access_key=sk,
            aws_session_token=st,
            region_name=reg,
        ), reg
    if not ALLOW_SERVER_AWS_FALLBACK:
        raise ValueError(
            "Credenciales AWS requeridas para esta sesión web "
            "(no se reutilizan credenciales del servidor ni de otros usuarios)."
        )
    return boto3.Session(region_name=reg), reg


def _quick_tcp(host: str, port: int, timeout: float = 1.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def audit_aws_account(
    *,
    workspace_root: Path,
    list_workspaces_fn: Callable[[], List[Dict[str, Any]]],
    build_env_fn: Callable[[Optional[Dict[str, str]]], Dict[str, str]],
    credentials: Optional[Dict[str, str]] = None,
    jobs_lookup_fn: Optional[Callable[[], List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """
    Audit running AWS resources (EC2 instances, EBS volumes, VPCs, Security Groups, EIPs)
    plus local Terraform workspaces for the requesting session's AWS credentials.
    """
    workspaces = list_workspaces_fn()
    has_explicit = bool(
        isinstance(credentials, dict)
        and credentials.get("aws_access_key_id")
        and credentials.get("aws_secret_access_key")
    )
    if not has_explicit and not ALLOW_SERVER_AWS_FALLBACK:
        return {
            "authenticated": False,
            "requires_credentials": True,
            "error": "Ingresa tus credenciales AWS en esta sesión para auditar tu cuenta AWS.",
            "workspaces": workspaces,
            "instances": [],
            "volumes": [],
            "vpcs": [],
            "security_groups": [],
            "elastic_ips": [],
        }

    cp_meta = get_control_plane_metadata()
    cp_url = cp_meta.get("public_api_url") or ""

    try:
        session, region = create_boto3_session(build_env_fn, credentials)
        cfg = boto_config(read_timeout=10)
        sts = session.client("sts", config=cfg)
        caller = sts.get_caller_identity()
        account_id = caller.get("Account", "")
        caller_arn = caller.get("Arn", "")
    except Exception as exc:
        return {
            "authenticated": False,
            "error": f"No se pudo autenticar con AWS STS: {str(exc)}",
            "workspaces": workspaces,
            "instances": [],
            "volumes": [],
            "vpcs": [],
            "security_groups": [],
            "elastic_ips": [],
        }

    try:
        ec2 = session.client("ec2", region_name=region, config=cfg)

        # 1. EC2 Instances
        inst_resp = ec2.describe_instances()
        instances: List[Dict[str, Any]] = []
        live_ip_by_instance_id: Dict[str, str] = {}
        instance_name_by_id: Dict[str, str] = {}
        control_plane_instance_ids = set(cp_meta.get("protected_instance_ids") or set())
        control_plane_vpc_ids = set(cp_meta.get("protected_vpc_ids") or set())
        probe_targets: List[tuple[int, str]] = []

        for resv in inst_resp.get("Reservations", []):
            for inst in resv.get("Instances", []):
                iid = inst.get("InstanceId", "")
                state_name = (inst.get("State") or {}).get("Name", "unknown")
                tags_dict = {t["Key"]: t["Value"] for t in (inst.get("Tags") or []) if "Key" in t and "Value" in t}
                name = tags_dict.get("Name") or iid
                pub_ip = inst.get("PublicIpAddress") or ""
                priv_ip = inst.get("PrivateIpAddress") or ""
                vpc_id = inst.get("VpcId") or ""
                is_cp = bool(
                    name == "cloudmove-server"
                    or tags_dict.get("Project") == "CloudMove-Capstone"
                    or tags_dict.get("Role") == "cloudmove-control-plane"
                    or iid in control_plane_instance_ids
                    or (pub_ip and pub_ip in cp_meta.get("protected_ips", set()))
                    or (priv_ip and priv_ip in cp_meta.get("protected_ips", set()))
                )
                if is_cp:
                    control_plane_instance_ids.add(iid)
                    if vpc_id:
                        control_plane_vpc_ids.add(vpc_id)

                instance_name_by_id[iid] = name
                if pub_ip and state_name == "running":
                    live_ip_by_instance_id[iid] = pub_ip

                launch_time = inst.get("LaunchTime")
                launch_iso = launch_time.isoformat() if hasattr(launch_time, "isoformat") else str(launch_time or "")

                idx = len(instances)
                if state_name == "running" and pub_ip and not is_cp:
                    probe_targets.append((idx, pub_ip))

                cp_front = cp_url if (is_cp and cp_url) else (f"https://{pub_ip}" if is_cp and pub_ip else None)
                cp_back = f"{cp_front}/api/v1/health" if cp_front else None
                instances.append({
                    "instance_id": iid,
                    "name": name,
                    "state": state_name,
                    "instance_type": inst.get("InstanceType", ""),
                    "public_ip": pub_ip,
                    "private_ip": priv_ip,
                    "vpc_id": vpc_id,
                    "subnet_id": inst.get("SubnetId", ""),
                    "availability_zone": (inst.get("Placement") or {}).get("AvailabilityZone", ""),
                    "launch_time": launch_iso,
                    "tags": tags_dict,
                    "managed_by_cloudmove": tags_dict.get("ManagedBy") == "CloudMove",
                    "cmir_id": tags_dict.get("CMIR_ID", ""),
                    "cmir_type": tags_dict.get("CMIR_Type", ""),
                    "is_control_plane": is_cp,
                    "frontend_online": False,
                    "backend_online": False,
                    "frontend_url": f"http://{pub_ip}:3000" if pub_ip and not is_cp else cp_front,
                    "backend_url": f"http://{pub_ip}:8000/health" if pub_ip and not is_cp else cp_back,
                    "docs_url": f"http://{pub_ip}:8000/docs" if pub_ip and not is_cp else None,
                })

        if probe_targets:
            with ThreadPoolExecutor(max_workers=min(6, len(probe_targets) * 2)) as pool:
                fut_map = {
                    idx: (
                        pool.submit(_quick_tcp, pub_ip, 3000, 1.0),
                        pool.submit(_quick_tcp, pub_ip, 8000, 1.0),
                    )
                    for idx, pub_ip in probe_targets
                }
                for idx, (fe_f, be_f) in fut_map.items():
                    instances[idx]["frontend_online"] = fe_f.result()
                    instances[idx]["backend_online"] = be_f.result()

        instances.sort(key=lambda x: (x["state"] != "running", x["is_control_plane"], x["name"]))

        # 2. Auto-sync dynamic public IPs in parsed terraform.tfstate JSON
        roots = [
            Path("generated/deployments"),
            workspace_root / "generated" / "deployments",
            Path("/app/generated/deployments"),
            Path("/generated/deployments"),
        ]
        ip_sync_events = sync_tfstate_instance_ips(roots, live_ip_by_instance_id)
        if ip_sync_events:
            workspaces = list_workspaces_fn()

        jobs_by_id: Dict[str, Dict[str, Any]] = {}
        try:
            job_rows = jobs_lookup_fn() if jobs_lookup_fn else []
            for j in job_rows:
                jid = j.get("migration_id")
                if jid:
                    jobs_by_id[jid] = j
        except Exception:
            pass

        def _build_project_meta(
            mig_id: Optional[str],
            inst_hint: Optional[Dict[str, Any]] = None,
            is_cp: bool = False,
            is_default_net: bool = False,
        ) -> Dict[str, Any]:
            if is_cp:
                return {
                    "project_id": "cloudmove-control-plane",
                    "project_name": "Servidor Principal CloudMove (Control Plane)",
                    "use_case": "control_plane",
                    "use_case_label": "Infraestructura Base CloudMove",
                    "source_detail": "deploy/aws (Control Plane EC2)",
                    "migration_id": "deploy/aws",
                    "is_control_plane": True,
                }
            job_obj = jobs_by_id.get(mig_id or "") if mig_id else None
            if job_obj:
                uc = job_obj.get("use_case", "app_source")
                uc_label = (
                    "Caso 1 · Aplicación (GitHub / Código)"
                    if uc == "app_source"
                    else "Caso 2 · Imagen de SO / Máquina Virtual"
                )
                src_cfg = job_obj.get("source_config") or {}
                src_env = job_obj.get("source_environment") or {}
                src_detail = (
                    src_cfg.get("repo_url")
                    or src_env.get("repository_url")
                    or src_env.get("hostname")
                    or src_cfg.get("image_path")
                    or "Origen CloudMove"
                )
                return {
                    "project_id": mig_id,
                    "project_name": job_obj.get("name") or mig_id,
                    "use_case": uc,
                    "use_case_label": uc_label,
                    "source_detail": str(src_detail),
                    "migration_id": mig_id,
                    "is_control_plane": False,
                }
            if inst_hint:
                iname = inst_hint.get("name", "")
                ctype = inst_hint.get("cmir_type", "")
                if ctype == "container":
                    return {
                        "project_id": mig_id or f"unlinked-{inst_hint.get('instance_id', 'app')}",
                        "project_name": f"Despliegue Aplicación: {iname}",
                        "use_case": "app_source",
                        "use_case_label": "Caso 1 · Aplicación (Contenedores)",
                        "source_detail": iname or "Aplicación en Contenedores",
                        "migration_id": mig_id,
                        "is_control_plane": False,
                    }
                if "live-os" in iname.lower() or ctype == "virtual_machine":
                    return {
                        "project_id": mig_id or f"unlinked-{inst_hint.get('instance_id', 'vm')}",
                        "project_name": f"Migración de SO / Máquina Virtual ({iname})",
                        "use_case": "vm_image",
                        "use_case_label": "Caso 2 · Imagen de SO / VM",
                        "source_detail": iname,
                        "migration_id": mig_id,
                        "is_control_plane": False,
                    }
            if mig_id:
                uc_guess = "app_source" if "app" in mig_id else ("vm_image" if "vm" in mig_id else "other")
                return {
                    "project_id": mig_id,
                    "project_name": f"Despliegue Terraform ({mig_id})",
                    "use_case": uc_guess,
                    "use_case_label": "Caso 1 · Aplicación" if uc_guess == "app_source" else "Caso 2 · Imagen VM",
                    "source_detail": f"generated/deployments/{mig_id}",
                    "migration_id": mig_id,
                    "is_control_plane": False,
                }
            if is_default_net:
                return {
                    "project_id": "aws-default-network",
                    "project_name": "Red por Defecto de la Cuenta AWS (Default VPC)",
                    "use_case": "control_plane",
                    "use_case_label": "Red Base AWS / Servidor CloudMove",
                    "source_detail": "AWS Default VPC (172.31.0.0/16)",
                    "migration_id": "deploy/aws",
                    "is_control_plane": True,
                }
            return {
                "project_id": "unassigned-aws-resource",
                "project_name": "Recurso en Cuenta AWS (Despliegue Previo / Sin Workspace)",
                "use_case": "external",
                "use_case_label": "Recurso Huérfano / Externo",
                "source_detail": "Cuenta AWS EC2",
                "migration_id": None,
                "is_control_plane": False,
            }

        ws_by_resource_id: Dict[str, str] = {}
        ws_by_instance: Dict[str, str] = {}
        ws_by_vpc: Dict[str, str] = {}
        for ws in workspaces:
            mid = ws["migration_id"]
            if ws.get("primary_instance_id"):
                ws_by_instance[ws["primary_instance_id"]] = mid
                ws_by_resource_id[ws["primary_instance_id"]] = mid
            if ws.get("vpc_id"):
                ws_by_vpc[ws["vpc_id"]] = mid
                ws_by_resource_id[ws["vpc_id"]] = mid
            for mr in ws.get("managed_resources") or []:
                if mr.get("id"):
                    ws_by_resource_id[mr["id"]] = mid

        instance_by_id: Dict[str, Dict[str, Any]] = {}
        vpc_to_project_meta: Dict[str, Dict[str, Any]] = {}
        for inst in instances:
            iid = inst["instance_id"]
            mid = ws_by_instance.get(iid) or ws_by_vpc.get(inst.get("vpc_id") or "")
            pmeta = _build_project_meta(mid, inst_hint=inst, is_cp=inst["is_control_plane"])
            inst["migration_id"] = pmeta.get("migration_id")
            inst["project_info"] = pmeta
            instance_by_id[iid] = inst
            if inst.get("vpc_id") and not inst["is_control_plane"]:
                vpc_to_project_meta[inst["vpc_id"]] = pmeta
                if pmeta.get("migration_id") and inst["vpc_id"] not in ws_by_vpc:
                    ws_by_vpc[inst["vpc_id"]] = pmeta["migration_id"]

        for ws in workspaces:
            ws["project_info"] = _build_project_meta(ws["migration_id"])

        # 3. EBS Volumes
        vol_resp = ec2.describe_volumes()
        volumes: List[Dict[str, Any]] = []
        for v in vol_resp.get("Volumes", []):
            vid = v.get("VolumeId", "")
            sz = int(v.get("Size", 0))
            atts = v.get("Attachments") or []
            att_iid = atts[0].get("InstanceId", "") if atts else ""
            att_dev = atts[0].get("Device", "") if atts else ""
            is_cp = att_iid in control_plane_instance_ids
            att_inst = instance_by_id.get(att_iid)
            vol_pmeta = (
                att_inst["project_info"]
                if att_inst and att_inst.get("project_info")
                else _build_project_meta(ws_by_resource_id.get(vid), is_cp=is_cp)
            )
            ctime = v.get("CreateTime")
            volumes.append({
                "volume_id": vid,
                "size_gb": sz,
                "volume_type": v.get("VolumeType", "gp3"),
                "state": v.get("State", ""),
                "encrypted": bool(v.get("Encrypted")),
                "attached_instance_id": att_iid,
                "attached_instance_name": instance_name_by_id.get(att_iid, att_iid),
                "device": att_dev,
                "create_time": ctime.isoformat() if hasattr(ctime, "isoformat") else str(ctime or ""),
                "is_control_plane": is_cp,
                "migration_id": vol_pmeta.get("migration_id"),
                "project_info": vol_pmeta,
            })

        # 4. VPCs, Subnets & Internet Gateways
        vpc_resp = ec2.describe_vpcs()
        sub_resp = ec2.describe_subnets()
        igw_resp = ec2.describe_internet_gateways()

        subnets_by_vpc: Dict[str, List[Dict[str, Any]]] = {}
        for sb in sub_resp.get("Subnets", []):
            svpc = sb.get("VpcId", "")
            stags = {t["Key"]: t["Value"] for t in (sb.get("Tags") or []) if "Key" in t and "Value" in t}
            subnets_by_vpc.setdefault(svpc, []).append({
                "subnet_id": sb.get("SubnetId", ""),
                "name": stags.get("Name") or sb.get("SubnetId", ""),
                "cidr_block": sb.get("CidrBlock", ""),
                "availability_zone": sb.get("AvailabilityZone", ""),
                "vpc_id": svpc,
            })

        igws_by_vpc: Dict[str, List[str]] = {}
        for igw in igw_resp.get("InternetGateways", []):
            igw_id = igw.get("InternetGatewayId", "")
            for att in igw.get("Attachments") or []:
                if att.get("VpcId"):
                    igws_by_vpc.setdefault(att["VpcId"], []).append(igw_id)

        vpcs: List[Dict[str, Any]] = []
        for vp in vpc_resp.get("Vpcs", []):
            vid = vp.get("VpcId", "")
            vtags = {t["Key"]: t["Value"] for t in (vp.get("Tags") or []) if "Key" in t and "Value" in t}
            vname = vtags.get("Name") or ("default-vpc" if vp.get("IsDefault") else vid)
            active_insts = [i for i in instances if i["vpc_id"] == vid and i["state"] not in ("terminated", "shutting-down")]
            is_cp = bool(vp.get("IsDefault") or vid in control_plane_vpc_ids)
            mid = ws_by_vpc.get(vid) or ws_by_resource_id.get(vid)
            vp_pmeta = (
                vpc_to_project_meta.get(vid)
                or _build_project_meta(mid, is_cp=is_cp, is_default_net=bool(vp.get("IsDefault")))
            )
            vpc_to_project_meta[vid] = vp_pmeta
            vpcs.append({
                "vpc_id": vid,
                "name": vname,
                "cidr_block": vp.get("CidrBlock", ""),
                "is_default": bool(vp.get("IsDefault")),
                "state": vp.get("State", "available"),
                "managed_by_cloudmove": vname.startswith("cloudmove") or vtags.get("ManagedBy") == "CloudMove",
                "active_instance_count": len(active_insts),
                "active_instance_ids": [i["instance_id"] for i in active_insts],
                "subnets": subnets_by_vpc.get(vid, []),
                "internet_gateways": igws_by_vpc.get(vid, []),
                "migration_id": vp_pmeta.get("migration_id"),
                "project_info": vp_pmeta,
                "is_control_plane": is_cp,
            })

        # 5. Security Groups
        sg_resp = ec2.describe_security_groups()
        security_groups: List[Dict[str, Any]] = []
        for sg in sg_resp.get("SecurityGroups", []):
            gid = sg.get("GroupId", "")
            gname = sg.get("GroupName", "")
            vpc_id = sg.get("VpcId", "")
            ports = []
            for perm in sg.get("IpPermissions") or []:
                fp = perm.get("FromPort")
                tp = perm.get("ToPort")
                if fp is not None:
                    ports.append(str(fp) if fp == tp else f"{fp}-{tp}")
            is_cp = bool(gname == "default" or "cloudmove-sg" in gname or (vpc_id in control_plane_vpc_ids and gname != "cloudmove-app-sg"))
            sg_pmeta = (
                _build_project_meta(None, is_cp=True)
                if "cloudmove-sg" in gname
                else vpc_to_project_meta.get(vpc_id)
                or _build_project_meta(ws_by_resource_id.get(gid), is_cp=is_cp)
            )
            security_groups.append({
                "group_id": gid,
                "group_name": gname,
                "vpc_id": vpc_id,
                "description": sg.get("Description", ""),
                "is_default": gname == "default",
                "ingress_ports": ports,
                "is_control_plane": is_cp,
                "migration_id": sg_pmeta.get("migration_id"),
                "project_info": sg_pmeta,
            })

        # 6. Elastic IPs
        eip_resp = ec2.describe_addresses()
        elastic_ips: List[Dict[str, Any]] = []
        for addr in eip_resp.get("Addresses", []):
            pub = addr.get("PublicIp", "")
            iid = addr.get("InstanceId", "")
            is_cp = (pub and pub in cp_meta.get("protected_ips", set())) or iid in control_plane_instance_ids
            att_inst = instance_by_id.get(iid)
            eip_pmeta = (
                att_inst["project_info"]
                if att_inst and att_inst.get("project_info")
                else _build_project_meta(None, is_cp=is_cp)
            )
            elastic_ips.append({
                "public_ip": pub,
                "allocation_id": addr.get("AllocationId", ""),
                "instance_id": iid,
                "instance_name": instance_name_by_id.get(iid, iid),
                "is_control_plane": is_cp,
                "project_info": eip_pmeta,
            })

        # 7. Group visible resources (hiding underlying CloudMove control-plane host)
        projects_map: Dict[str, Dict[str, Any]] = {}

        def _ensure_proj_bucket(pmeta: Dict[str, Any]) -> Dict[str, Any]:
            pid = pmeta.get("project_id") or "unassigned"
            if pid not in projects_map:
                projects_map[pid] = {
                    **pmeta,
                    "instances": [],
                    "volumes": [],
                    "vpcs": [],
                    "security_groups": [],
                    "elastic_ips": [],
                    "total_ebs_gb": 0,
                    "total_resources_count": 0,
                }
            return projects_map[pid]

        visible_instances = [i for i in instances if not i.get("is_control_plane")]
        visible_volumes = [v for v in volumes if not v.get("is_control_plane")]
        visible_vpcs = [vp for vp in vpcs if not vp.get("is_control_plane") and not vp.get("is_default")]
        visible_sgs = [sg for sg in security_groups if not sg.get("is_control_plane") and not sg.get("is_default")]
        visible_eips = [eip for eip in elastic_ips if not eip.get("is_control_plane")]
        visible_ebs_gb = sum(v["size_gb"] for v in visible_volumes)

        for inst in visible_instances:
            if inst["state"] == "terminated":
                continue
            b = _ensure_proj_bucket(inst["project_info"])
            b["instances"].append(inst)
            b["total_resources_count"] += 1

        for v in visible_volumes:
            b = _ensure_proj_bucket(v["project_info"])
            b["volumes"].append(v)
            b["total_ebs_gb"] += v["size_gb"]
            b["total_resources_count"] += 1

        for vp in visible_vpcs:
            b = _ensure_proj_bucket(vp["project_info"])
            b["vpcs"].append(vp)
            b["total_resources_count"] += 1 + len(vp.get("subnets") or []) + len(vp.get("internet_gateways") or [])

        for sg in visible_sgs:
            b = _ensure_proj_bucket(sg["project_info"])
            b["security_groups"].append(sg)
            b["total_resources_count"] += 1

        for eip in visible_eips:
            b = _ensure_proj_bucket(eip["project_info"])
            b["elastic_ips"].append(eip)
            b["total_resources_count"] += 1

        projects_deployed = [p for p in projects_map.values() if not p.get("is_control_plane")]
        projects_deployed.sort(key=lambda p: (len(p.get("instances", [])) == 0, p.get("project_name", "")))
        running_instances = [i for i in visible_instances if i["state"] == "running"]

        return {
            "authenticated": True,
            "account_id": account_id,
            "caller_arn": caller_arn,
            "region": region,
            "audited_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "summary": {
                "running_instances_count": len(running_instances),
                "total_instances_count": len(visible_instances),
                "total_volumes_count": len(visible_volumes),
                "total_ebs_gb": visible_ebs_gb,
                "academy_ebs_limit_gb": 150,
                "total_vpcs_count": len(visible_vpcs),
                "custom_vpcs_count": len(visible_vpcs),
                "active_workspaces_count": sum(1 for w in workspaces if w["resource_count"] > 0),
                "projects_count": len(projects_deployed),
            },
            "ip_sync_events": ip_sync_events,
            "projects_deployed": projects_deployed,
            "instances": visible_instances,
            "volumes": visible_volumes,
            "vpcs": visible_vpcs,
            "security_groups": visible_sgs,
            "elastic_ips": visible_eips,
            "workspaces": workspaces,
        }
    except Exception as exc:
        err_str = str(exc)
        if "voc-cancel-cred" in err_str:
            err_str = (
                "Sesión de AWS Academy detenida (policy/voc-cancel-cred). "
                "Inicia el laboratorio ('Start Lab') en AWS Academy y actualiza tus credenciales."
            )
        return {
            "authenticated": False,
            "error": f"Error consultando recursos AWS EC2: {err_str}",
            "workspaces": workspaces,
            "instances": [],
            "volumes": [],
            "vpcs": [],
            "security_groups": [],
            "elastic_ips": [],
        }


def delete_aws_audit_resource(
    *,
    resolve_job_dir_fn: Callable[[str], Path],
    inspect_tfstate_fn: Callable[[Path], Dict[str, Any]],
    save_status_meta_fn: Callable[[str, Path, Dict[str, Any]], None],
    build_env_fn: Callable[[Optional[Dict[str, str]]], Dict[str, str]],
    resource_type: str,
    resource_id: str,
    credentials: Optional[Dict[str, str]] = None,
    cleanup_vpc: bool = True,
) -> Dict[str, Any]:
    """
    Safely terminate or delete an AWS resource or Terraform workspace discovered
    during audit while protecting the primary CloudMove control plane.
    """
    clean_type = (resource_type or "").strip().lower()
    clean_id = (resource_id or "").strip()
    if not clean_type or not clean_id:
        return {"success": False, "error": "Debe especificar resource_type y resource_id."}

    cp_meta = get_control_plane_metadata()
    protected_ids = (
        set(cp_meta.get("protected_instance_ids") or set())
        | set(cp_meta.get("protected_vpc_ids") or set())
        | set(cp_meta.get("protected_ips") or set())
        | {"deploy/aws", "cloudmove-control-plane"}
    )
    if clean_id in protected_ids:
        return {
            "success": False,
            "error": f"El recurso '{clean_id}' está protegido por políticas de seguridad de la plataforma.",
        }

    try:
        validate_safe_id(clean_id, label="resource_id")
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    try:
        session, region = create_boto3_session(build_env_fn, credentials)
        ec2 = session.client("ec2", region_name=region, config=boto_config(read_timeout=15))
    except Exception as exc:
        return {"success": False, "error": f"Error de autenticación AWS: {str(exc)}"}

    def _delete_vpc_and_dependencies(vpc_id: str) -> List[str]:
        actions_log: List[str] = []
        try:
            vp_info = ec2.describe_vpcs(VpcIds=[vpc_id]).get("Vpcs", [])
            if vp_info and vp_info[0].get("IsDefault"):
                actions_log.append(f"VPC {vpc_id} es la VPC por defecto (protegida).")
                return actions_log
        except Exception:
            return actions_log

        try:
            inst_res = ec2.describe_instances(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
            iids = []
            for r in inst_res.get("Reservations", []):
                for i in r.get("Instances", []):
                    if (i.get("State") or {}).get("Name") in ("terminated",):
                        continue
                    itags = {t["Key"]: t["Value"] for t in (i.get("Tags") or []) if "Key" in t}
                    if (
                        i["InstanceId"] in protected_ids
                        or itags.get("Name") == "cloudmove-server"
                        or itags.get("Project") == "CloudMove-Capstone"
                    ):
                        continue
                    iids.append(i["InstanceId"])
            if iids:
                ec2.terminate_instances(InstanceIds=iids)
                actions_log.append(f"Instancias terminadas: {', '.join(iids)}")
                for _ in range(18):
                    chk = ec2.describe_instances(InstanceIds=iids)
                    states = [
                        (inst.get("State") or {}).get("Name")
                        for r in chk.get("Reservations", [])
                        for inst in r.get("Instances", [])
                    ]
                    if all(s == "terminated" for s in states):
                        break
                    time.sleep(2.0)
        except Exception as e:
            actions_log.append(f"Aviso instancias en {vpc_id}: {str(e)}")

        try:
            igws = ec2.describe_internet_gateways(Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]).get("InternetGateways", [])
            for igw in igws:
                igw_id = igw["InternetGatewayId"]
                ec2.detach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
                ec2.delete_internet_gateway(InternetGatewayId=igw_id)
                actions_log.append(f"Internet Gateway eliminado: {igw_id}")
        except Exception as e:
            actions_log.append(f"Aviso IGW: {str(e)}")

        try:
            subs = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]).get("Subnets", [])
            for sub in subs:
                sid = sub["SubnetId"]
                ec2.delete_subnet(SubnetId=sid)
                actions_log.append(f"Subnet eliminada: {sid}")
        except Exception as e:
            actions_log.append(f"Aviso Subnets: {str(e)}")

        try:
            rts = ec2.describe_route_tables(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]).get("RouteTables", [])
            for rt in rts:
                assocs = rt.get("Associations") or []
                if any(a.get("Main") for a in assocs):
                    continue
                for a in assocs:
                    if a.get("RouteTableAssociationId"):
                        try:
                            ec2.disassociate_route_table(AssociationId=a["RouteTableAssociationId"])
                        except Exception:
                            pass
                rt_id = rt["RouteTableId"]
                ec2.delete_route_table(RouteTableId=rt_id)
                actions_log.append(f"Route Table eliminada: {rt_id}")
        except Exception as e:
            actions_log.append(f"Aviso Route Tables: {str(e)}")

        try:
            sgs = ec2.describe_security_groups(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]).get("SecurityGroups", [])
            for sg in sgs:
                sg_id = sg["GroupId"]
                try:
                    if sg.get("IpPermissions"):
                        ec2.revoke_security_group_ingress(GroupId=sg_id, IpPermissions=sg["IpPermissions"])
                except Exception:
                    pass
                try:
                    if sg.get("IpPermissionsEgress"):
                        ec2.revoke_security_group_egress(GroupId=sg_id, IpPermissions=sg["IpPermissionsEgress"])
                except Exception:
                    pass
            for sg in sgs:
                if sg.get("GroupName") == "default":
                    continue
                sg_id = sg["GroupId"]
                ec2.delete_security_group(GroupId=sg_id)
                actions_log.append(f"Security Group eliminado: {sg_id}")
        except Exception as e:
            actions_log.append(f"Aviso Security Groups: {str(e)}")

        try:
            nacls = ec2.describe_network_acls(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]).get("NetworkAcls", [])
            for nacl in nacls:
                if not nacl.get("IsDefault") and nacl.get("NetworkAclId"):
                    ec2.delete_network_acl(NetworkAclId=nacl["NetworkAclId"])
                    actions_log.append(f"Network ACL eliminada: {nacl['NetworkAclId']}")
        except Exception as e:
            actions_log.append(f"Aviso Network ACLs: {str(e)}")

        try:
            ec2.delete_vpc(VpcId=vpc_id)
            actions_log.append(f"VPC eliminada exitosamente: {vpc_id}")
        except Exception as e:
            actions_log.append(f"La VPC {vpc_id} quedó en proceso de liberación de interfaces de red ({str(e)}).")

        return actions_log

    try:
        if clean_type == "ec2_instance":
            inst_desc = ec2.describe_instances(InstanceIds=[clean_id]).get("Reservations", [])
            vpc_id = None
            for r in inst_desc:
                for i in r.get("Instances", []):
                    tags = {t["Key"]: t["Value"] for t in (i.get("Tags") or []) if "Key" in t}
                    if tags.get("Name") == "cloudmove-server":
                        return {"success": False, "error": "Instancia principal cloudmove-server protegida."}
                    vpc_id = i.get("VpcId")

            ec2.terminate_instances(InstanceIds=[clean_id])
            details = [f"Instancia EC2 {clean_id} enviada a terminación (su volumen raíz EBS se eliminará automáticamente)."]
            if cleanup_vpc and vpc_id:
                vp_info = ec2.describe_vpcs(VpcIds=[vpc_id]).get("Vpcs", [])
                if vp_info and not vp_info[0].get("IsDefault"):
                    other_insts = ec2.describe_instances(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]).get("Reservations", [])
                    active_others = [
                        i["InstanceId"]
                        for r in other_insts
                        for i in r.get("Instances", [])
                        if i["InstanceId"] != clean_id and (i.get("State") or {}).get("Name") not in ("terminated", "shutting-down")
                    ]
                    if not active_others:
                        details.extend(_delete_vpc_and_dependencies(vpc_id))
            return {"success": True, "resource_type": clean_type, "resource_id": clean_id, "details": details}

        elif clean_type == "start_instance":
            ec2.start_instances(InstanceIds=[clean_id])
            return {
                "success": True,
                "resource_type": clean_type,
                "resource_id": clean_id,
                "details": [f"Instancia EC2 {clean_id} iniciándose en AWS."],
            }

        elif clean_type == "stop_instance":
            ec2.stop_instances(InstanceIds=[clean_id])
            return {
                "success": True,
                "resource_type": clean_type,
                "resource_id": clean_id,
                "details": [f"Instancia EC2 {clean_id} deteniéndose en AWS."],
            }

        elif clean_type == "ebs_volume":
            ec2.delete_volume(VolumeId=clean_id)
            return {
                "success": True,
                "resource_type": clean_type,
                "resource_id": clean_id,
                "details": [f"Volumen EBS {clean_id} eliminado exitosamente."],
            }

        elif clean_type == "vpc":
            details = _delete_vpc_and_dependencies(clean_id)
            return {"success": True, "resource_type": clean_type, "resource_id": clean_id, "details": details}

        elif clean_type == "security_group":
            ec2.delete_security_group(GroupId=clean_id)
            return {
                "success": True,
                "resource_type": clean_type,
                "resource_id": clean_id,
                "details": [f"Security Group {clean_id} eliminado exitosamente."],
            }

        elif clean_type == "terraform_workspace":
            safe_ws_id = validate_safe_id(clean_id, label="workspace_id")
            job_dir = resolve_job_dir_fn(safe_ws_id)
            st = inspect_tfstate_fn(job_dir)
            details = []
            vpc_ids_to_clean = set()
            for mr in st.get("managed_resources", []):
                if (
                    mr.get("type") == "aws_instance"
                    and mr.get("id")
                    and mr["id"] not in protected_ids
                    and (mr.get("tags") or {}).get("Name") != "cloudmove-server"
                ):
                    try:
                        ec2.terminate_instances(InstanceIds=[mr["id"]])
                        details.append(f"Instancia {mr['id']} terminada.")
                    except Exception:
                        pass
                elif mr.get("type") == "aws_vpc" and mr.get("id"):
                    vpc_ids_to_clean.add(mr["id"])

            for vid in vpc_ids_to_clean:
                details.extend(_delete_vpc_and_dependencies(vid))

            tfstate_path = job_dir / "terraform.tfstate"
            if tfstate_path.is_file():
                try:
                    raw = json.loads(tfstate_path.read_text(encoding="utf-8"))
                    raw["resources"] = []
                    raw["outputs"] = {}
                    tfstate_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
                    details.append(f"Estado local terraform.tfstate de '{clean_id}' limpiado (0 recursos activos).")
                except Exception:
                    pass

            save_status_meta_fn(clean_id, job_dir, {
                "status": "IDLE",
                "stage": "DESTROYED_BY_AUDIT",
                "active_command": None,
                "is_running": False,
                "message": "Recursos del workspace eliminados desde la Auditoría Cloud.",
                "error": None,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            return {
                "success": True,
                "resource_type": clean_type,
                "resource_id": clean_id,
                "details": details or [f"Workspace {clean_id} limpiado."],
            }

        else:
            return {"success": False, "error": f"Tipo de recurso '{clean_type}' no soportado."}
    except Exception as exc:
        return {"success": False, "error": f"Error eliminando {clean_type} '{clean_id}': {str(exc)}"}
