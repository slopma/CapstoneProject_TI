import os
import shutil
from typing import Dict, Any, List, Optional
from app.adapters.base import BaseProviderAdapter
from app.cmir.models import CMIR, CMIRNode
from app.generators.terraform import generate_aws_terraform_files, generate_aws_terraform


AWS_RESOURCE_MAP = {
    "datacenter": "aws_vpc",
    "physical_host": "aws_instance",
    "hypervisor": "aws_instance",
    "virtual_machine": "aws_instance",
    "vm": "aws_instance",
    "host": "aws_instance",
    "compute": "aws_instance",
    "workload": "aws_instance",
    "service": "aws_instance",
    "system_service": "in_guest_service",
    "process": "in_guest_process",
    "application": "aws_instance",
    "application_component": "aws_ecs_task_definition",
    "machine_image": "aws_ami",
    "disk_image": "aws_ebs_snapshot",
    "operating_system": "aws_ami_data_source",
    "os": "aws_ami_data_source",
    "container": "aws_ecs_task_definition",
    "database": "aws_db_instance",
    "database_instance": "aws_db_instance",
    "database_schema": "aws_db_instance",
    "cache": "aws_elasticache_cluster",
    "storage": "aws_s3_bucket",
    "file_share": "aws_efs_file_system",
    "shared_file": "aws_s3_bucket",
    "san_storage": "aws_ebs_volume",
    "volume": "aws_ebs_volume",
    "disk": "aws_ebs_volume",
    "block_device": "aws_ebs_volume",
    "partition": "aws_ebs_volume",
    "filesystem": "aws_ebs_volume",
    "bucket": "aws_s3_bucket",
    "network": "aws_vpc",
    "vpc": "aws_vpc",
    "subnet": "aws_subnet",
    "vlan": "aws_subnet",
    "network_interface": "aws_subnet",
    "security_boundary": "aws_security_group",
    "security_group": "aws_security_group",
    "firewall": "aws_security_group",
    "connectivity_rule": "aws_security_group_rule",
    "listening_port": "aws_security_group_rule",
    "port": "aws_security_group_rule",
    "network_connection": "aws_security_group_rule",
    "cluster": "aws_eks_cluster",
    "kubernetes_cluster": "aws_eks_cluster",
    "kubernetes_namespace": "aws_eks_node_group",
    "namespace": "aws_eks_node_group",
    "load_balancer": "aws_lb",
    "ingress": "aws_lb",
    "queue": "aws_sqs_queue",
    "topic": "aws_sns_topic",
    "identity": "aws_iam_role",
    "role": "aws_iam_role",
    "permission": "aws_iam_policy",
    "secret": "aws_secretsmanager_secret",
}

VALID_AWS_REGIONS = {
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "eu-west-1", "eu-west-2", "eu-central-1",
    "sa-east-1", "ap-southeast-1", "ap-northeast-1",
}


class AWSAdapter(BaseProviderAdapter):
    @property
    def provider_name(self) -> str:
        return "aws"

    def translate_node(self, node: CMIRNode) -> Dict[str, Any]:
        node_type_lower = node.type.lower()
        target_type = AWS_RESOURCE_MAP.get(node_type_lower, "aws_instance")

        safe_name = node.name.lower().replace(" ", "-").replace("_", "-").replace("/", "-")
        safe_id = node.id.lower().replace("-", "_").replace(".", "_").replace(":", "_").replace("/", "_")

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
            "location": node.location if node.location in VALID_AWS_REGIONS else "us-east-1",
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
        region = cfg.get("region") or cfg.get("aws_region") or "us-east-1"
        cfg["region"] = region
        if region not in VALID_AWS_REGIONS:
            warnings.append(f"La región AWS '{region}' no está en el catálogo estándar; verifique disponibilidad.")
        vpc_cidr = cfg.get("vpc_cidr", "10.0.0.0/16")
        cfg["vpc_cidr"] = vpc_cidr
        return {
            "provider": "aws",
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "normalized_config": cfg,
            "capabilities": {
                "compute": ["EC2 (aws_instance)", "ECS Fargate/EC2", "EKS"],
                "vm_image_import": ["AWS VM Import/Export (aws ec2 import-image)", "AWS Application Migration Service (MGN)"],
                "storage": ["Amazon EBS (gp3/io2)", "Amazon S3", "Amazon EFS"],
                "database": ["Amazon RDS (PostgreSQL/MySQL)", "Amazon ElastiCache (Redis)", "Amazon MQ (RabbitMQ)"],
                "SupportedImageFormats": ["RAW", "VHD", "VHDX", "VMDK", "OVA"],
                "RequiresConversionFor": ["QCOW2 -> RAW o VMDK mediante qemu-img convert"],
            },
        }

    def check_permissions_and_prerequisites(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        cfg = config or {}
        has_aws_env = bool(
            (os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"))
            or (cfg.get("aws_access_key_id") and cfg.get("aws_secret_access_key"))
        )
        aws_cli = shutil.which("aws") is not None
        terraform_cli = shutil.which("terraform") is not None
        live_verified = (bool(cfg.get("live_credentials_verified")) or has_aws_env) and not cfg.get("dry_run", False)
        return {
            "provider": "aws",
            "live_credentials_verified": live_verified,
            "aws_env_vars_detected": has_aws_env,
            "aws_cli_installed": aws_cli,
            "terraform_cli_installed": terraform_cli,
            "execution_mode": "live_cloud" if live_verified else "simulated_dry_run",
            "required_permissions": [
                "ec2:ImportImage",
                "ec2:DescribeImportImageTasks",
                "ec2:RunInstances",
                "ec2:CreateVolume",
                "ec2:CreateVpc",
                "ec2:CreateSecurityGroup",
                "s3:CreateBucket",
                "s3:PutObject",
                "rds:CreateDBInstance",
                "iam:PassRole",
            ],
            "vmimport_role_required": "vmimport (IAM Role con trust policy para vmie.amazonaws.com)",
            "prerequisites_met": True,
            "notes": [
                "Para importar imágenes de VM reales en AWS se requiere un bucket S3 de staging y el rol IAM 'vmimport'.",
                "Terraform aprovisiona la infraestructura (VPC, EC2, EBS, RDS, S3), pero la copia de bloques e importación de imágenes se ejecuta vía AWS VM Import/Export o AWS MGN.",
            ],
        }

    def generate_iac(self, cmir: CMIR, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        translated = self.translate_cmir(cmir)
        files = generate_aws_terraform_files(translated)
        code = generate_aws_terraform(translated)
        validation = self.validate_artifacts(files)
        return {
            "provider": "aws",
            "translated_resources": translated,
            "files": files,
            "iac_code": code,
            "validation": validation,
        }
