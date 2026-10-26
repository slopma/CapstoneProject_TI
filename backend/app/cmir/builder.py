from typing import List, Dict, Any
from app.cmir.models import CMIR, CMIRNode, CMIRRelationship, CMIREvidence


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
    "connectivity_rule": 3,
    "cluster": 4,
    "kubernetes_cluster": 4,
    "physical_host": 4,
    "hypervisor": 4,
    "namespace": 5,
    "kubernetes_namespace": 5,
    "virtual_machine": 5,
    "vm": 5,
    "machine_image": 5,
    "disk_image": 5,
    "operating_system": 5,
    "application": 6,
    "application_component": 7,
    "service": 7,
    "workload": 7,
    "system_service": 7,
    "compute": 8,
    "container": 8,
    "database": 8,
    "database_instance": 8,
    "database_schema": 8,
    "cache": 8,
    "storage": 8,
    "volume": 8,
    "disk": 8,
    "file_share": 8,
    "shared_file": 8,
    "load_balancer": 8,
    "queue": 8,
    "topic": 8,
    "identity": 8,
    "permission": 8,
    "secret": 8,
    "port": 8,
    "network_connection": 8,
    "target_aws_resource": 8,
    "target_gcp_resource": 8,
    # Discovery & Host-level semantic types (CMIR v2.0 / v2.1 compatible)
    "host": 1,
    "discovery_group": 2,
    "network_interface": 3,
    "route": 3,
    "gateway": 3,
    "os": 4,
    "firmware": 4,
    "hardware_component": 5,
    "cpu": 5,
    "memory": 5,
    "block_device": 5,
    "partition": 6,
    "filesystem": 6,
    "package_group": 6,
    "systemd_service": 7,
    "kernel_module": 7,
    "process": 7,
    "listening_port": 8,
    "remote_endpoint": 8,
}


def _normalize_evidence_list(raw_evidence: Any, default_source: str, default_state: str, default_ts: str | None) -> List[CMIREvidence]:
    if isinstance(raw_evidence, list):
        items: List[CMIREvidence] = []
        for entry in raw_evidence:
            if isinstance(entry, CMIREvidence):
                items.append(entry)
            elif isinstance(entry, dict):
                items.append(
                    CMIREvidence(
                        source=str(entry.get("source") or default_source),
                        observed_at=entry.get("observed_at") or default_ts,
                        epistemic_state=str(entry.get("epistemic_state") or default_state),
                        confidence=float(entry.get("confidence", 1.0)),
                        detail=entry.get("detail"),
                        raw_reference=entry.get("raw_reference"),
                    )
                )
            elif isinstance(entry, str) and entry.strip():
                items.append(
                    CMIREvidence(
                        source=default_source,
                        observed_at=default_ts,
                        epistemic_state=default_state,
                        confidence=1.0 if default_state == "observed" else 0.75,
                        detail=entry.strip(),
                    )
                )
        return items
    if isinstance(raw_evidence, str) and raw_evidence.strip():
        return [
            CMIREvidence(
                source=default_source,
                observed_at=default_ts,
                epistemic_state=default_state,
                confidence=1.0 if default_state == "observed" else 0.75,
                detail=raw_evidence.strip(),
            )
        ]
    return []


