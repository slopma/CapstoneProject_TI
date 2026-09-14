import networkx as nx


def resolve_dependencies(
    graph,
    selected_resources
):

    resolved = set(
        selected_resources
    )


    for resource in selected_resources:

        if resource not in graph:
            continue


        dependencies = nx.descendants(
            graph,
            resource
        )


        resolved.update(
            dependencies
        )


    return sorted(resolved)