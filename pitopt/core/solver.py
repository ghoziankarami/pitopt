"""Maximum closure through a minimum cut.

Positive blocks connect from the source; negative blocks connect to the
sink. A block-to-predecessor arc has capacity greater than all finite
benefit, so an optimal cut cannot violate precedence.

By default, the graph is built as a vectorized 64-bit integer CSR matrix
and solved with SciPy's C/Cython Dinic max-flow (`scipy_dinic`), with
`edmonds_karp` and NetworkX `preflow_push` available as explicit backends.
The optimum applies to the supplied values and discrete graph, not to
geotechnical safety or optimal production scheduling.
"""
from __future__ import annotations

import networkx as nx
import numpy as np
from networkx.algorithms.flow import preflow_push
from scipy import sparse
from scipy.sparse.csgraph import breadth_first_order, maximum_flow

SOURCE, SINK = "__source__", "__sink__"
_TARGET_INT_TOTAL = float(1 << 29)
_VALID_METHODS = ("scipy_dinic", "edmonds_karp", "preflow_push")


def _solve_scipy(values: np.ndarray, arcs: np.ndarray, total: float, scipy_method: str) -> np.ndarray:
    """Solve max-closure using a vectorized CSR graph and SciPy csgraph.maximum_flow."""
    scale = _TARGET_INT_TOTAL / total
    v = np.round(values * scale).astype(np.int64)
    pos = np.flatnonzero(v > 0)
    if not len(pos):
        return np.zeros(len(values), dtype=bool)
    neg = np.flatnonzero(v < 0)
    big_cap = int(np.abs(v).sum()) + 1

    n = len(values)
    src, snk = n, n + 1
    rows = np.concatenate([np.full(len(pos), src, dtype=np.int64), neg, arcs[:, 0]])
    cols = np.concatenate([pos, np.full(len(neg), snk, dtype=np.int64), arcs[:, 1]])
    caps = np.concatenate([v[pos], -v[neg], np.full(len(arcs), big_cap, dtype=np.int64)])

    graph = sparse.csr_matrix((caps, (rows, cols)), shape=(n + 2, n + 2), dtype=np.int64)
    result = maximum_flow(graph, src, snk, method=scipy_method)
    residual = (graph - result.flow) > 0
    reachable = breadth_first_order(residual, src, directed=True, return_predecessors=False)

    in_pit = np.zeros(n, dtype=bool)
    in_pit[reachable[reachable < n]] = True
    return in_pit


def _solve_networkx(values: np.ndarray, arcs: np.ndarray, total: float) -> np.ndarray:
    """Solve max-closure using NetworkX preflow-push."""
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


def solve_max_closure(values: np.ndarray, arcs: np.ndarray, method: str = "scipy_dinic") -> np.ndarray:
    """Return the maximum-value closed set, up to floating-point tolerance.

    Ties may select different blocks with the same total value. Empty,
    all-positive, all-negative and zero-valued inputs are supported.
    `method` selects the max-flow backend: `'scipy_dinic'` (default),
    `'edmonds_karp'`, or `'preflow_push'`.
    """
    if method not in _VALID_METHODS:
        raise ValueError(f"unknown solver method {method!r}; expected one of {_VALID_METHODS}")
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
    if total == 0.0 or not np.any(values > 0):
        return np.zeros(len(values), dtype=bool)
    if method == "preflow_push":
        return _solve_networkx(values, arcs, total)
    scipy_method = "dinic" if method == "scipy_dinic" else "edmonds_karp"
    return _solve_scipy(values, arcs, total, scipy_method)
