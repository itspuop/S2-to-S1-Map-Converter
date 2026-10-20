"""Inspect native mesh attributes in an editable Source 2 VMAP.

Run from this folder:
    py inspect_mesh_schema.py "D:/path/to/map.vmap" "D:/path/to/mesh_schema.json"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from s2css.dmx_binary import DMXError
from s2css.mesh_schema import inspect_mesh_schema


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vmap", type=Path, help="Editable binary-DMX .vmap file (not .vmap_c)")
    parser.add_argument("output", nargs="?", type=Path,
                        help="Output JSON path (default: <mapname>_mesh_schema.json)")
    args = parser.parse_args()
    if not args.vmap.is_file():
        parser.error(f"VMAP file not found: {args.vmap}")
    output = args.output or args.vmap.with_name(args.vmap.stem + "_mesh_schema.json")
    try:
        report = inspect_mesh_schema(args.vmap)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except (OSError, DMXError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Mesh schema report written: {output}")
    print(f"CMapMesh nodes: {report['cmapmesh_count']}")
    print(f"Mesh-related elements: {report['mesh_related_element_count']}")
    print("This is a diagnostic report; it does not create VMF geometry.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
