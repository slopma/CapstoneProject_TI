from typing import Dict, Any
from app.cmir.models import CMIR
from app.cmir.builder import build_hierarchical_cmir


def normalize_inventory(inventory: Dict[str, Any]) -> CMIR:
    architecture = inventory.get("architecture", {
        "name": "default-architecture",
        "provider": "multi-cloud"
    })
    resources_raw = inventory.get("resources", [])
    relationships_raw = inventory.get("relationships", [])

    return build_hierarchical_cmir(
        resources_data=resources_raw,
        relationships_data=relationships_raw,
        architecture_meta=architecture
    )