def build_hierarchical_cmir(
    resources_data: List[Dict[str, Any]],
    relationships_data: List[Dict[str, Any]],
    architecture_meta: Dict[str, Any],
) -> CMIR:
    node_map: Dict[str, CMIRNode] = {}
    default_provider = architecture_meta.get("provider", "aws")
    default_source = architecture_meta.get("source_connector", "inventory")
    default_ts = architecture_meta.get("discovered_at")

    for item in resources_data:
        node_id = item["id"]
        node_type = item.get("type", "workload").lower()
        level = item.get("level", TYPE_LEVEL_MAP.get(node_type, 8))
        meta = item.get("metadata", {}) or {}
        epistemic_state = (
            item.get("epistemic_state")
            or meta.get("data_state")
            or meta.get("epistemic_state")
            or "observed"
        )
        source_conn = item.get("source_connector") or meta.get("provenance") or default_source
        disc_at = item.get("discovered_at") or meta.get("observed_at") or default_ts
        default_conf = 1.0 if epistemic_state == "observed" else (0.85 if epistemic_state == "derived" else (0.6 if epistemic_state == "inferred" else 0.3))
        confidence = float(item.get("confidence", meta.get("confidence", default_conf)))

        evidence_list = _normalize_evidence_list(
            item.get("evidence") or meta.get("evidence"),
            default_source=str(source_conn),
            default_state=str(epistemic_state),
            default_ts=disc_at,
        )

        node = CMIRNode(
            id=node_id,
            name=item.get("name", node_id),
            type=node_type,
            category=item.get("category", "resource"),
            parent_id=item.get("parent_id"),
            children_ids=list(item.get("children_ids", [])),
            level=level,
            provider=item.get("provider", default_provider),
            platform=item.get("platform"),
            engine=item.get("engine"),
            location=item.get("location", "us-east-1"),
            environment=item.get("environment", "production"),
            status=item.get("status", "DISCOVERED"),
            is_shared=item.get("is_shared", False),
            security=item.get("security", {}),
            network=item.get("network", {}),
            metadata=meta,
            canonical_id=item.get("canonical_id") or meta.get("canonical_id") or node_id,
            epistemic_state=str(epistemic_state),
            confidence=confidence,
            source_connector=str(source_conn) if source_conn else None,
            discovered_at=disc_at,
            evidence=evidence_list,
            target_mapping=item.get("target_mapping", {}),
        )
        node_map[node_id] = node

    # Process explicit 'contains', 'parent_of', or 'hosts' relationships
    relationships: List[CMIRRelationship] = []
    for rel in relationships_data:
        rel_meta = rel.get("metadata", {}) or {}
        rel_type = rel.get("type", "depends_on")
        nature = rel_meta.get("nature") or rel.get("epistemic_state")
        if nature in ("inferred", "derived", "unknown", "observed"):
            rel_state = nature
        elif rel_type in ("inferred_relation",):
            rel_state = "inferred"
        else:
            rel_state = "observed"

        rel_conf_default = 1.0 if rel_state == "observed" else (0.85 if rel_state == "derived" else (0.6 if rel_state == "inferred" else 0.3))
        rel_conf = float(rel.get("confidence", rel_meta.get("confidence", rel_conf_default)))
        rel_source_conn = rel.get("source_connector") or rel_meta.get("provenance") or default_source
        rel_disc_at = rel.get("discovered_at") or rel_meta.get("observed_at") or default_ts
        rel_evidence = _normalize_evidence_list(
            rel.get("evidence") or rel_meta.get("evidence"),
            default_source=str(rel_source_conn),
            default_state=str(rel_state),
            default_ts=rel_disc_at,
        )

        rel_obj = CMIRRelationship(
            source=rel["source"],
            target=rel["target"],
            type=rel_type,
            metadata=rel_meta,
            epistemic_state=str(rel_state),
            confidence=rel_conf,
            source_connector=str(rel_source_conn) if rel_source_conn else None,
            discovered_at=rel_disc_at,
            evidence=rel_evidence,
        )
        relationships.append(rel_obj)

        if rel_obj.type in ("contains", "parent_of", "hosts"):
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
        version=architecture_meta.get("version", "2.1"),
        resources=list(node_map.values()),
        relationships=relationships,
        metadata=architecture_meta.get("metadata", {}),
    )


def build_cmir_hierarchy(payload: Dict[str, Any]) -> CMIR:
    """Convenience wrapper building a hierarchical CMIR v2.1 from a single dictionary payload."""
    return build_hierarchical_cmir(
        resources_data=payload.get("resources", []),
        relationships_data=payload.get("relationships", []),
        architecture_meta={
            "name": payload.get("name", "cloudmove-architecture"),
            "provider": payload.get("provider", "aws"),
            "version": payload.get("version", "2.1"),
            "metadata": payload.get("metadata", {}),
        },
    )
