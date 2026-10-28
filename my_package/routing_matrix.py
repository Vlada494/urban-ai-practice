"""Compatibility adapter for BlocksNet 1.0.0a9 / IduEdu 0.4.1 matrices.

Importing this module never downloads data or runs the homework calculation.
"""
import networkx as nx
import numpy as np


def prepare_matrix_graph(graph):
    """Align node IDs with CSR row order and keep the fastest parallel edge.

    IduEdu 0.4.1 uses a nearest node's ID directly as a CSR row number.
    IDs must therefore be 0..N-1 in iteration order, after component selection.
    Its MultiDiGraph conversion also keeps an arbitrary parallel edge, so choose
    the minimum time explicitly. Coordinates, direction and connectivity stay
    the same; the original graph and published Overture IDs are preserved.
    """
    if not graph.is_directed() or len(graph) < 2:
        raise ValueError('Для матрицы нужен ориентированный дорожный граф.')
    if not nx.is_strongly_connected(graph):
        raise ValueError('Перед расчётом нужна проверка связности дорожной сети.')
    indices = {node: i for i, node in enumerate(graph)}
    result = nx.DiGraph(**graph.graph)
    result.add_nodes_from((indices[node], dict(data)) for node, data in graph.nodes(data=True))
    for u, v, data in graph.edges(data=True):
        minutes = float(data['time_min'])
        if not np.isfinite(minutes) or minutes <= 0:
            raise ValueError('В дорожной сети есть некорректное время ребра.')
        a, b = indices[u], indices[v]
        if not result.has_edge(a, b) or minutes < result[a][b]['time_min']:
            attributes = dict(data)
            attributes['time_min'] = minutes
            result.add_edge(a, b, **attributes)
    assert list(result) == list(range(len(result)))
    return result


def calculate_drive_matrix(blocks, graph, dtype=np.float32, max_workers=2):
    """Calculate with BlocksNet, then add both straight-line approaches.

    The old IduEdu helper adds approaches only when road time is positive.
    Add them explicitly here so different blocks sharing one road node also
    get their approach time. The same-block diagonal remains zero.
    """
    from blocksnet.relations import calculate_accessibility_matrix
    from iduedu.modules.matrix.matrix_builder import get_closest_nodes

    prepared = prepare_matrix_graph(graph)
    matrix = calculate_accessibility_matrix(
        blocks[['geometry']].copy(), prepared, dtype=dtype,
        max_workers=max_workers, add_dist_tofrom_node=False)
    points = blocks[['geometry']].copy().to_crs(prepared.graph['crs'])
    points.geometry = points.representative_point()
    _, distances = get_closest_nodes(points, prepared)
    approaches = np.asarray(distances / (5000 / 60), dtype=dtype)
    values = matrix.to_numpy(copy=True)
    values += approaches[:, None] + approaches[None, :]
    np.fill_diagonal(values, 0)
    matrix.iloc[:, :] = values
    return matrix
