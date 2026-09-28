from typing import Dict, Any, List
from app.cmir.models import CMIR


def validate_migration_subgraph(
    selected_cmir: CMIR,
    dependency_analysis: Dict[str, Any],
    target_provider: str = "aws"
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    missing_requirements: List[str] = []

    resource_types = {res.type for res in selected_cmir.resources}
    unresolved = dependency_analysis.get("unresolved_dependencies", [])

    if unresolved:
        errors.append(f"Existen dependencias irresolutas que bloquean la migración: {', '.join(unresolved)}")
        missing_requirements.extend(unresolved)

    # Check for Network boundary requirement if compute or workload is present
    has_compute = any(r_type in ("compute", "container", "workload", "service", "database", "cache") for r_type in resource_types)
    has_network = any(r_type in ("network", "vpc", "subnet") for r_type in resource_types)

    if has_compute and not has_network:
        warnings.append("Se detectaron componentes de cómputo/base de datos pero no se incluyó una red explícita. Se autogenerará una VPC y Subred predeterminada.")

    # Check for shared resources warning
    shared_deps = dependency_analysis.get("shared_dependencies", [])
    if shared_deps:
        warnings.append(f"Atención: Los siguientes recursos son compartidos con otros sistemas no seleccionados: {', '.join(shared_deps)}. Verifique si debe clonarlos o mantener la conexión existente.")

    # Check for target provider compatibility
    for res in selected_cmir.resources:
        if res.provider and res.provider != target_provider and target_provider not in ("aws", "azure", "gcp", "kubernetes"):
            warnings.append(f"El recurso '{res.name}' proveniente de '{res.provider}' será traducido hacia '{target_provider}'.")

    can_generate = len(errors) == 0

    return {
        "valid": can_generate,
        "can_generate": can_generate,
        "errors": errors,
        "warnings": warnings,
        "missing_requirements": missing_requirements,
        "selected_count": len(selected_cmir.resources),
        "target_provider": target_provider,
    }
