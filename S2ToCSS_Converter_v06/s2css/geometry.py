"""Schema-aware decoder for editable VMAP CMapMesh / CDmePolygonMesh data.

This module intentionally decodes polygon topology and positions only. It does not
claim that a surface mesh is a valid closed Source 1 brush, and does not emit VMF.
"""
from __future__ import annotations

from typing import Any


class GeometryDecodeError(ValueError):
    """Raised when a polygon mesh graph is incomplete or internally inconsistent."""


def _element_ref(value: Any, elements: list[dict], label: str) -> dict:
    if not isinstance(value, dict) or "element_index" not in value:
        raise GeometryDecodeError(f"{label}: expected a DMX element reference")
    index = value["element_index"]
    if not isinstance(index, int) or index < 0 or index >= len(elements):
        raise GeometryDecodeError(f"{label}: invalid element index {index!r}")
    return elements[index]


def _attribute_element(owner: dict, attribute: str, elements: list[dict]) -> dict:
    return _element_ref(owner.get("attributes", {}).get(attribute), elements,
                        f"{owner.get('type', 'element')}.{attribute}")


def _int_list(value: Any, label: str) -> list[int]:
    if not isinstance(value, list) or any(not isinstance(v, int) for v in value):
        raise GeometryDecodeError(f"{label}: expected an integer array")
    return value


def _position_stream(mesh_data: dict, elements: list[dict]) -> list[list[float]]:
    vertex_data = _attribute_element(mesh_data, "vertexData", elements)
    streams = vertex_data.get("attributes", {}).get("streams", [])
    if not isinstance(streams, list):
        raise GeometryDecodeError("vertexData.streams: expected an element array")

    candidates = []
    for ref in streams:
        stream = _element_ref(ref, elements, "vertexData.streams[]")
        attrs = stream.get("attributes", {})
        names = (
            str(attrs.get("standardAttributeName", "")),
            str(attrs.get("semanticName", "")),
            str(stream.get("name", "")),
        )
        if any(n.split(":", 1)[0].strip().lower() == "position" for n in names):
            candidates.append((stream, attrs))

    if not candidates:
        raise GeometryDecodeError("No position stream found in mesh vertexData")
    stream, attrs = candidates[0]
    data = attrs.get("data")
    if not isinstance(data, list):
        raise GeometryDecodeError(f"Position stream {stream.get('name', '')!r} has no decoded array")
    positions = []
    for index, point in enumerate(data):
        if not isinstance(point, list) or len(point) < 3:
            raise GeometryDecodeError(f"Position stream item {index} is not a vector3")
        try:
            xyz = [float(point[0]), float(point[1]), float(point[2])]
        except (TypeError, ValueError) as exc:
            raise GeometryDecodeError(f"Position stream item {index} is not numeric") from exc
        positions.append(xyz)
    if not positions:
        raise GeometryDecodeError("Position stream is empty")
    return positions


