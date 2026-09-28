from typing import Dict, Any, List
from app.adapters.base import BaseProviderAdapter
from app.cmir.models import CMIR, CMIRNode


class KubernetesAdapter(BaseProviderAdapter):
    @property
    def provider_name(self) -> str:
        return "kubernetes"

    def translate_node(self, node: CMIRNode) -> Dict[str, Any]:
        node_type = node.type.lower()
        if node_type in ("kubernetes_namespace", "namespace"):
            k8s_kind = "Namespace"
        elif node_type in ("service", "application", "workload", "compute"):
            k8s_kind = "Deployment"
        elif node_type in ("database", "cache"):
            k8s_kind = "StatefulSet"
        elif node_type == "load_balancer":
            k8s_kind = "Ingress"
        elif node_type == "secret":
            k8s_kind = "Secret"
        elif node_type == "configuration":
            k8s_kind = "ConfigMap"
        else:
            k8s_kind = "Service"

        safe_name = node.name.lower().replace(" ", "-").replace("_", "-")

        return {
            "id": node.id,
            "name": node.name,
            "safe_name": safe_name,
            "cmir_type": node.type,
            "kind": k8s_kind,
            "namespace": node.metadata.get("namespace", "default"),
            "environment": node.environment or "production",
            "metadata": node.metadata,
        }

    def translate_cmir(self, cmir: CMIR) -> List[Dict[str, Any]]:
        return [self.translate_node(node) for node in cmir.resources]
