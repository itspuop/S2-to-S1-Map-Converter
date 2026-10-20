"""Validate geometry in decoded_mesh JSON without exporting VMF."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from s2css.mesh_validate import validate_decoded_mesh

def main() -> int:
    parser=argparse.ArgumentParser(description="Check planarity, convexity, and manifold edges in decoded mesh JSON.")
    parser.add_argument("decoded_json",help="Output from decode_vmap_mesh.py")
    parser.add_argument("--output",default="mesh_validation.json",help="JSON report path")
    args=parser.parse_args()
    try:
        decoded=json.loads(Path(args.decoded_json).read_text(encoding="utf-8"))
        report=validate_decoded_mesh(decoded)
        Path(args.output).write_text(json.dumps(report,indent=2),encoding="utf-8")
    except (OSError,ValueError,json.JSONDecodeError) as exc: parser.error(str(exc))
    print(f"Wrote geometry validation report: {args.output}")
    print(f"Planar faces: {report['planar_faces']}/{report['face_count']}")
    print(f"Closed two-manifold: {report['closed_two_manifold']}")
    print(f"Convex half-space check: {report['all_faces_bound_convex_halfspaces']}")
    print("VMF brush ready: False (export is intentionally disabled)")
    return 0
if __name__=="__main__": raise SystemExit(main())
