"""Decode polygon loops and positions from editable Source 2 VMAP DMX graphs.

This module extracts native CMapMesh / CDmePolygonMesh data. It does not yet create
VMF brushes: brush suitability, convexity, winding, texture projection, and transform
conventions must be validated before that step.
"""
from __future__ import annotations

from typing import Any


def _ref_index(value: Any) -> int | None:
    if isinstance(value, dict) and isinstance(value.get("element_index"), int):
        return value["element_index"]
    return None


def _stream_data(elements: list[dict], array_ref: Any, semantic: str) -> list | None:
    array_index = _ref_index(array_ref)
    if array_index is None or not 0 <= array_index < len(elements):
        return None
    array_attrs = elements[array_index].get("attributes", {})
    for stream_ref in array_attrs.get("streams", []):
        stream_index = _ref_index(stream_ref)
        if stream_index is None or not 0 <= stream_index < len(elements):
            continue
        stream = elements[stream_index]
        attrs = stream.get("attributes", {})
        if attrs.get("semanticName") == semantic or attrs.get("standardAttributeName") == semantic:
            data = attrs.get("data")
            if isinstance(data, list):
                return data
    return None


def _int_array(attrs: dict, key: str) -> list[int] | None:
    value = attrs.get(key)
    if isinstance(value, list) and all(isinstance(v, int) for v in value):
        return value
    return None


def decode_polygon_mesh(elements: list[dict], node_index: int) -> dict:
    """Decode one CMapMesh into local-space positions and ordered polygon loops."""
    if not 0 <= node_index < len(elements):
        raise ValueError(f"Element index {node_index} is out of range.")
    node = elements[node_index]
    if node.get("type") != "CMapMesh":
        raise ValueError(f"Element {node_index} is {node.get('type')!r}, not CMapMesh.")

    node_attrs = node.get("attributes", {})
    mesh_index = _ref_index(node_attrs.get("meshData"))
    if mesh_index is None or not 0 <= mesh_index < len(elements):
        raise ValueError(f"CMapMesh element {node_index} has an unresolved meshData reference.")
    mesh = elements[mesh_index]
    attrs = mesh.get("attributes", {})
    positions = _stream_data(elements, attrs.get("vertexData"), "position")
    edge_vertices = _int_array(attrs, "edgeVertexIndices")
    edge_next = _int_array(attrs, "edgeNextIndices")
    edge_faces = _int_array(attrs, "edgeFaceIndices")
    face_edges = _int_array(attrs, "faceEdgeIndices")
    if positions is None:
        raise ValueError(f"Mesh element {mesh_index} has no readable position stream.")
    if not edge_vertices or not edge_next or not face_edges:
        raise ValueError(f"Mesh element {mesh_index} is missing required topology arrays.")
    if len(edge_next) != len(edge_vertices):
        raise ValueError(
            f"Mesh element {mesh_index}: edgeNextIndices length {len(edge_next)} "
            f"does not match edgeVertexIndices length {len(edge_vertices)}."
        )

    points: list[list[float]] = []
    for i, p in enumerate(positions):
        if not isinstance(p, (list, tuple)) or len(p) < 3:
            raise ValueError(f"Position {i} is not a 3-component vector.")
        points.append([float(p[0]), float(p[1]), float(p[2])])

    loops: list[dict] = []
    for face_index, start in enumerate(face_edges):
        if not 0 <= start < len(edge_next):
            loops.append({"face_index": face_index, "valid": False, "error": "start edge out of range"})
            continue
        visited: list[int] = []
        current = start
        closed = False
        for _ in range(len(edge_next) + 1):
            if current == start and visited:
                closed = True
                break
            if not 0 <= current < len(edge_next):
                break
            if current in visited:
                break
            visited.append(current)
            next_edge = edge_next[current]
            if edge_faces is not None and current < len(edge_faces) and edge_faces[current] != face_index:
                # Record the mismatch rather than silently accepting a cross-face cycle.
                pass
            current = next_edge
        vertex_ids = [edge_vertices[e] for e in visited]
        valid_ids = all(0 <= v < len(points) for v in vertex_ids)
        valid = closed and len(vertex_ids) >= 3 and valid_ids and len(set(vertex_ids)) >= 3
        loops.append({
            "face_index": face_index,
            "edge_indices": visited,
            "vertex_indices": vertex_ids,
            "closed": closed,
            "valid": valid,
            **({"error": "loop did not close, had fewer than three distinct vertices, or referenced an invalid vertex"}
               if not valid else {}),
        })

    return {
        "node_index": node_index,
        "node_guid": node.get("guid"),
        "meshdata_index": mesh_index,
        "origin": node_attrs.get("origin", [0, 0, 0]),
        "angles": node_attrs.get("angles", [0, 0, 0]),
        "scales": node_attrs.get("scales", [1, 1, 1]),
        "materials": attrs.get("materials", []),
        "positions_local": points,
        "faces": loops,
        "valid_face_count": sum(1 for f in loops if f["valid"]),
        "invalid_face_count": sum(1 for f in loops if not f["valid"]),
        "vmf_brush_ready": False,
        "note": "Decoded polygon loops are not proof that the mesh is a closed convex solid suitable for a VMF brush.",
    }
