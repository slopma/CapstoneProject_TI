from typing import Dict, Any, List
from app.adapters.base import BaseProviderAdapter
from app.cmir.models import CMIR, CMIRNode


AWS_RESOURCE_MAP = {
    "compute": "aws_instance",
    "workload": "aws_instance",
    "service": "aws_instance",
    "application": "aws_instance",
    "container": "aws_ecs_task_definition",
    "database": "aws_db_instance",
    "cache": "aws_elasticache_cluster",
    "storage": "aws_s3_bucket",
    "bucket": "aws_s3_bucket",
    "network": "aws_vpc",
    "vpc": "aws_vpc",
    "subnet": "aws_subnet",
    "security_boundary": "aws_security_group",
    "security_group": "aws_security_group",
    "cluster": "aws_eks_cluster",
    "kubernetes_cluster": "aws_eks_cluster",
    "kubernetes_namespace": "aws_eks_node_group",
    "namespace": "aws_eks_node_group",
    "load_balancer": "aws_lb",
    "queue": "aws_sqs_queue",
    "topic": "aws_sns_topic",
    "identity": "aws_iam_role",
    "secret": "aws_secretsmanager_secret",
}


class AWSAdapter(BaseProviderAdapter):
    @property
    def provider_name(self) -> str:
        return "aws"

    def translate_node(self, node: CMIRNode) -> Dict[str, Any]:
        target_type = AWS_RESOURCE_MAP.get(node.type.lower(), "aws_instance")

        safe_name = node.name.lower().replace(" ", "-").replace("_", "-")
        safe_id = node.id.lower().replace("-", "_").replace(".", "_")

        return {
            "id": node.id,
            "safe_id": safe_id,
            "name": node.name,
            "safe_name": safe_name,
            "cmir_type": node.type,
            "type": target_type,
            "engine": node.engine,
            "platform": node.platform,
            "location": node.location or "us-east-1",
            "environment": node.environment or "production",
            "security": node.security,
            "network": node.network,
            "metadata": node.metadata,
        }

    def translate_cmir(self, cmir: CMIR) -> List[Dict[str, Any]]:
        return [self.translate_node(node) for node in cmir.resources]
