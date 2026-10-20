"""Decode one CMapMesh in an editable VMAP into diagnostic polygon JSON."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from s2css.dmx_binary import DMXError
from s2css.mesh_decode import MeshDecodeError, decode_vmap_mesh


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vmap", type=Path, help="Editable binary-DMX .vmap (not .vmap_c)")
    parser.add_argument("--mesh-index", type=int, required=True, help="CMapMesh element index in the DMX graph")
    parser.add_argument("--output", type=Path, help="Output JSON path")
    args = parser.parse_args(argv)
    if not args.vmap.is_file():
        parser.error(f"VMAP file not found: {args.vmap}")
    output = args.output or args.vmap.with_name(f"{args.vmap.stem}_mesh_{args.mesh_index}.json")
    try:
        result = decode_vmap_mesh(args.vmap, args.mesh_index)
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except (OSError, DMXError, MeshDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Decoded mesh JSON written: {output}")
    print(f"Vertices: {result['counts']['vertices']}; faces: {result['counts']['faces']}")
    print("Geometry is diagnostic until validated for VMF export.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
