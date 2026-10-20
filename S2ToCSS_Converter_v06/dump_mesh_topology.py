"""Dump complete topology arrays and position streams from an editable VMAP.

This diagnostic intentionally prints raw connectivity for one CMapMesh. It does not
convert geometry or assume every mesh is suitable for a convex VMF brush.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from s2css.dmx_binary import DMXError, parse_binary_v9

TOPOLOGY_KEYS = (
    "vertexEdgeIndices",
    "vertexDataIndices",
    "edgeVertexIndices",
    "edgeOppositeIndices",
    "edgeNextIndices",
    "edgeFaceIndices",
    "edgeDataIndices",
    "edgeVertexDataIndices",
    "faceEdgeIndices",
    "faceDataIndices",
)


def ref_index(value: Any) -> int | None:
    if isinstance(value, dict) and isinstance(value.get("element_index"), int):
        return value["element_index"]
    return None


def stream_summary(index: int, elements: list[dict]) -> dict:
    element = elements[index]
    attrs = element.get("attributes", {})
    data = attrs.get("data")
    return {
        "index": index,
        "type": element.get("type"),
        "name": element.get("name"),
        "semanticName": attrs.get("semanticName"),
        "standardAttributeName": attrs.get("standardAttributeName"),
        "data": data,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print full edge/face connectivity and vertex streams for one CMapMesh."
    )
    parser.add_argument("vmap", help="Path to the editable .vmap file")
    parser.add_argument(
        "--mesh-index",
        type=int,
        help="Element index of the CMapMesh; defaults to the first CMapMesh in the file",
    )
    args = parser.parse_args()

    try:
        graph = parse_binary_v9(Path(args.vmap))
    except (OSError, DMXError, ValueError) as exc:
        parser.error(str(exc))
    elements = graph.get("elements", [])
    candidates = [
        (i, e) for i, e in enumerate(elements)
        if e.get("type") == "CMapMesh"
    ]
    if not candidates:
        parser.error("No CMapMesh elements found.")
    selected = next(
        ((i, e) for i, e in candidates if i == args.mesh_index),
        None,
    ) if args.mesh_index is not None else candidates[0]
    if selected is None:
        parser.error(f"No CMapMesh found at element index {args.mesh_index}.")
    node_index, node = selected
    node_attrs = node.get("attributes", {})
    mesh_index = ref_index(node_attrs.get("meshData"))
    if mesh_index is None or not (0 <= mesh_index < len(elements)):
        parser.error(f"CMapMesh element {node_index} has no resolvable meshData reference.")
    mesh = elements[mesh_index]
    mesh_attrs = mesh.get("attributes", {})

    output = {
        "source_file": str(Path(args.vmap)),
        "cmapmesh_element_index": node_index,
        "cmapmesh_guid": node.get("guid"),
        "transform": {
            "origin": node_attrs.get("origin"),
            "angles": node_attrs.get("angles"),
            "scales": node_attrs.get("scales"),
        },
        "meshdata_element_index": mesh_index,
        "meshdata_type": mesh.get("type"),
        "topology": {key: mesh_attrs.get(key) for key in TOPOLOGY_KEYS},
        "materials": mesh_attrs.get("materials"),
        "data_arrays": {},
    }
    for attr in ("vertexData", "faceVertexData", "edgeData", "faceData"):
        arr_index = ref_index(mesh_attrs.get(attr))
        if arr_index is None or not (0 <= arr_index < len(elements)):
            output["data_arrays"][attr] = {"reference": arr_index, "error": "unresolved"}
            continue
        arr = elements[arr_index]
        arr_attrs = arr.get("attributes", {})
        streams = []
        for stream_ref in arr_attrs.get("streams", []):
            stream_index = ref_index(stream_ref)
            if stream_index is not None and 0 <= stream_index < len(elements):
                streams.append(stream_summary(stream_index, elements))
            else:
                streams.append({"error": "unresolved stream reference"})
        output["data_arrays"][attr] = {
            "element_index": arr_index,
            "type": arr.get("type"),
            "size": arr_attrs.get("size"),
            "streams": streams,
        }

    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
