"""Maximum closure through a minimum cut using NetworkX preflow-push.

Positive blocks connect from the source; negative blocks connect to the
sink. A block-to-predecessor arc has capacity greater than all finite
benefit, so an optimal cut cannot violate precedence. NetworkX is BSD-3-Clause.
The optimum applies to the supplied values and discrete graph, not to
geotechnical safety or optimal production scheduling.
"""
from __future__ import annotations

import networkx as nx
import numpy as np
from networkx.algorithms.flow import preflow_push

SOURCE, SINK = "__source__", "__sink__"


def solve_max_closure(values: np.ndarray, arcs: np.ndarray) -> np.ndarray:
    """Return the maximum-value closed set, up to floating-point tolerance.

    Ties may select different blocks with the same total value. Empty,
    all-positive, all-negative and zero-valued inputs are supported.
    """
    values = np.asarray(values, dtype=float)
    arcs = np.asarray(arcs, dtype=np.int64).reshape(-1, 2)
    if values.ndim != 1 or not np.isfinite(values).all():
        raise ValueError("block values must be a finite one-dimensional array")
    if arcs.size and (arcs.min() < 0 or arcs.max() >= len(values)):
        raise ValueError("precedence indices must refer to existing blocks")
    if not len(values):
        return np.zeros(0, dtype=bool)
    total = float(np.abs(values).sum())
    if not np.isfinite(total):
        raise ValueError("total block value exceeds floating-point range")
    big_cap = total + max(1.0, total * 1e-12)
    graph = nx.DiGraph()
    graph.add_nodes_from([SOURCE, SINK])
    graph.add_nodes_from(range(len(values)))
    graph.add_edges_from((SOURCE, int(i), {"cap": float(values[i])}) for i in np.flatnonzero(values > 0))
    graph.add_edges_from((int(i), SINK, {"cap": float(-values[i])}) for i in np.flatnonzero(values < 0))
    graph.add_edges_from((int(b), int(p), {"cap": big_cap}) for b, p in arcs)
    _, (source_side, _) = nx.minimum_cut(graph, SOURCE, SINK, capacity="cap", flow_func=preflow_push)
    in_pit = np.zeros(len(values), dtype=bool)
    for node in source_side:
        if isinstance(node, (int, np.integer)):
            in_pit[node] = True
    return in_pit
