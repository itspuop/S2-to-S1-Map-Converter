"""Headless Blender Source Tools exporter used by model_pipeline.py."""
from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path


def blender_compatible_dmx_bytes(data: bytes) -> bytes:
    """Return a DMX byte stream Blender Source Tools can parse.

    Source 2 binary_seqids v9 has the same payload layout as binary v9; only
    its element-ID bytes differ. Blender Source Tools rejects the encoding
    label before parsing, so changing only that label is sufficient. The
    original source file is never modified.
    """
    nul = data.find(b"\0")
    if nul < 0:
        raise ValueError("DMX file has no null-terminated header.")
    header = data[:nul]
    if b"dmx encoding binary_seqids 9 format " not in header:
        return data
    return header.replace(b"binary_seqids", b"binary", 1) + data[nul:]


def normalize_smd_material_paths(smd_path: Path) -> list[dict]:
    """Normalize Source 2 VMAT paths in SMD triangle material rows for QC $cdmaterials."""
    lines = smd_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    in_triangles = False
    changes = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.lower() == "triangles":
            in_triangles = True
            continue
        if not in_triangles or not stripped:
            continue
        first = stripped.split()[0]
        if first.lstrip("+-").isdigit():
            continue
        original = stripped.strip('"')
        normalized = original.replace("\\", "/")
        if normalized.lower().startswith("materials/"):
            normalized = normalized[10:]
        if normalized.lower().startswith("s2_import/"):
            normalized = normalized[10:]
        for suffix in (".vmat_c", ".vmat", ".vmt"):
            if normalized.lower().endswith(suffix):
                normalized = normalized[:-len(suffix)]
                break
        if normalized != original:
            lines[index] = normalized
            changes.append({"line": index + 1, "source_material": original,
                            "smd_material": normalized})
    if changes:
        smd_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changes


