import networkx as nx
from app.cmir.models import CMIR


def build_graph(cmir: CMIR) -> nx.DiGraph:
    graph = nx.DiGraph()

    for resource in cmir.resources:
        graph.add_node(
            resource.id,
            id=resource.id,
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
            )

    for relationship in cmir.relationships:
        graph.add_edge(
            relationship.source,
            relationship.target,
            type=relationship.type,
            is_hierarchy=(relationship.type in ("contains", "parent_of")),
            metadata=relationship.metadata,
        )

    return graph