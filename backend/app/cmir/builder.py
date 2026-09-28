from typing import List, Dict, Any
from app.cmir.models import CMIR, CMIRNode, CMIRRelationship


TYPE_LEVEL_MAP = {
    "cloud": 0,
    "provider": 1,
    "region": 2,
    "datacenter": 2,
    "network": 3,
    "vpc": 3,
    "subnet": 3,
    "security_boundary": 3,
    "security_group": 3,
    "cluster": 4,
    "kubernetes_cluster": 4,
    "namespace": 5,
    "kubernetes_namespace": 5,
    "application": 6,
    "service": 7,
    "workload": 7,
    "compute": 8,
    "container": 8,
    "database": 8,
    "cache": 8,
    "storage": 8,
    "load_balancer": 8,
    "queue": 8,
    "topic": 8,
    "identity": 8,
    "secret": 8,
}


def build_hierarchical_cmir(
    resources_data: List[Dict[str, Any]],
    relationships_data: List[Dict[str, Any]],
    architecture_meta: Dict[str, Any],
) -> CMIR:
    node_map: Dict[str, CMIRNode] = {}

    for item in resources_data:
        node_id = item["id"]
        node_type = item.get("type", "workload").lower()
        level = item.get("level", TYPE_LEVEL_MAP.get(node_type, 8))

        node = CMIRNode(
            id=node_id,
            name=item.get("name", node_id),
            type=node_type,
            category=item.get("category", "resource"),
            parent_id=item.get("parent_id"),
            children_ids=item.get("children_ids", []),
            level=level,
            provider=item.get("provider", architecture_meta.get("provider", "aws")),
            platform=item.get("platform"),
            engine=item.get("engine"),
            location=item.get("location", "us-east-1"),
            environment=item.get("environment", "production"),
            status=item.get("status", "DISCOVERED"),
            is_shared=item.get("is_shared", False),
            security=item.get("security", {}),
            network=item.get("network", {}),
            metadata=item.get("metadata", {}),
        )
        node_map[node_id] = node

    # Process explicit 'contains' or parent-child relationships
    relationships: List[CMIRRelationship] = []
    for rel in relationships_data:
        rel_obj = CMIRRelationship(
            source=rel["source"],
            target=rel["target"],
            type=rel.get("type", "depends_on"),
            metadata=rel.get("metadata", {}),
        )
        relationships.append(rel_obj)

        if rel_obj.type in ("contains", "parent_of"):
            parent_id = rel_obj.source
            child_id = rel_obj.target
            if child_id in node_map and not node_map[child_id].parent_id:
                node_map[child_id].parent_id = parent_id

    # Sync children_ids based on parent_id
    for n_id, node in node_map.items():
        if node.parent_id and node.parent_id in node_map:
            parent_node = node_map[node.parent_id]
            if n_id not in parent_node.children_ids:
                parent_node.children_ids.append(n_id)

    return CMIR(
        name=architecture_meta.get("name", "cloudmove-architecture"),
        provider=architecture_meta.get("provider", "multi-cloud"),
        version=architecture_meta.get("version", "2.0"),
        resources=list(node_map.values()),
        relationships=relationships,
        metadata=architecture_meta.get("metadata", {}),
    )
