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
        elif node_type in ("service", "application", "workload", "compute", "container"):
            k8s_kind = "Deployment"
        elif node_type in ("database", "cache"):
            k8s_kind = "StatefulSet"
        elif node_type in ("load_balancer", "ingress"):
            k8s_kind = "Ingress"
        elif node_type == "secret":
            k8s_kind = "Secret"
        elif node_type in ("configuration", "configmap"):
            k8s_kind = "ConfigMap"
        elif node_type in ("storage", "san_storage", "volume"):
            k8s_kind = "PersistentVolumeClaim"
        else:
            k8s_kind = "Service"

        safe_name = node.name.lower().replace(" ", "-").replace("_", "-")

        # Extract port and image metadata if present
        port = (node.network or {}).get("port") or (node.metadata or {}).get("port") or 80
        image = (node.metadata or {}).get("image") or (f"{safe_name}:latest" if node.engine else "nginx:alpine")

        return {
            "id": node.id,
            "name": node.name,
            "safe_name": safe_name,
            "cmir_type": node.type,
            "kind": k8s_kind,
            "engine": node.engine,
            "port": port,
            "image": image,
            "namespace": (node.metadata or {}).get("namespace", "default"),
            "environment": node.environment or "production",
            "metadata": node.metadata or {},
        }

    def translate_cmir(self, cmir: CMIR) -> List[Dict[str, Any]]:
        return [self.translate_node(node) for node in cmir.resources]

