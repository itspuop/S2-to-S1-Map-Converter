"""Decode polygon face loops from one CMapMesh in an editable VMAP to JSON."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from s2css.dmx_binary import DMXError, parse_binary_v9
from s2css.mesh_decode import decode_polygon_mesh


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Decode local vertex positions and polygon face loops from a native VMAP mesh."
    )
    parser.add_argument("vmap", help="Path to editable .vmap")
    parser.add_argument("--mesh-index", type=int, help="CMapMesh element index (defaults to first)")
    parser.add_argument("--output", help="Optional JSON output path; defaults to stdout")
    args = parser.parse_args()

    try:
        graph = parse_binary_v9(Path(args.vmap))
        elements = graph.get("elements", [])
        nodes = [i for i, e in enumerate(elements) if e.get("type") == "CMapMesh"]
        if not nodes:
            parser.error("No CMapMesh elements found.")
        node_index = args.mesh_index if args.mesh_index is not None else nodes[0]
        decoded = decode_polygon_mesh(elements, node_index)
        decoded["source_file"] = str(Path(args.vmap))
    except (OSError, DMXError, ValueError) as exc:
        parser.error(str(exc))

    rendered = json.dumps(decoded, indent=2)
    if args.output:
        out = Path(args.output)
        out.write_text(rendered, encoding="utf-8")
        print(f"Wrote diagnostic polygon decode: {out}")
        print(f"Faces: {len(decoded['faces'])}; valid: {decoded['valid_face_count']}; invalid: {decoded['invalid_face_count']}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
