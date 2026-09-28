from typing import Dict, Any, List
from app.adapters.base import BaseProviderAdapter
from app.cmir.models import CMIR, CMIRNode

AZURE_RESOURCE_MAP = {
    "compute": "azurerm_linux_virtual_machine",
    "workload": "azurerm_linux_virtual_machine",
    "service": "azurerm_linux_virtual_machine",
    "application": "azurerm_app_service",
    "database": "azurerm_postgresql_server",
    "cache": "azurerm_redis_cache",
    "storage": "azurerm_storage_account",
    "network": "azurerm_virtual_network",
    "vpc": "azurerm_virtual_network",
    "subnet": "azurerm_subnet",
    "security_boundary": "azurerm_network_security_group",
    "cluster": "azurerm_kubernetes_cluster",
    "kubernetes_cluster": "azurerm_kubernetes_cluster",
    "load_balancer": "azurerm_lb",
}


class AzureAdapter(BaseProviderAdapter):
    @property
    def provider_name(self) -> str:
        return "azure"

    def translate_node(self, node: CMIRNode) -> Dict[str, Any]:
        target_type = AZURE_RESOURCE_MAP.get(node.type.lower(), "azurerm_linux_virtual_machine")
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
            "location": node.location or "eastus",
            "environment": node.environment or "production",
            "metadata": node.metadata,
        }

    def translate_cmir(self, cmir: CMIR) -> List[Dict[str, Any]]:
        return [self.translate_node(node) for node in cmir.resources]
