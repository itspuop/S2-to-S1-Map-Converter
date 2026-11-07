"""Export a validated decoded polygon mesh as a Source 1 VMF brush.

Input is the JSON diagnostic produced by the native VMAP mesh decoder. Only closed,
planar-faced, convex meshes are emitted as a single world brush. Unsupported meshes
are rejected instead of silently producing broken VMF.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


class MeshExportError(ValueError):
    pass


def _vec3(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        raise MeshExportError(f"{label} must be a 3-component vector")
    result = tuple(float(value[i]) for i in range(3))
    if not all(math.isfinite(v) for v in result):
        raise MeshExportError(f"{label} contains a non-finite coordinate")
    return result


def _dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


def _sub(a, b):
    return (a[0]-b[0], a[1]-b[1], a[2]-b[2])


def _add(a, b):
    return (a[0]+b[0], a[1]+b[1], a[2]+b[2])


def _cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _length(v):
    return math.sqrt(_dot(v, v))


def _normalise(v):
    n = _length(v)
    if n <= 1e-12:
        raise MeshExportError("Degenerate face has no usable plane normal")
    return (v[0]/n, v[1]/n, v[2]/n)


def _face_normal(points):
    # Newell normal works for planar convex polygons with more than three vertices.
    nx = ny = nz = 0.0
    for i, p in enumerate(points):
        q = points[(i + 1) % len(points)]
        nx += (p[1]-q[1]) * (p[2]+q[2])
        ny += (p[2]-q[2]) * (p[0]+q[0])
        nz += (p[0]-q[0]) * (p[1]+q[1])
    return _normalise((nx, ny, nz))


def _source_transform(point, origin, angles, scales):
    """Apply Source-style pitch/yaw/roll basis and component scale to local vertices."""
    x, y, z = (point[i] * scales[i] for i in range(3))
    pitch, yaw, roll = (math.radians(v) for v in angles)
    sp, cp = math.sin(pitch), math.cos(pitch)
    sy, cy = math.sin(yaw), math.cos(yaw)
    sr, cr = math.sin(roll), math.cos(roll)
    # Source AngleVectors basis. At zero angles this is identity; local Y remains Y.
    forward = (cp*cy, cp*sy, -sp)
    right = (-sr*sp*cy + cr*sy, -sr*sp*sy - cr*cy, -sr*cp)
    up = (cr*sp*cy + sr*sy, cr*sp*sy - sr*cy, cr*cp)
    world = (
        origin[0] + forward[0]*x - right[0]*y + up[0]*z,
        origin[1] + forward[1]*x - right[1]*y + up[1]*z,
        origin[2] + forward[2]*x - right[2]*y + up[2]*z,
    )
    return world


def _extract_mesh(document: dict) -> tuple[list[tuple[float, float, float]], list[list[int]]]:
    raw_positions = document.get("positions_local", document.get("vertices"))
    raw_faces = document.get("face_loops", document.get("faces"))
    if not isinstance(raw_positions, list) or not raw_positions:
        raise MeshExportError("JSON has no positions_local/vertices array")
    if not isinstance(raw_faces, list) or not raw_faces:
        raise MeshExportError("JSON has no face_loops/faces array")
    positions = [_vec3(p, f"vertex {i}") for i, p in enumerate(raw_positions)]
    faces = []
    for fi, face in enumerate(raw_faces):
        if not isinstance(face, list) or len(face) < 3:
            raise MeshExportError(f"Face {fi} has fewer than three vertex indices")
        try:
            loop = [int(i) for i in face]
        except (TypeError, ValueError) as exc:
            raise MeshExportError(f"Face {fi} has non-integer vertex indices") from exc
        if any(i < 0 or i >= len(positions) for i in loop):
            raise MeshExportError(f"Face {fi} references an out-of-range vertex")
        if len(set(loop)) < 3:
            raise MeshExportError(f"Face {fi} has fewer than three unique vertices")
        faces.append(loop)
    return positions, faces


def validate_convex_brush(vertices, faces, tolerance=0.05) -> dict:
    """Return geometric checks; VMF brush export requires every check to pass."""
    issues = []
    edge_uses = {}
    center = tuple(sum(v[k] for v in vertices) / len(vertices) for k in range(3))
    planes = []
    for fi, face in enumerate(faces):
        points = [vertices[i] for i in face]
        try:
            normal = _face_normal(points)
        except MeshExportError:
            issues.append(f"face {fi}: degenerate polygon")
            continue
        anchor = points[0]
        max_error = max(abs(_dot(normal, _sub(p, anchor))) for p in points)
        if max_error > tolerance:
            issues.append(f"face {fi}: non-planar (max deviation {max_error:.4g})")
        # Plane must support the whole mesh: all points lie on one side.
        distances = [_dot(normal, _sub(v, anchor)) for v in vertices]
        pos = max(distances)
        neg = min(distances)
        if pos > tolerance and neg < -tolerance:
            issues.append(f"face {fi}: mesh crosses its face plane (not convex)")
        # Face loops should form a closed 2-manifold.
        for j, a in enumerate(face):
            b = face[(j + 1) % len(face)]
            key = (min(a, b), max(a, b))
            edge_uses[key] = edge_uses.get(key, 0) + 1
        planes.append((fi, normal, anchor, points))
    boundary = sum(1 for n in edge_uses.values() if n == 1)
    nonmanifold = sum(1 for n in edge_uses.values() if n > 2)
    if boundary:
        issues.append(f"{boundary} boundary edge(s): mesh is open")
    if nonmanifold:
        issues.append(f"{nonmanifold} non-manifold edge(s)")
    # Every polygon should face away from the vertex centroid. Face loops are reoriented
    # during output, but inconsistent/ambiguous normals are still unsafe for a solid.
    for fi, normal, anchor, points in planes:
        face_center = tuple(sum(p[k] for p in points)/len(points) for k in range(3))
        if abs(_dot(normal, _sub(face_center, center))) < 1e-8:
            issues.append(f"face {fi}: ambiguous orientation relative to mesh center")
    return {
        "valid": not issues,
        "vertex_count": len(vertices),
        "face_count": len(faces),
        "unique_edge_count": len(edge_uses),
        "boundary_edge_count": boundary,
        "nonmanifold_edge_count": nonmanifold,
        "issues": issues,
    }


def _plane_points(face, vertices, center):
    points = [vertices[i] for i in face]
    normal = _face_normal(points)
    face_center = tuple(sum(p[k] for p in points)/len(points) for k in range(3))
    # VMF brush plane points must wind toward the brush interior. The decoded
    # polygon normal is oriented outward here, so reverse outward-facing loops.
    if _dot(normal, _sub(face_center, center)) > 0:
        points.reverse()
    # VMF stores a plane using three non-collinear points.
    a = points[0]
    for i in range(1, len(points)-1):
        if _length(_cross(_sub(points[i], a), _sub(points[i+1], a))) > 1e-8:
            return a, points[i], points[i+1]
    raise MeshExportError("Could not find three non-collinear points for a face plane")


def _fmt(v):
    if abs(v) < 0.00005:
        v = 0.0
    return f"{v:.4f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v))


def _vmf_side(side_id, a, b, c, material):
    plane = f"({_fmt(a[0])} {_fmt(a[1])} {_fmt(a[2])}) ({_fmt(b[0])} {_fmt(b[1])} {_fmt(b[2])}) ({_fmt(c[0])} {_fmt(c[1])} {_fmt(c[2])})"
    return (
        "  side\n  {\n"
        f'   "id" "{side_id}"\n'
        f'   "plane" "{plane}"\n'
        f'   "material" "{material}"\n'
        '   "uaxis" "[1 0 0 0] 0.25"\n'
        '   "vaxis" "[0 -1 0 0] 0.25"\n'
        '   "rotation" "0"\n'
        '   "lightmapscale" "16"\n'
        '   "smoothing_groups" "0"\n'
        "  }\n"
    )


def export_decoded_mesh(document: dict, output_path: str | Path, material="TOOLS/TOOLSNODRAW") -> dict:
    """Validate one decoded mesh and write a VMF containing a single world brush."""
    positions, faces = _extract_mesh(document)
    origin = _vec3(document.get("origin", [0, 0, 0]), "origin")
    angles = _vec3(document.get("angles", [0, 0, 0]), "angles")
    scales = _vec3(document.get("scales", document.get("scale", [1, 1, 1])), "scales")
    vertices = [_source_transform(p, origin, angles, scales) for p in positions]
    report = validate_convex_brush(vertices, faces)
    report["transform"] = {"origin": list(origin), "angles": list(angles), "scales": list(scales)}
    if not report["valid"]:
        raise MeshExportError("Mesh is not safe to emit as one VMF brush: " + "; ".join(report["issues"]))
    center = tuple(sum(v[k] for v in vertices)/len(vertices) for k in range(3))
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "// Generated by S2ToCSS Converter. Review in Hammer before compiling.\n",
        "versioninfo\n{\n",
        ' "editorversion" "400"\n "editorbuild" "0"\n "mapversion" "1"\n "formatversion" "100"\n "prefab" "0"\n}\n',
        "visgroups\n{\n}\nviewsettings\n{\n",
        ' "bSnapToGrid" "1"\n "bShowGrid" "1"\n "bShowLogicalGrid" "0"\n "nGridSpacing" "64"\n "bShow3DGrid" "0"\n}\n',
        'world\n{\n "id" "1"\n',
        ' "mapversion" "1"\n "classname" "worldspawn"\n "detailmaterial" "detail/detailsprites"\n "detailvbsp" "detail.vbsp"\n "maxpropscreenwidth" "-1"\n "skyname" "sky_day01_01"\n',
        " solid\n {\n  \"id\" \"2\"\n",
    ]
    side_id = 3
    for face in faces:
        a, b, c = _plane_points(face, vertices, center)
        lines.append(_vmf_side(side_id, a, b, c, material))
        side_id += 1
    lines.extend([
        "  editor\n  {\n   \"color\" \"0 0 0\"\n   \"visgroupshown\" \"1\"\n   \"visgroupautoshown\" \"1\"\n  }\n",
        " }\n}\n",
    ])
    out.write_text("".join(lines), encoding="utf-8")
    report.update({"output": str(out), "status": "written", "material": material})
    return report


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Export one validated decoded VMAP mesh JSON to a VMF brush.")
    parser.add_argument("mesh_json", type=Path, help="Decoded mesh JSON with positions_local and face_loops")
    parser.add_argument("--output", type=Path, help="Output .vmf path (default: <input>_brush.vmf)")
    parser.add_argument("--material", default="TOOLS/TOOLSNODRAW", help="Source 1 material for all brush faces")
    parser.add_argument("--report", type=Path, help="Optional validation report JSON path")
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.mesh_json.read_text(encoding="utf-8"))
        output = args.output or args.mesh_json.with_name(args.mesh_json.stem + "_brush.vmf")
        report = export_decoded_mesh(document, output, args.material)
        if args.report:
            args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"VMF brush written: {output}")
        print(f"Validated {report['vertex_count']} vertices / {report['face_count']} faces.")
        print("Open in Hammer and inspect before compiling.")
        return 0
    except (OSError, json.JSONDecodeError, MeshExportError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
