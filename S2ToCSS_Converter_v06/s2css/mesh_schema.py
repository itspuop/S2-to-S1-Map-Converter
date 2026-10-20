"""Diagnostic inventory of native CMapMesh / CDmePolygonMesh schemas.

This tool reports what the actual editable VMAP contains before geometry decoding is
attempted. It deliberately does not guess binary vertex layouts or claim VMF readiness.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .dmx_binary import parse_binary_v9


def _shape(value: Any, elements: list[dict]) -> Any:
    if isinstance(value, dict):
        if "element_index" in value:
            i = value["element_index"]
            if isinstance(i, int) and 0 <= i < len(elements):
                target = elements[i]
                return {"reference": i, "type": target.get("type"), "name": target.get("name")}
            return {"reference": i, "invalid": True}
        if "binary_bytes" in value:
            return {"binary_bytes": value.get("binary_bytes")}
        return {k: _shape(v, elements) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) <= 8:
            return [_shape(v, elements) for v in value]
        return {
            "array_length": len(value),
            "sample": [_shape(v, elements) for v in value[:4]],
            "item_kinds": sorted({type(v).__name__ for v in value}),
        }
    if isinstance(value, str) and len(value) > 160:
        return value[:157] + "..."
    return value


def _element_summary(index: int, element: dict, elements: list[dict]) -> dict:
    attrs = element.get("attributes", {})
    return {
        "index": index,
        "type": element.get("type"),
        "name": element.get("name"),
        "guid": element.get("guid"),
        "attributes": {name: _shape(value, elements) for name, value in attrs.items()},
    }


def inspect_mesh_schema(vmap_path: str | Path) -> dict:
    """Parse an editable VMAP and summarize all mesh/topology/vertex-data elements."""
    path = Path(vmap_path)
    graph = parse_binary_v9(path)
    elements = graph.get("elements", [])
    relevant = []
    mesh_nodes = []
    for index, element in enumerate(elements):
        kind = str(element.get("type", ""))
        low = kind.lower()
        attrs = element.get("attributes", {})
        is_mesh_node = kind == "CMapMesh"
        is_mesh_data = (
            "polygonmesh" in low
            or "vertexdata" in low
            or "vertexattribute" in low
            or "mesh" in low and any(
                key in attrs for key in (
                    "vertexData", "faceVertexData", "edgeVertexIndices",
                    "edgeNextIndices", "faceEdgeIndices", "vertexDataIndices",
                )
            )
        )
        if is_mesh_node:
            mesh_nodes.append(_element_summary(index, element, elements))
        if is_mesh_node or is_mesh_data:
            relevant.append(_element_summary(index, element, elements))

    return {
        "source_file": str(path),
        "dmx_format": graph.get("format"),
        "dmx_format_version": graph.get("format_version"),
        "element_count": len(elements),
        "cmapmesh_count": sum(1 for e in elements if e.get("type") == "CMapMesh"),
        "mesh_related_element_count": len(relevant),
        "mesh_nodes": mesh_nodes,
        "mesh_related_elements": relevant,
        "interpretation": {
            "status": "schema_inventory_only",
            "decoded_vertex_positions": False,
            "decoded_face_loops": False,
            "vmf_brush_ready": False,
            "next_step": (
                "Use the reported real attribute names, element references, array lengths, "
                "and binary byte counts to implement and test the exact vertex-data layout."
            ),
        },
    }


def write_mesh_schema_report(vmap_path: str | Path, output_path: str | Path) -> dict:
    report = inspect_mesh_schema(vmap_path)
    Path(output_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