def decode_polygon_mesh(mesh_data: dict, elements: list[dict]) -> dict:
    """Decode one CDmePolygonMesh element into local-space polygon coordinates.

    DMX graph references are expected in the generic parser's
    {"element_index": N} representation. Face loops are walked using
    faceEdgeIndices -> edgeNextIndices; each edge's first vertex index is
    mapped through vertexDataIndices into the position stream.
    """
    if mesh_data.get("type") != "CDmePolygonMesh":
        raise GeometryDecodeError(
            f"Expected CDmePolygonMesh, got {mesh_data.get('type')!r}"
        )
    attrs = mesh_data.get("attributes", {})
    positions = _position_stream(mesh_data, elements)

    vertex_data_indices = _int_list(attrs.get("vertexDataIndices"), "vertexDataIndices")
    edge_vertex_indices = _int_list(attrs.get("edgeVertexIndices"), "edgeVertexIndices")
    edge_next_indices = _int_list(attrs.get("edgeNextIndices"), "edgeNextIndices")
    face_edge_indices = _int_list(attrs.get("faceEdgeIndices"), "faceEdgeIndices")

    if len(edge_vertex_indices) % 2:
        raise GeometryDecodeError("edgeVertexIndices must contain pairs")
    edge_count = len(edge_vertex_indices) // 2
    if len(edge_next_indices) != edge_count:
        raise GeometryDecodeError(
            f"edgeNextIndices has {len(edge_next_indices)} entries for {edge_count} edges"
        )
    for vertex_index, data_index in enumerate(vertex_data_indices):
        if data_index < 0 or data_index >= len(positions):
            raise GeometryDecodeError(
                f"vertexDataIndices[{vertex_index}]={data_index} is outside "
                f"the {len(positions)}-position stream"
            )
    for edge_index, next_index in enumerate(edge_next_indices):
        if next_index < 0 or next_index >= edge_count:
            raise GeometryDecodeError(
                f"edgeNextIndices[{edge_index}]={next_index} is outside edge array"
            )
    for offset, vertex_index in enumerate(edge_vertex_indices):
        if vertex_index < 0 or vertex_index >= len(vertex_data_indices):
            raise GeometryDecodeError(
                f"edgeVertexIndices[{offset}]={vertex_index} is outside vertex topology"
            )

    faces = []
    warnings = []
    for face_index, first_edge in enumerate(face_edge_indices):
        if first_edge < 0 or first_edge >= edge_count:
            raise GeometryDecodeError(
                f"faceEdgeIndices[{face_index}]={first_edge} is outside edge array"
            )
        edge = first_edge
        visited = set()
        loop_vertex_indices = []
        while edge not in visited:
            if len(visited) >= edge_count:
                raise GeometryDecodeError(f"Face {face_index} edge walk exceeded edge count")
            visited.add(edge)
            # The first entry of each edge pair is the vertex reached by this
            # half-edge in the map's stored face winding.
            loop_vertex_indices.append(edge_vertex_indices[2 * edge])
            edge = edge_next_indices[edge]
        if edge != first_edge:
            raise GeometryDecodeError(
                f"Face {face_index} edge loop entered a different cycle at edge {edge}"
            )
        if len(loop_vertex_indices) < 3:
            warnings.append(f"Face {face_index} has fewer than 3 vertices and was skipped")
            continue
        data_indices = [vertex_data_indices[i] for i in loop_vertex_indices]
        face_points = [positions[i] for i in data_indices]
        faces.append({
            "face_index": face_index,
            "topology_vertex_indices": loop_vertex_indices,
            "vertex_data_indices": data_indices,
            "points": face_points,
        })

    return {
        "mesh_name": mesh_data.get("name", ""),
        "vertex_count": len(positions),
        "topology_vertex_count": len(vertex_data_indices),
        "edge_count": edge_count,
        "face_count": len(face_edge_indices),
        "decoded_face_count": len(faces),
        "materials": attrs.get("materials", []) if isinstance(attrs.get("materials"), list) else [],
        "faces": faces,
        "warnings": warnings,
        "coordinate_space": "mesh-local; CMapMesh transforms have not been applied",
        "vmf_brush_ready": False,
        "brush_readiness_note": (
            "Topology and local positions decoded; transform composition, closed-solid "
            "validation, convexity checks, and VMF plane validation are still required."
        ),
    }


def decode_map_meshes(graph: dict) -> list[dict]:
    """Decode each CMapMesh with a meshData reference, returning per-mesh errors as data."""
    elements = graph.get("elements", [])
    if not isinstance(elements, list):
        raise GeometryDecodeError("DMX graph has no element list")
    results = []
    for index, node in enumerate(elements):
        if node.get("type") != "CMapMesh":
            continue
        attrs = node.get("attributes", {})
        record = {
            "node_index": index,
            "node_name": node.get("name", ""),
            "node_guid": node.get("guid"),
            "origin": attrs.get("origin"),
            "angles": attrs.get("angles"),
            "scales": attrs.get("scales", attrs.get("scale")),
        }
        try:
            mesh_data = _attribute_element(node, "meshData", elements)
            record["geometry"] = decode_polygon_mesh(mesh_data, elements)
            record["status"] = "decoded_local_geometry"
        except GeometryDecodeError as exc:
            record["status"] = "unsupported_or_malformed"
            record["error"] = str(exc)
        results.append(record)
    return results
