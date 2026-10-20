"""Diagnose one CMapMesh's local geometry and transformed bounds without exporting it."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from s2css.dmx_binary import parse_binary_v9
from s2css.mesh_decode import decode_polygon_mesh
from s2css.vmf_export import _extract_mesh, _source_transform, validate_convex_brush


def bounds(points):
    if not points:
        return None
    return {
        "min": [min(p[i] for p in points) for i in range(3)],
        "max": [max(p[i] for p in points) for i in range(3)],
        "size": [max(p[i] for p in points) - min(p[i] for p in points) for i in range(3)],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vmap", type=Path)
    parser.add_argument("--mesh-index", type=int, required=True, help="CMapMesh element index from the DMX graph")
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()
    graph = parse_binary_v9(args.vmap, include_binary=False)
    elements = graph.get("elements", [])
    if args.mesh_index < 0 or args.mesh_index >= len(elements):
        parser.error(f"mesh index {args.mesh_index} is outside 0..{len(elements)-1}")
    node = elements[args.mesh_index]
    if node.get("type") != "CMapMesh":
        parser.error(f"element {args.mesh_index} is {node.get('type')!r}, not CMapMesh")
    decoded = decode_polygon_mesh(graph, args.mesh_index)
    positions, faces = _extract_mesh(decoded)
    origin = decoded.get("origin", [0, 0, 0])
    angles = decoded.get("angles", [0, 0, 0])
    scales = decoded.get("scales", [1, 1, 1])
    transformed = [_source_transform(p, origin, angles, scales) for p in positions]
    report = {
        "source_file": str(args.vmap),
        "cmapmesh_element_index": args.mesh_index,
        "cmapmesh_guid": node.get("guid"),
        "meshData_index": decoded.get("meshData_index"),
        "transform": {"origin": origin, "angles": angles, "scales": scales},
        "counts": decoded.get("counts"),
        "local_bounds": bounds(positions),
        "transformed_bounds_current_source_basis": bounds(transformed),
        "validation_after_current_transform": validate_convex_brush(transformed, faces),
        "first_10_local_vertices": positions[:10],
        "first_10_transformed_vertices": transformed[:10],
        "face_loops": faces,
        "note": "This diagnostic reports the exporter's current transform interpretation; it does not assert that Source 2 uses the same angle convention as Source 1."
    }
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
        print(f"Wrote diagnostic report: {args.output}")
    print(rendered)


if __name__ == "__main__":
    main()
