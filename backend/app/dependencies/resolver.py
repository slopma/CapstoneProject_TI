def resolve_dependencies(graph, selected_resources):

    resolved = set(selected_resources)

    for resource in selected_resources:

        if resource not in graph:
            continue

        dependencies = graph.successors(resource)

        for dependency in dependencies:
            resolved.add(dependency)

    return sorted(resolved)