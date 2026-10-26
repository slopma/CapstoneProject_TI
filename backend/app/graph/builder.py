import networkx as nx
from app.cmir.models import CMIR


def build_graph(cmir: CMIR) -> nx.DiGraph:
    graph = nx.DiGraph()

    for resource in cmir.resources:
        graph.add_node(
            resource.id,
            id=resource.id,
            canonical_id=resource.canonical_id or resource.id,
            name=resource.name,
            type=resource.type,
            category=resource.category,
            parent_id=resource.parent_id,
            children_ids=resource.children_ids,
            level=resource.level,
            provider=resource.provider,
            platform=resource.platform,
            engine=resource.engine,
            location=resource.location,
            environment=resource.environment,
            status=resource.status,
            is_shared=resource.is_shared,
            epistemic_state=resource.epistemic_state,
            confidence=resource.confidence,
            source_connector=resource.source_connector,
            discovered_at=resource.discovered_at,
            evidence=[e.model_dump() if hasattr(e, "model_dump") else e for e in resource.evidence] if resource.evidence else [],
            target_mapping=(
                resource.target_mapping.model_dump()
                if hasattr(resource.target_mapping, "model_dump")
                else resource.target_mapping
            ),
            security=resource.security,
            network=resource.network,
            metadata=resource.metadata,
        )

        # Add structural hierarchy edge from parent to child
        if resource.parent_id:
            graph.add_edge(
                resource.parent_id,
                resource.id,
                type="contains",
                is_hierarchy=True,
                epistemic_state=resource.epistemic_state,
                confidence=resource.confidence,
            )

    for relationship in cmir.relationships:
        graph.add_edge(
            relationship.source,
            relationship.target,
            id=relationship.id,
            type=relationship.type,
            is_hierarchy=(relationship.type in ("contains", "parent_of", "hosts")),
            epistemic_state=relationship.epistemic_state,
            confidence=relationship.confidence,
            source_connector=relationship.source_connector,
            discovered_at=relationship.discovered_at,
            evidence=[e.model_dump() for e in relationship.evidence] if relationship.evidence else [],
            metadata=relationship.metadata,
        )

    return graph