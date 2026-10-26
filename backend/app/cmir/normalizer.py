from typing import Dict, Any
from app.cmir.models import CMIR
from app.cmir.builder import build_hierarchical_cmir


SUPPORTED_CMIR_VERSIONS = ("1.0", "2.0", "2.1")


def migrate_cmir_schema(payload: Dict[str, Any], target_version: str = "2.1") -> Dict[str, Any]:
    """
    Upgrade a persisted CMIR or raw inventory dictionary from v1.0 / v2.0 to v2.1
    without losing existing nodes, relationships or metadata.
    """
    if not isinstance(payload, dict):
        raise ValueError("El documento CMIR debe ser un diccionario JSON válido.")

    arch = dict(payload.get("architecture") or {})
    source_version = str(payload.get("version") or arch.get("version") or "2.0")

    resources = []
    for raw_res in payload.get("resources", []):
        if not isinstance(raw_res, dict):
            continue
        res = dict(raw_res)
        res.setdefault("canonical_id", res.get("id"))
        res.setdefault("epistemic_state", (res.get("metadata") or {}).get("data_state", "observed"))
        res.setdefault("confidence", 1.0 if res["epistemic_state"] == "observed" else 0.75)
        res.setdefault("source_connector", (res.get("metadata") or {}).get("provenance", "inventory"))
        res.setdefault("target_mapping", {})
        resources.append(res)

    relationships = []
    for raw_rel in payload.get("relationships", []):
        if not isinstance(raw_rel, dict):
            continue
        rel = dict(raw_rel)
        rel_meta = rel.get("metadata") or {}
        nature = rel_meta.get("nature")
        if "epistemic_state" not in rel:
            if nature in ("inferred", "derived", "unknown", "observed"):
                rel["epistemic_state"] = nature
            elif rel.get("type") == "inferred_relation":
                rel["epistemic_state"] = "inferred"
            else:
                rel["epistemic_state"] = "observed"
        rel.setdefault("confidence", 1.0 if rel["epistemic_state"] == "observed" else 0.65)
        relationships.append(rel)

    meta = dict(payload.get("metadata") or arch.get("metadata") or {})
    if source_version != target_version:
        meta["migrated_from_version"] = source_version
        meta["schema_version"] = target_version

    arch["name"] = payload.get("name") or arch.get("name") or "default-architecture"
    arch["provider"] = payload.get("provider") or arch.get("provider") or "multi-cloud"
    arch["version"] = target_version
    arch["metadata"] = meta

    return {
        "name": arch["name"],
        "provider": arch["provider"],
        "version": target_version,
        "metadata": meta,
        "architecture": arch,
        "resources": resources,
        "relationships": relationships,
    }


def normalize_inventory(inventory: Dict[str, Any]) -> CMIR:
    migrated = migrate_cmir_schema(inventory, target_version="2.1")
    architecture = migrated["architecture"]
    resources_raw = migrated["resources"]
    relationships_raw = migrated["relationships"]

    return build_hierarchical_cmir(
        resources_data=resources_raw,
        relationships_data=relationships_raw,
        architecture_meta=architecture,
    )
