"""Decode native polygon topology from editable binary-DMX VMAP mesh nodes.

This decoder targets the explicit CMapMesh -> CDmePolygonMesh topology references used
by editable VMAP. It deliberately fails closed when a position stream or edge loop is
ambiguous; no coordinates are fabricated.
"""
from __future__ import annotations
import math
from pathlib import Path
from typing import Any
from .dmx_binary import DMXError, parse_binary_v9


class MeshDecodeError(ValueError):
    pass


def _ref(value: Any) -> int | None:
    if isinstance(value, dict) and isinstance(value.get("element_index"), int):
        return value["element_index"]
    return None


def _element(graph: dict, value: Any, label: str) -> dict:
    index = _ref(value)
    elements = graph["elements"]
    if index is None or index < 0 or index >= len(elements):
        raise MeshDecodeError(f"{label} is not a valid DMX element reference")
    return elements[index]


def _numeric_vec3_array(value: Any) -> list[list[float]] | None:
    if not isinstance(value, list) or not value:
        return None
    out = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            return None
        try:
            v = [float(item[0]), float(item[1]), float(item[2])]
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(n) for n in v):
            return None
        out.append(v)
    return out


def _find_position_stream(graph: dict, vertex_data_ref: Any) -> list[list[float]]:
    _element(graph, vertex_data_ref, "vertexData")
    elements = graph["elements"]
    visited = set()
    candidates = []

    def walk(value: Any, path: str, depth: int = 0):
        if depth > 8:
            return
        if isinstance(value, dict) and "element_index" in value:
            index = _ref(value)
            if index is None or index in visited or not (0 <= index < len(elements)):
                return
            visited.add(index)
            e = elements[index]
            attrs = e.get("attributes", {})
            semantic = str(attrs.get("semantic", attrs.get("name", ""))).lower()
            for key, child in attrs.items():
                if key.lower() in ("data", "values", "positions", "position"):
                    vectors = _numeric_vec3_array(child)
                    if vectors:
                        candidates.append((1 if "position" in semantic or key.lower() in ("positions", "position") else 0, vectors, f"{path}/{e.get('type')}[{key}]"))
                walk(child, f"{path}/{e.get('type')}[{key}]", depth + 1)
        elif isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}/{key}", depth + 1)
        elif isinstance(value, list):
            vectors = _numeric_vec3_array(value)
            if vectors:
                candidates.append((1 if "position" in path.lower() else 0, vectors, path))
            else:
                for i, child in enumerate(value):
                    walk(child, f"{path}[{i}]", depth + 1)

    walk({"element_index": _ref(vertex_data_ref)}, "vertexData")
    if not candidates:
        raise MeshDecodeError("No numeric vec3 position stream found beneath vertexData")
    candidates.sort(key=lambda c: (c[0], len(c[1])), reverse=True)
    best = candidates[0]
    tied = [c for c in candidates if c[0] == best[0] and len(c[1]) == len(best[1])]
    if len({str(c[1]) for c in tied}) > 1:
        raise MeshDecodeError("Multiple equally ranked vec3 streams found; position stream is ambiguous")
    return best[1]


def _int_array(attrs: dict, key: str) -> list[int]:
    value = attrs.get(key)
    if not isinstance(value, list):
        raise MeshDecodeError(f"Polygon mesh attribute {key!r} is missing or not an array")
    try:
        return [int(v) for v in value]
    except (TypeError, ValueError) as exc:
        raise MeshDecodeError(f"Polygon mesh attribute {key!r} contains non-integer values") from exc


def _walk_faces(edge_vertices: list[int], edge_next: list[int], face_edges: list[int]) -> list[list[int]]:
    if len(edge_vertices) != len(edge_next):
        raise MeshDecodeError("edgeVertexIndices and edgeNextIndices lengths differ")
    count = len(edge_next)
    faces = []
    for fi, start in enumerate(face_edges):
        if not (0 <= start < count):
            raise MeshDecodeError(f"Face {fi} starts at invalid edge {start}")
        loop, edge, visited = [], start, set()
        while edge not in visited:
            if not (0 <= edge < count):
                raise MeshDecodeError(f"Face {fi} edge loop points to invalid edge {edge}")
            visited.add(edge)
            loop.append(edge_vertices[edge])
            edge = edge_next[edge]
            if len(visited) > count:
                raise MeshDecodeError(f"Face {fi} edge loop exceeded edge count")
        if edge != start:
            raise MeshDecodeError(f"Face {fi} edge loop enters a different cycle")
        if len(loop) < 3:
            raise MeshDecodeError(f"Face {fi} has fewer than three edges")
        faces.append(loop)
    return faces


def decode_polygon_mesh(graph: dict, cmapmesh_element_index: int) -> dict:
    elements = graph.get("elements", [])
    if not isinstance(cmapmesh_element_index, int) or not (0 <= cmapmesh_element_index < len(elements)):
        raise MeshDecodeError(f"CMapMesh element index out of range: {cmapmesh_element_index}")
    node = elements[cmapmesh_element_index]
    if node.get("type") != "CMapMesh":
        raise MeshDecodeError(f"Element {cmapmesh_element_index} is {node.get('type')!r}, not CMapMesh")
    attrs = node.get("attributes", {})
    mesh_ref = attrs.get("meshData")
    mesh_element = _element(graph, mesh_ref, "meshData")
    mesh_attrs = mesh_element.get("attributes", {})
    positions = _find_position_stream(graph, mesh_attrs.get("vertexData"))
    edge_vertices = _int_array(mesh_attrs, "edgeVertexIndices")
    edge_next = _int_array(mesh_attrs, "edgeNextIndices")
    face_edges = _int_array(mesh_attrs, "faceEdgeIndices")
    faces = _walk_faces(edge_vertices, edge_next, face_edges)
    for fi, face in enumerate(faces):
        if any(i < 0 or i >= len(positions) for i in face):
            raise MeshDecodeError(f"Face {fi} references a vertex outside position stream ({len(positions)} vertices)")
    result = {
        "source_file": graph.get("source_file"),
        "cmapmesh_element_index": cmapmesh_element_index,
        "cmapmesh_guid": node.get("guid"),
        "transform": {"origin": attrs.get("origin", [0,0,0]), "angles": attrs.get("angles", [0,0,0]), "scales": attrs.get("scales", attrs.get("scale", [1,1,1]))},
        "origin": attrs.get("origin", [0,0,0]),
        "angles": attrs.get("angles", [0,0,0]),
        "scales": attrs.get("scales", attrs.get("scale", [1,1,1])),
        "meshData_index": _ref(mesh_ref),
        "meshData_class": mesh_element.get("type"),
        "materials": mesh_attrs.get("materials", []),
        "positions_local": positions,
        "face_loops": faces,
        "counts": {"vertices": len(positions), "faces": len(faces), "edges": len(edge_next)},
        "vmf_brush_ready": False,
    }
    return result


def decode_vmap_mesh(vmap_path: str | Path, cmapmesh_element_index: int) -> dict:
    graph = parse_binary_v9(vmap_path, include_binary=False)
    graph["source_file"] = str(vmap_path)
    return decode_polygon_mesh(graph, cmapmesh_element_index)
