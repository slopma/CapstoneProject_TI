from typing import Dict, Any, List
from app.cmir.models import CMIR


def validate_cmir(cmir: CMIR) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    if not cmir.resources:
        errors.append("El modelo CMIR no contiene ningún recurso.")

    resource_ids = {resource.id for resource in cmir.resources}
    if len(resource_ids) != len(cmir.resources):
        errors.append("Existen IDs duplicados entre los recursos del CMIR.")

    inferred_nodes_count = 0
    unknown_nodes_count = 0

    for resource in cmir.resources:
        if resource.parent_id:
            if resource.parent_id not in resource_ids:
                errors.append(f"El nodo '{resource.id}' referencia a un parent_id inexistente '{resource.parent_id}'.")
            if resource.parent_id == resource.id:
                errors.append(f"El nodo '{resource.id}' se autoreferencia como su propio padre.")

        if resource.epistemic_state == "inferred":
            inferred_nodes_count += 1
        elif resource.epistemic_state in ("unknown", "unavailable"):
            unknown_nodes_count += 1

    inferred_relationships_count = 0
    for relationship in cmir.relationships:
        if relationship.source not in resource_ids:
            errors.append(f"La relación referencia un origen inexistente '{relationship.source}'.")
        if relationship.target not in resource_ids:
            errors.append(f"La relación referencia un destino inexistente '{relationship.target}'.")

        if relationship.epistemic_state == "inferred" or relationship.type == "inferred_relation":
            inferred_relationships_count += 1
            warnings.append(
                f"La relación '{relationship.source} -> {relationship.target}' ({relationship.type}) es inferida "
                f"y no debe tratarse como dependencia confirmada sin validación adicional."
            )

    # Check for shared resources warning
    for resource in cmir.resources:
        if resource.is_shared:
            warnings.append(f"El recurso '{resource.id}' está marcado como compartido por múltiples componentes.")

    is_valid = len(errors) == 0

    return {
        "valid": is_valid,
        "schema_version": cmir.version,
        "errors": errors,
        "warnings": warnings,
        "total_resources": len(cmir.resources),
        "total_relationships": len(cmir.relationships),
        "inferred_nodes_count": inferred_nodes_count,
        "unknown_nodes_count": unknown_nodes_count,
        "inferred_relationships_count": inferred_relationships_count,
    }
