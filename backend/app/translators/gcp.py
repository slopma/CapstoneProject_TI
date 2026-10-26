from typing import Dict, Any, List
from app.adapters.gcp_adapter import GCPAdapter, GCP_RESOURCE_MAP
from app.cmir.models import CMIR, CMIRNode

GCP_MAPPING = GCP_RESOURCE_MAP


def translate_resource(resource: CMIRNode) -> Dict[str, Any]:
    adapter = GCPAdapter()
    translated = adapter.translate_node(resource)
    translated["target_type"] = translated["type"]
    return translated


def translate_cmir_to_gcp(cmir: CMIR) -> List[Dict[str, Any]]:
    adapter = GCPAdapter()
    return adapter.translate_cmir(cmir)