def main():
    try:
        separator = sys.argv.index("--")
        source_path, output_dir, object_name = sys.argv[separator + 1:separator + 4]
        source = Path(source_path)
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)

        try:
            import bpy
        except Exception as exc:
            raise RuntimeError(f"Blender Python API is unavailable: {exc}")

        # Start from an empty scene, then enable the installed import/export add-ons.
        bpy.ops.wm.read_factory_settings(use_empty=True)
        for addon_module in ("io_scene_fbx", "io_scene_valvesource"):
            try:
                bpy.ops.preferences.addon_enable(module=addon_module)
            except Exception:
                pass
        if not hasattr(bpy.context.scene, "vs"):
            raise RuntimeError(
                "Blender Source Tools did not register Scene.vs. "
                "Check that io_scene_valvesource 3.4.3 is installed in this Blender profile."
            )

        suffix = source.suffix.lower()
        if suffix == ".json":
            # Native mesh package emitted by vmap_export.py. Geometry coordinates
            # already include the Source 2 instance transform, so the resulting
            # prop entity is placed at world origin with identity angles.
            payload = json.loads(source.read_text(encoding="utf-8"))
            vertices = payload.get("vertices", [])
            faces = payload.get("faces", [])
            material_names = payload.get("materials", [])
            if not vertices or not faces:
                raise RuntimeError("Mesh package contains no vertices or faces.")
            mesh = bpy.data.meshes.new(object_name)
            mesh.from_pydata(vertices, [], faces)
            mesh.update()
            obj = bpy.data.objects.new(object_name, mesh)
            bpy.context.collection.objects.link(obj)
            for material_name in sorted(set(str(value) for value in material_names)):
                material = bpy.data.materials.new(name=material_name)
                obj.data.materials.append(material)
            material_slots = {material.name: index for index, material in enumerate(obj.data.materials)}
            for polygon_index, polygon in enumerate(mesh.polygons):
                if polygon_index < len(material_names):
                    polygon.material_index = material_slots.get(str(material_names[polygon_index]), 0)
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
        elif suffix == ".fbx":
            bpy.ops.import_scene.fbx(filepath=str(source))
        elif suffix == ".dmx":
            if not hasattr(bpy.ops.import_scene, "smd"):
                raise RuntimeError("Blender Source Tools DMX importer operator is unavailable.")
            # Blender Source Tools 3.4.3 rejects the binary_seqids encoding
            # label even though its v9 payload is otherwise binary-compatible.
            # Import a temporary header-normalized copy; leave addon assets intact.
            dmx_data = source.read_bytes()
            compatible_data = blender_compatible_dmx_bytes(dmx_data)
            if compatible_data is dmx_data:
                bpy.ops.import_scene.smd(filepath=str(source))
            else:
                with tempfile.TemporaryDirectory(prefix="s2css_dmx_") as temp_dir:
                    compatible_source = Path(temp_dir) / source.name
                    compatible_source.write_bytes(compatible_data)
                    bpy.ops.import_scene.smd(filepath=str(compatible_source))
        else:
            raise RuntimeError(f"Unsupported source model extension: {suffix}")

        meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
        if not meshes:
            raise RuntimeError("Import completed but produced no mesh objects.")

        bpy.ops.object.select_all(action="DESELECT")
        for obj in meshes:
            obj.select_set(True)
        active = meshes[0]
        bpy.context.view_layer.objects.active = active
        if len(meshes) > 1:
            bpy.ops.object.join()
        active = bpy.context.view_layer.objects.active
        active.name = object_name
        active.data.name = object_name
        active.data.validate(clean_customdata=True)
        active.data.update()
        if not active.data.uv_layers:
            # Imported mesh packages do not contain Source 2 UV layers in this
            # intermediate representation. Generate a fallback atlas so VMTs
            # have usable texture coordinates rather than a zeroed UV channel.
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.uv.smart_project(island_margin=0.02)
            bpy.ops.object.mode_set(mode="OBJECT")

        scene = bpy.context.scene
        scene.vs.export_format = "SMD"
        scene.vs.up_axis = "Z"
        scene.vs.export_path = str(output)
        scene.vs.qc_compile = False
        scene.vs.export_list.clear()
        for obj in list(scene.objects):
            if obj.type == "MESH":
                obj.vs.export = (obj == active)
                obj.vs.subdir = ""
        export_item = scene.vs.export_list.add()
        export_item.obj = active
        active.select_set(True)
        bpy.context.view_layer.objects.active = active

        # Blender Source Tools may remove/rebuild the exported object during its
        # operator. Capture all RNA-backed metadata before export so the success
        # path never dereferences a removed Object/ Mesh afterwards.
        mesh_objects_imported = len(meshes)
        vertex_count = len(active.data.vertices)
        polygon_count = len(active.data.polygons)

        result = bpy.ops.export_scene.smd(export_scene=True)
        if "FINISHED" not in result:
            raise RuntimeError(f"Blender Source Tools export returned {result!r}")

        expected = output / f"{object_name}.smd"
        if not expected.is_file():
            candidates = sorted(output.rglob("*.smd"))
            if not candidates:
                raise RuntimeError("Blender Source Tools reported success but produced no SMD.")
            expected = candidates[0]

        material_path_changes = normalize_smd_material_paths(expected)
        payload = {
            "status": "success",
            "material_path_changes": material_path_changes,
            "source_file": str(source),
            "smd_file": str(expected),
            "mesh_objects_imported": mesh_objects_imported,
            "vertex_count": vertex_count,
            "polygon_count": polygon_count,
            "blender_version": bpy.app.version_string,
            "source_tools_export_operator": "export_scene.smd",
        }
        (output / "blender_export_result.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        output_dir = Path(sys.argv[sys.argv.index("--") + 2]) if "--" in sys.argv else Path.cwd()
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "blender_export_result.json").write_text(
            json.dumps({"status": "failed", "error": str(exc), "traceback": traceback.format_exc()}, indent=2),
            encoding="utf-8",
        )
        raise


if __name__ == "__main__":
    main()
