"""
Live Cloud Infrastructure Discovery & CMIR Normalization for AWS (Section 5.2).

Uses the official AWS SDK (`boto3` / `botocore`) to discover live AWS cloud
resources, paginate results, handle rate limits (`429` / `Throttling`) with exponential
backoff, propagate authentication/authorization errors (never disguising an API failure
as an empty successful inventory), normalize into CMIR v2.1 with deterministic IDs, and
reconcile against previous snapshots (`added`, `modified`, `removed`, `read_errors`).
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

import boto3
from botocore.config import Config as BotocoreConfig
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, PartialCredentialsError

from app.cmir.builder import build_cmir_hierarchy
from app.cmir.models import CMIR, deterministic_node_id
from app.core.text_utils import utc_now_iso
from app.discovery.connectors import ConnectorAuthError, ConnectorError, ConnectorTimeoutError
from app.persistence.transactional_db import TransactionalDatabase, get_transactional_db


_utc_now = utc_now_iso


def _fingerprint_resource(res: Dict[str, Any]) -> str:
    relevant = {
        "type": res.get("type"),
        "name": res.get("name"),
        "location": res.get("location"),
        "engine": res.get("engine"),
        "platform": res.get("platform"),
        "metadata": res.get("metadata", {}),
    }
    raw = json.dumps(relevant, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class CloudInventoryReconciler:
    """
    Reconciles a newly discovered Cloud CMIR snapshot against the previous snapshot
    for the same `(provider, account_or_project)`, tracking `added`, `modified`,
    `removed`, `unchanged`, and `read_errors`.
    """

    @staticmethod
    def reconcile(
        current_resources: List[Dict[str, Any]],
        previous_snapshot: Optional[Dict[str, Any]],
        read_errors: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        prev_resources_list = ((previous_snapshot or {}).get("cmir") or {}).get("resources") or []
        prev_by_canonical: Dict[str, Dict[str, Any]] = {}
        for r in prev_resources_list:
            cid = r.get("canonical_id") or r.get("id")
            if cid:
                prev_by_canonical[cid] = r

        curr_by_canonical: Dict[str, Dict[str, Any]] = {}
        for r in current_resources:
            cid = r.get("canonical_id") or r.get("id")
            if cid:
                curr_by_canonical[cid] = r

        added: List[Dict[str, Any]] = []
        modified: List[Dict[str, Any]] = []
        unchanged: List[str] = []
        removed: List[Dict[str, Any]] = []

        for cid, curr_res in curr_by_canonical.items():
            if cid not in prev_by_canonical:
                added.append({"canonical_id": cid, "id": curr_res["id"], "type": curr_res["type"], "name": curr_res["name"]})
            else:
                prev_res = prev_by_canonical[cid]
                if _fingerprint_resource(curr_res) != _fingerprint_resource(prev_res):
                    modified.append({
                        "canonical_id": cid,
                        "id": curr_res["id"],
                        "type": curr_res["type"],
                        "name": curr_res["name"],
                        "previous_updated_at": prev_res.get("discovered_at"),
                        "current_updated_at": curr_res.get("discovered_at"),
                    })
                else:
                    unchanged.append(cid)

        # Only mark resources as removed if the corresponding service did not fail to read
        failed_scopes = {e.get("service") for e in read_errors if e.get("service")}
        for cid, prev_res in prev_by_canonical.items():
            if cid not in curr_by_canonical:
                svc = (prev_res.get("metadata") or {}).get("cloud_service")
                if svc and svc in failed_scopes:
                    continue
                removed.append({
                    "canonical_id": cid,
                    "id": prev_res.get("id"),
                    "type": prev_res.get("type"),
                    "name": prev_res.get("name"),
                })

        return {
            "previous_snapshot_id": (previous_snapshot or {}).get("snapshot_id"),
            "added_count": len(added),
            "modified_count": len(modified),
            "removed_count": len(removed),
            "unchanged_count": len(unchanged),
            "read_errors_count": len(read_errors),
            "added": added,
            "modified": modified,
            "removed": removed,
            "unchanged": unchanged,
            "read_errors": read_errors,
        }


class AWSLiveDiscoveryConnector:
    """
    Discovers live AWS infrastructure using `boto3` (`sts`, `ec2`, `rds`, `s3`, `iam`)
    with full pagination, exponential backoff on rate limits, strict authentication
    verification, and CMIR v2.1 normalization.
    """

    MIN_REQUIRED_PERMISSIONS = [
        "sts:GetCallerIdentity",
        "ec2:DescribeVpcs",
        "ec2:DescribeSubnets",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeInstances",
        "ec2:DescribeVolumes",
        "rds:DescribeDBInstances",
        "s3:ListAllMyBuckets",
        "iam:ListRoles",
    ]

    def __init__(
        self,
        region: str = "us-east-1",
        regions: Optional[List[str]] = None,
        profile_name: Optional[str] = None,
        role_arn: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        max_retries: int = 3,
        timeout_seconds: int = 10,
        boto3_session_factory: Optional[Callable[..., Any]] = None,
        db: Optional[TransactionalDatabase] = None,
    ) -> None:
        clean_regions = [str(r).strip() for r in (regions or []) if str(r).strip()]
        self.region = (region or (clean_regions[0] if clean_regions else "") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1").strip()
        self.regions = list(dict.fromkeys(clean_regions or [self.region]))
        self.profile_name = profile_name or os.getenv("AWS_PROFILE")
        self.role_arn = role_arn or os.getenv("AWS_ASSUME_ROLE_ARN")
        self.aws_access_key_id = (aws_access_key_id or "").strip() or None
        self.aws_secret_access_key = (aws_secret_access_key or "").strip() or None
        self.aws_session_token = (aws_session_token or "").strip() or None
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.boto3_session_factory = boto3_session_factory
        self.db = db or get_transactional_db()

    def _create_session(self) -> Any:
        if self.boto3_session_factory is not None:
            return self.boto3_session_factory(region_name=self.region, profile_name=self.profile_name)
        kwargs: Dict[str, Any] = {"region_name": self.region}
        if self.aws_access_key_id and self.aws_secret_access_key:
            kwargs["aws_access_key_id"] = self.aws_access_key_id
            kwargs["aws_secret_access_key"] = self.aws_secret_access_key
            if self.aws_session_token:
                kwargs["aws_session_token"] = self.aws_session_token
        elif self.profile_name:
            kwargs["profile_name"] = self.profile_name
        session = boto3.Session(**kwargs)
        if self.role_arn:
            sts = session.client("sts")
            assumed = sts.assume_role(RoleArn=self.role_arn, RoleSessionName="CloudMoveLiveDiscovery")
            creds = assumed["Credentials"]
            session = boto3.Session(
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"],
                region_name=self.region,
            )
        return session

    def _call_with_backoff(self, fn: Callable[[], Any], service_name: str, operation_name: str) -> Any:
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return fn()
            except (NoCredentialsError, PartialCredentialsError) as exc:
                raise ConnectorAuthError(
                    "AWS_MISSING_CREDENTIALS",
                    f"Credenciales AWS no encontradas o incompletas al invocar {service_name}:{operation_name}: {exc}",
                ) from exc
            except ClientError as exc:
                err_code = (exc.response.get("Error") or {}).get("Code", "ClientError")
                err_msg = (exc.response.get("Error") or {}).get("Message", str(exc))
                if err_code in ("AuthFailure", "InvalidClientTokenId", "SignatureDoesNotMatch", "ExpiredToken", "UnrecognizedClientException"):
                    raise ConnectorAuthError(
                        f"AWS_AUTH_{err_code.upper()}",
                        f"Autenticación AWS rechazada en {service_name}:{operation_name} ({err_code}): {err_msg}",
                    ) from exc
                if err_code in ("AccessDenied", "AccessDeniedException", "UnauthorizedOperation"):
                    raise ConnectorAuthError(
                        f"AWS_PERMISSION_DENIED",
                        f"Permisos IAM insuficientes para {service_name}:{operation_name} ({err_code}): {err_msg}",
                    ) from exc
                if err_code in ("Throttling", "ThrottlingException", "RequestLimitExceeded", "TooManyRequestsException"):
                    last_exc = exc
                    if attempt < self.max_retries:
                        time.sleep(0.05 * (2 ** (attempt - 1)))
                        continue
                    raise ConnectorError(
                        "AWS_RATE_LIMIT_EXCEEDED",
                        f"Límite de tasa excedido tras {self.max_retries} intentos en {service_name}:{operation_name}: {err_msg}",
                    ) from exc
                raise ConnectorError(f"AWS_{err_code}", f"Error AWS en {service_name}:{operation_name}: {err_msg}") from exc
            except TimeoutError as exc:
                raise ConnectorTimeoutError(f"Timeout consultando AWS {service_name}:{operation_name}: {exc}") from exc
            except BotoCoreError as exc:
                if "timed out" in str(exc).lower():
                    raise ConnectorTimeoutError(f"Timeout consultando AWS {service_name}:{operation_name}: {exc}") from exc
                raise ConnectorError("AWS_BOTOCORE_ERROR", f"Error de transporte AWS en {service_name}:{operation_name}: {exc}") from exc
        raise ConnectorError("AWS_RETRY_EXHAUSTED", f"Fallo tras reintentos en {service_name}:{operation_name}: {last_exc}")

    def _paginate_all(self, client: Any, operation: str, result_key: str, service_name: str, **kwargs: Any) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        if hasattr(client, "can_paginate") and client.can_paginate(operation):
            paginator = client.get_paginator(operation)

            def _fetch_pages() -> List[Dict[str, Any]]:
                collected: List[Dict[str, Any]] = []
                for page in paginator.paginate(**kwargs):
                    collected.extend(page.get(result_key) or [])
                return collected

            return self._call_with_backoff(_fetch_pages, service_name, operation)

        # Fallback to manual NextToken pagination
        next_token: Optional[str] = None
        while True:
            call_kwargs = dict(kwargs)
            if next_token:
                call_kwargs["NextToken"] = next_token
            method = getattr(client, operation)
            resp = self._call_with_backoff(lambda: method(**call_kwargs), service_name, operation)
            items.extend(resp.get(result_key) or [])
            next_token = resp.get("NextToken")
            if not next_token:
                break
        return items

    def discover_live_account(self) -> Dict[str, Any]:
        """
        Execute live AWS discovery. Never masks authentication failures as an empty inventory.
        Records partial service read errors (e.g. if `iam:ListRoles` is denied while EC2 is allowed)
        explicitly in `read_errors`.
        """
        now = _utc_now()
        session = self._create_session()
        boto_cfg = BotocoreConfig(
            connect_timeout=self.timeout_seconds,
            read_timeout=self.timeout_seconds,
            retries={"max_attempts": 1},
        )

        sts = session.client("sts", config=boto_cfg) if hasattr(session, "client") else None
        if sts is None:
            raise ConnectorAuthError("AWS_INVALID_SESSION", "No se pudo inicializar sesión boto3 válida.")

        # 1. Verify caller identity (mandatory; raises ConnectorAuthError if credentials are invalid/missing)
        identity = self._call_with_backoff(lambda: sts.get_caller_identity(), "sts", "GetCallerIdentity")
        account_id = str(identity.get("Account") or "unknown-account")
        caller_arn = str(identity.get("Arn") or "")

        s3 = session.client("s3", region_name=self.region, config=boto_cfg)
        iam = session.client("iam", region_name=self.region, config=boto_cfg)

        nodes: List[Dict[str, Any]] = []
        relationships: List[Dict[str, Any]] = []
        read_errors: List[Dict[str, Any]] = []

        for active_region in self.regions:
            ec2 = session.client("ec2", region_name=active_region, config=boto_cfg)
            rds = session.client("rds", region_name=active_region, config=boto_cfg)
            vpc_id_map: Dict[str, str] = {}
            subnet_id_map: Dict[str, str] = {}

            # 2. Discover VPCs
            try:
                vpcs = self._paginate_all(ec2, "describe_vpcs", "Vpcs", "ec2")
                for v in vpcs:
                    aws_vpc_id = v["VpcId"]
                    tags = {t["Key"]: t["Value"] for t in (v.get("Tags") or []) if "Key" in t and "Value" in t}
                    name = tags.get("Name") or aws_vpc_id
                    cid = f"aws:{account_id}:{active_region}:vpc:{aws_vpc_id}"
                    nid = deterministic_node_id("vpc", cid)
                    vpc_id_map[aws_vpc_id] = nid
                    nodes.append({
                        "id": nid,
                        "canonical_id": cid,
                        "name": name,
                        "type": "vpc",
                        "category": "network",
                        "provider": "aws",
                        "location": active_region,
                        "epistemic_state": "observed",
                        "confidence": 1.0,
                        "source_connector": "aws_boto3_live_discovery",
                        "discovered_at": now,
                        "evidence": [{
                            "source": f"aws:ec2:DescribeVpcs ({account_id}/{active_region})",
                            "observed_at": now,
                            "epistemic_state": "observed",
                            "confidence": 1.0,
                            "detail": f"VPC {aws_vpc_id} CIDR={v.get('CidrBlock')}",
                        }],
                        "metadata": {
                            "cloud_service": "ec2:vpc",
                            "aws_vpc_id": aws_vpc_id,
                            "cidr_block": v.get("CidrBlock"),
                            "is_default": v.get("IsDefault", False),
                            "tags": tags,
                        },
                    })
            except ConnectorError as exc:
                read_errors.append({"service": f"ec2:vpc:{active_region}", "code": exc.code, "message": exc.message, "timestamp": now})

            # 3. Discover Subnets
            try:
                subnets = self._paginate_all(ec2, "describe_subnets", "Subnets", "ec2")
                for s in subnets:
                    aws_sub_id = s["SubnetId"]
                    aws_vpc_id = s.get("VpcId", "")
                    tags = {t["Key"]: t["Value"] for t in (s.get("Tags") or []) if "Key" in t and "Value" in t}
                    name = tags.get("Name") or aws_sub_id
                    cid = f"aws:{account_id}:{active_region}:subnet:{aws_sub_id}"
                    nid = deterministic_node_id("subnet", cid)
                    subnet_id_map[aws_sub_id] = nid
                    parent_nid = vpc_id_map.get(aws_vpc_id)
                    nodes.append({
                        "id": nid,
                        "canonical_id": cid,
                        "name": name,
                        "type": "subnet",
                        "category": "network",
                        "parent_id": parent_nid,
                        "provider": "aws",
                        "location": s.get("AvailabilityZone", active_region),
                        "epistemic_state": "observed",
                        "confidence": 1.0,
                        "source_connector": "aws_boto3_live_discovery",
                        "discovered_at": now,
                        "metadata": {
                            "cloud_service": "ec2:subnet",
                            "aws_subnet_id": aws_sub_id,
                            "aws_vpc_id": aws_vpc_id,
                            "cidr_block": s.get("CidrBlock"),
                            "availability_zone": s.get("AvailabilityZone"),
                        },
                    })
            except ConnectorError as exc:
                read_errors.append({"service": f"ec2:subnet:{active_region}", "code": exc.code, "message": exc.message, "timestamp": now})

            # 4. Discover Security Groups
            sg_id_map: Dict[str, str] = {}
            try:
                sgs = self._paginate_all(ec2, "describe_security_groups", "SecurityGroups", "ec2")
                for sg in sgs:
                    aws_sg_id = sg["GroupId"]
                    cid = f"aws:{account_id}:{active_region}:sg:{aws_sg_id}"
                    nid = deterministic_node_id("security_group", cid)
                    sg_id_map[aws_sg_id] = nid
                    nodes.append({
                        "id": nid,
                        "canonical_id": cid,
                        "name": sg.get("GroupName") or aws_sg_id,
                        "type": "security_group",
                        "category": "security",
                        "parent_id": vpc_id_map.get(sg.get("VpcId", "")),
                        "provider": "aws",
                        "location": active_region,
                        "epistemic_state": "observed",
                        "confidence": 1.0,
                        "source_connector": "aws_boto3_live_discovery",
                        "discovered_at": now,
                        "metadata": {
                            "cloud_service": "ec2:security_group",
                            "aws_group_id": aws_sg_id,
                            "ingress_rules_count": len(sg.get("IpPermissions") or []),
                            "egress_rules_count": len(sg.get("IpPermissionsEgress") or []),
                        },
                    })
            except ConnectorError as exc:
                read_errors.append({"service": f"ec2:security_group:{active_region}", "code": exc.code, "message": exc.message, "timestamp": now})

            # 5. Discover EC2 Instances
            inst_id_map: Dict[str, str] = {}
            try:
                reservations = self._paginate_all(ec2, "describe_instances", "Reservations", "ec2")
                for resv in reservations:
                    for inst in resv.get("Instances") or []:
                        aws_inst_id = inst["InstanceId"]
                        tags = {t["Key"]: t["Value"] for t in (inst.get("Tags") or []) if "Key" in t and "Value" in t}
                        name = tags.get("Name") or aws_inst_id
                        cid = f"aws:{account_id}:{active_region}:instance:{aws_inst_id}"
                        nid = deterministic_node_id("virtual_machine", cid)
                        inst_id_map[aws_inst_id] = nid
                        parent_nid = subnet_id_map.get(inst.get("SubnetId", "")) or vpc_id_map.get(inst.get("VpcId", ""))
                        nodes.append({
                            "id": nid,
                            "canonical_id": cid,
                            "name": name,
                            "type": "virtual_machine",
                            "category": "compute",
                            "parent_id": parent_nid,
                            "provider": "aws",
                            "platform": inst.get("PlatformDetails") or "Linux/UNIX",
                            "location": active_region,
                            "epistemic_state": "observed",
                            "confidence": 1.0,
                            "source_connector": "aws_boto3_live_discovery",
                            "discovered_at": now,
                            "metadata": {
                                "cloud_service": "ec2:instance",
                                "aws_instance_id": aws_inst_id,
                                "instance_type": inst.get("InstanceType"),
                                "state": (inst.get("State") or {}).get("Name"),
                                "private_ip": inst.get("PrivateIpAddress"),
                                "public_ip": inst.get("PublicIpAddress"),
                                "architecture": inst.get("Architecture", "x86_64"),
                                "boot_mode": inst.get("BootMode", "uefi"),
                            },
                        })
                        for sg_ref in inst.get("SecurityGroups") or []:
                            sg_nid = sg_id_map.get(sg_ref.get("GroupId", ""))
                            if sg_nid:
                                relationships.append({
                                    "source": nid,
                                    "target": sg_nid,
                                    "type": "depends_on",
                                    "epistemic_state": "observed",
                                    "confidence": 1.0,
                                    "source_connector": "aws_boto3_live_discovery",
                                    "discovered_at": now,
                                })
            except ConnectorError as exc:
                read_errors.append({"service": f"ec2:instance:{active_region}", "code": exc.code, "message": exc.message, "timestamp": now})

            # 6. Discover EBS Volumes
            try:
                volumes = self._paginate_all(ec2, "describe_volumes", "Volumes", "ec2")
                for vol in volumes:
                    aws_vol_id = vol["VolumeId"]
                    cid = f"aws:{account_id}:{active_region}:volume:{aws_vol_id}"
                    nid = deterministic_node_id("volume", cid)
                    attachments = vol.get("Attachments") or []
                    attached_inst_id = attachments[0].get("InstanceId") if attachments else None
                    parent_nid = inst_id_map.get(attached_inst_id or "")
                    nodes.append({
                        "id": nid,
                        "canonical_id": cid,
                        "name": aws_vol_id,
                        "type": "volume",
                        "category": "storage",
                        "parent_id": parent_nid,
                        "provider": "aws",
                        "location": vol.get("AvailabilityZone", active_region),
                        "epistemic_state": "observed",
                        "confidence": 1.0,
                        "source_connector": "aws_boto3_live_discovery",
                        "discovered_at": now,
                        "metadata": {
                            "cloud_service": "ec2:volume",
                            "aws_volume_id": aws_vol_id,
                            "size_gib": vol.get("Size"),
                            "volume_type": vol.get("VolumeType", "gp3"),
                            "encrypted": vol.get("Encrypted", False),
                            "state": vol.get("State"),
                        },
                    })
                    if parent_nid:
                        relationships.append({
                            "source": parent_nid,
                            "target": nid,
                            "type": "mounts",
                            "epistemic_state": "observed",
                            "confidence": 1.0,
                            "source_connector": "aws_boto3_live_discovery",
                            "discovered_at": now,
                        })
            except ConnectorError as exc:
                read_errors.append({"service": f"ec2:volume:{active_region}", "code": exc.code, "message": exc.message, "timestamp": now})

            # 7. Discover RDS Databases
            try:
                dbs = self._paginate_all(rds, "describe_db_instances", "DBInstances", "rds")
                for db_inst in dbs:
                    db_id = db_inst["DBInstanceIdentifier"]
                    cid = f"aws:{account_id}:{active_region}:rds:{db_id}"
                    nid = deterministic_node_id("database_instance", cid)
                    nodes.append({
                        "id": nid,
                        "canonical_id": cid,
                        "name": db_id,
                        "type": "database_instance",
                        "category": "data",
                        "provider": "aws",
                        "engine": db_inst.get("Engine", "postgres"),
                        "location": active_region,
                        "epistemic_state": "observed",
                        "confidence": 1.0,
                        "source_connector": "aws_boto3_live_discovery",
                        "discovered_at": now,
                        "metadata": {
                            "cloud_service": "rds:db_instance",
                            "db_instance_class": db_inst.get("DBInstanceClass"),
                            "engine_version": db_inst.get("EngineVersion"),
                            "allocated_storage_gib": db_inst.get("AllocatedStorage"),
                            "multi_az": db_inst.get("MultiAZ", False),
                        },
                    })
            except ConnectorError as exc:
                read_errors.append({"service": f"rds:db_instance:{active_region}", "code": exc.code, "message": exc.message, "timestamp": now})

        # 8. Discover S3 Buckets
        try:
            s3_resp = self._call_with_backoff(lambda: s3.list_buckets(), "s3", "ListBuckets")
            for b in s3_resp.get("Buckets") or []:
                b_name = b["Name"]
                cid = f"aws:{account_id}:global:s3:{b_name}"
                nid = deterministic_node_id("storage", cid)
                nodes.append({
                    "id": nid,
                    "canonical_id": cid,
                    "name": b_name,
                    "type": "storage",
                    "category": "storage",
                    "provider": "aws",
                    "location": self.region,
                    "epistemic_state": "observed",
                    "confidence": 1.0,
                    "source_connector": "aws_boto3_live_discovery",
                    "discovered_at": now,
                    "metadata": {"cloud_service": "s3:bucket", "bucket_name": b_name},
                })
        except ConnectorError as exc:
            read_errors.append({"service": "s3:bucket", "code": exc.code, "message": exc.message, "timestamp": now})

        # 9. Discover IAM Roles
        try:
            roles = self._paginate_all(iam, "list_roles", "Roles", "iam")
            for r in roles[:50]:
                r_name = r["RoleName"]
                cid = f"aws:{account_id}:global:iam_role:{r_name}"
                nid = deterministic_node_id("identity", cid)
                nodes.append({
                    "id": nid,
                    "canonical_id": cid,
                    "name": r_name,
                    "type": "identity",
                    "category": "security",
                    "provider": "aws",
                    "location": "global",
                    "epistemic_state": "observed",
                    "confidence": 1.0,
                    "source_connector": "aws_boto3_live_discovery",
                    "discovered_at": now,
                    "metadata": {"cloud_service": "iam:role", "arn": r.get("Arn")},
                })
        except ConnectorError as exc:
            read_errors.append({"service": "iam:role", "code": exc.code, "message": exc.message, "timestamp": now})

        if not nodes and read_errors:
            raise ConnectorError(
                "AWS_ALL_SERVICES_FAILED",
                f"Falló la lectura de todos los servicios AWS consultados en {account_id}/{self.region}: {read_errors[0]['message']}",
            )

        cmir_obj = build_cmir_hierarchy({
            "name": f"AWS Live Discovery — Account {account_id} ({self.region})",
            "provider": "aws",
            "version": "2.1",
            "resources": nodes,
            "relationships": relationships,
            "metadata": {
                "discovery_mode": "live_cloud_api",
                "account_id": account_id,
                "caller_arn": caller_arn,
                "region": self.region,
                "regions": self.regions,
                "discovered_at": now,
            },
        })
        cmir_dict = cmir_obj.model_dump()

        prev_snap = self.db.get_latest_cloud_discovery_snapshot("aws", account_id)
        reconciliation = CloudInventoryReconciler.reconcile(cmir_dict["resources"], prev_snap, read_errors)

        snapshot = {
            "snapshot_id": f"snap-aws-{account_id}-{uuid.uuid4().hex[:8]}",
            "provider": "aws",
            "account_or_project": account_id,
            "caller_identity": caller_arn,
            "region": self.region,
            "regions": self.regions,
            "execution_mode": "live_cloud_api",
            "discovered_at": now,
            "resources_count": len(cmir_dict["resources"]),
            "cmir": cmir_dict,
            "reconciliation": reconciliation,
            "read_errors": read_errors,
        }
        self.db.save_cloud_discovery_snapshot(snapshot)
        return snapshot
