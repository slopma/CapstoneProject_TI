import networkx as nx


def build_graph(cmir):

    graph = nx.DiGraph()

    for resource in cmir.resources:

        graph.add_node(
            resource.id,
            name=resource.name,
            type=resource.type
        )

    for relationship in cmir.relationships:

        graph.add_edge(
            relationship.source,
            relationship.target,
            type=relationship.type
        )

    return graph