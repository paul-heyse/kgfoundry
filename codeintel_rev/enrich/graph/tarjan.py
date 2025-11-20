"""Tarjan SCC computation utilities."""

from __future__ import annotations

from collections.abc import Mapping


def tarjan_scc(edges: Mapping[str, set[str]]) -> dict[str, int]:
    """Return a component id mapping for the provided adjacency list.

    Parameters
    ----------
    edges : Mapping[str, set[str]]
        Adjacency list mapping each node to its set of outgoing neighbors.

    Returns
    -------
    dict[str, int]
        Mapping from node to its strongly connected component identifier.
    """
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    components: dict[str, int] = {}
    component_id = 0

    def strongconnect(node: str) -> None:
        """Compute strongly connected component for a node using Tarjan's algorithm.

        Parameters
        ----------
        node : str
            Node identifier to compute SCC for. The function recursively
            processes neighbors and assigns component IDs.

        Notes
        -----
        This is a nested function implementing Tarjan's SCC algorithm. It
        maintains indices, lowlink values, and a stack to identify strongly
        connected components. Nodes are assigned component IDs when a root
        of an SCC is found.
        """
        nonlocal index, component_id
        indices[node] = index
        lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for neighbor in edges.get(node, set()):
            if neighbor not in indices:
                strongconnect(neighbor)
                lowlink[node] = min(lowlink[node], lowlink[neighbor])
            elif neighbor in on_stack:
                lowlink[node] = min(lowlink[node], indices[neighbor])

        if lowlink[node] == indices[node]:
            while True:
                member = stack.pop()
                on_stack.remove(member)
                components[member] = component_id
                if member == node:
                    break
            component_id += 1

    for node in edges:
        if node not in indices:
            strongconnect(node)
    return components
