"""Geometric sanity checks for diagnostic VMAP polygon decodes.

These checks do not emit VMF. They report planarity, convexity, and edge-manifold
properties in local space, leaving world-transform conventions for a separate test.
"""
from __future__ import annotations
import math
from collections import Counter

def _dot(a, b): return sum(a[i] * b[i] for i in range(3))
def _cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
def _length(v): return math.sqrt(_dot(v, v))
def _newell(points):
    n=[0.0,0.0,0.0]
    for p,q in zip(points,points[1:]+points[:1]):
        n[0]+=(p[1]-q[1])*(p[2]+q[2])
        n[1]+=(p[2]-q[2])*(p[0]+q[0])
        n[2]+=(p[0]-q[0])*(p[1]+q[1])
    length=_length(n)
    return None if length<=1e-12 else [v/length for v in n]

def validate_decoded_mesh(decoded: dict, tolerance: float=1e-4) -> dict:
    """Check polygon geometry in local space; never claims VMF readiness."""
    positions=decoded.get("positions_local",[]); faces=decoded.get("faces",[])
    if not positions or not faces: raise ValueError("Decoded JSON must contain non-empty positions_local and faces.")
    points=[]
    for i,p in enumerate(positions):
        if not isinstance(p,list) or len(p)<3: raise ValueError(f"Vertex {i} is not a 3D coordinate.")
        points.append([float(p[0]),float(p[1]),float(p[2])])
    edge_use=Counter(); directed=Counter(); face_reports=[]
    valid_polygons=[]
    for face in faces:
        fi=face.get("face_index"); ids=face.get("vertex_indices")
        if not face.get("valid") or not isinstance(ids,list) or len(ids)<3:
            face_reports.append({"face_index":fi,"valid":False,"reason":"decoder marked face invalid"}); continue
        if any(not isinstance(i,int) or i<0 or i>=len(points) for i in ids):
            face_reports.append({"face_index":fi,"valid":False,"reason":"vertex index out of range"}); continue
        poly=[points[i] for i in ids]; normal=_newell(poly)
        if normal is None:
            face_reports.append({"face_index":fi,"valid":False,"reason":"degenerate polygon"}); continue
        offset=_dot(normal,poly[0]); error=max(abs(_dot(normal,p)-offset) for p in poly)
        distances=[_dot(normal,p)-offset for p in points]
        convex=not (any(d>tolerance for d in distances) and any(d< -tolerance for d in distances))
        face_reports.append({"face_index":fi,"valid":error<=tolerance,"vertex_count":len(ids),
            "max_planarity_error":error,"all_mesh_vertices_on_one_side":convex,"normal_local":normal,
            **({"reason":"non-planar polygon"} if error>tolerance else {})})
        valid_polygons.append((fi,ids,error<=tolerance,convex))
        for a,b in zip(ids,ids[1:]+ids[:1]):
            if a!=b: edge_use[(min(a,b),max(a,b))]+=1; directed[(a,b)]+=1
    boundary=[list(e) for e,n in edge_use.items() if n==1]
    nonmanifold=[list(e) for e,n in edge_use.items() if n>2]
    conflicts=[]
    for a,b in edge_use:
        if edge_use[(a,b)]==2 and (directed[(a,b)]!=1 or directed[(b,a)]!=1): conflicts.append([a,b])
    return {
        "source_file":decoded.get("source_file"),"node_index":decoded.get("node_index"),
        "meshdata_index":decoded.get("meshdata_index"),
        "transform":{"origin":decoded.get("origin"),"angles":decoded.get("angles"),"scales":decoded.get("scales"),"world_positions_computed":False},
        "vertex_count":len(points),"face_count":len(faces),
        "planar_faces":sum(1 for f in face_reports if f["valid"]),"face_reports":face_reports,
        "all_faces_planar":bool(face_reports) and all(f["valid"] for f in face_reports),
        "all_faces_bound_convex_halfspaces":bool(valid_polygons) and all(f[3] for f in valid_polygons),
        "closed_two_manifold":bool(edge_use) and not boundary and not nonmanifold,
        "boundary_edges":boundary,"nonmanifold_edges":nonmanifold,"orientation_conflicts":conflicts,
        "vmf_brush_ready":False,
        "limitations":["Local-space positions only; transform angle convention is not yet verified.",
          "Convex half-space and manifold checks are necessary but not sufficient for a valid VMF solid.",
          "Texture axes/material mapping and Source 1 plane serialization are not checked."]
    }
