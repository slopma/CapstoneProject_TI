import networkx as nx


def select_subgraph(graph, selected_resources):

    nodes = set(selected_resources)

    for resource in selected_resources:

        if resource not in graph:
            continue

        dependencies = nx.descendants(
            graph,
            resource
        )

        nodes.update(dependencies)

    return graph.subgraph(nodes).copy()