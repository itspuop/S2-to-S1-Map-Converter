"""Optional Blender Source Tools -> SMD/QC -> CS:S studiomdl model pipeline.

The module deliberately keeps tool execution optional. It inventories candidate source
assets even when Blender/studiomdl are not configured, and only emits VMF prop entities
for models that were actually compiled.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Iterable

SUPPORTED_SOURCE_EXTENSIONS = (".dmx", ".fbx")
SUPPORTED_PROP_CLASSES = {"prop_static", "prop_dynamic", "prop_dynamic_override", "prop_physics", "prop_physics_override", "prop_physics_multiplayer"}


def safe_name(value: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "_-" else "_" for c in Path(value.replace("\\", "/")).stem)
    return cleaned.strip("_") or "source_model"


def model_key(source_model: str) -> str:
    normalized = source_model.replace("\\", "/").lower()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:8]


def find_model_source(project_root: str | Path, source_model: str) -> tuple[Path | None, list[Path]]:
    """Resolve a VMAP .vmdl reference to an editable DMX/FBX with the same relative stem."""
    root = Path(project_root)
    ref = Path(source_model.replace("\\", "/"))
    relative = ref.with_suffix("")
    candidates: list[Path] = []
    for ext in SUPPORTED_SOURCE_EXTENSIONS:
        direct = root / relative.with_suffix(ext)
        if direct.is_file():
            candidates.append(direct)
    if candidates:
        return candidates[0], candidates

    wanted_stem = ref.stem.lower()
    wanted_relative = relative.as_posix().lower()
    matches: list[Path] = []
    try:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in SUPPORTED_SOURCE_EXTENSIONS:
                rel = path.relative_to(root).with_suffix("").as_posix().lower()
                stem = path.stem.lower()
                if rel == wanted_relative or stem == wanted_stem or rel.startswith(wanted_relative + "_") or stem.startswith(wanted_stem + "_"):
                    matches.append(path)
    except OSError:
        pass
    def source_rank(path: Path):
        stem = path.stem.lower()
        return (
            0 if path.suffix.lower() == ".dmx" else 1,
            0 if "lod0" in stem else 1,
            0 if "body" in stem else 1,
            len(stem),
            str(path).lower(),
        )
    matches.sort(key=source_rank)
    return (matches[0] if matches else None), matches


def write_qc(
    qc_path: str | Path,
    model_name: str,
    smd_name: str,
    static_prop: bool,
    collision: bool = True,
) -> Path:
    """Write a conservative QC for a static or dynamic CS:S model."""
    qc = Path(qc_path)
    qc.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f'$modelname "models/s2_import/{model_name}.mdl"',
        f'$body "body" "{smd_name}"',
        '$surfaceprop "default"',
        '$cdmaterials "s2_import"',
    ]
    if static_prop:
        lines.append("$staticprop")
    if collision:
        lines.extend([f'$collisionmodel "{smd_name}"', "{", "    $concave", "}"])
    lines.extend([f'$sequence "idle" "{smd_name}"', ""])
    qc.write_text("\n".join(lines), encoding="utf-8")
    return qc


def _blender_script_path() -> Path:
    return Path(__file__).with_name("blender_export.py")


def export_smd_with_blender(
    blender_exe: str | Path,
    source_file: str | Path,
    export_dir: str | Path,
    object_name: str,
    timeout: int = 1800,
) -> tuple[Path, dict]:
    """Run Blender headlessly and export the imported static mesh through Blender Source Tools."""
    blender = Path(blender_exe)
    source = Path(source_file)
    out = Path(export_dir)
    out.mkdir(parents=True, exist_ok=True)
    if not blender.is_file():
        raise FileNotFoundError(f"Blender executable not found: {blender}")
    if not source.is_file():
        raise FileNotFoundError(f"Source model file not found: {source}")
    script = _blender_script_path()
    if not script.is_file():
        raise FileNotFoundError(f"Bundled Blender export script is missing: {script}")
    command = [
        str(blender), "--background", "--factory-startup",
        "--python", str(script), "--",
        str(source.resolve()), str(out.resolve()), safe_name(object_name),
    ]
    completed = subprocess.run(
        command, capture_output=True, text=True, timeout=timeout,
        cwd=str(out), check=False,
    )
    log = (completed.stdout or "") + "\n" + (completed.stderr or "")
    result_file = out / "blender_export_result.json"
    if completed.returncode != 0:
        raise RuntimeError(
            f"Blender export failed (exit {completed.returncode}).\n"
            f"Command: {subprocess.list2cmdline(command)}\n{log[-12000:]}"
        )
    if not result_file.is_file():
        raise RuntimeError(f"Blender exited without writing its result file.\n{log[-8000:]}")
    result = json.loads(result_file.read_text(encoding="utf-8"))
    smd = Path(result.get("smd_file", ""))
    if not smd.is_file():
        raise RuntimeError(f"Blender reported success but the SMD file is missing: {smd}\n{log[-8000:]}")
    result["log_tail"] = log[-4000:]
    return smd, result


def compile_qc(
    studiomdl_exe: str | Path,
    game_dir: str | Path,
    qc_file: str | Path,
    output_dir: str | Path,
    timeout: int = 900,
) -> dict:
    """Compile one QC using the user's CS:S studiomdl and stage generated model files."""
    compiler, game, qc = Path(studiomdl_exe), Path(game_dir), Path(qc_file)
    if not compiler.is_file():
        raise FileNotFoundError(f"studiomdl.exe not found: {compiler}")
    if not game.is_dir():
        raise FileNotFoundError(f"CS:S game directory not found: {game}")
    if not qc.is_file():
        raise FileNotFoundError(f"QC file not found: {qc}")
    command = [str(compiler), "-nop4", "-game", str(game), str(qc)]
    completed = subprocess.run(
        command, capture_output=True, text=True, timeout=timeout,
        cwd=str(qc.parent), check=False,
    )
    log = (completed.stdout or "") + "\n" + (completed.stderr or "")
    if completed.returncode != 0:
        raise RuntimeError(
            f"studiomdl failed (exit {completed.returncode}) for {qc.name}.\n{log[-12000:]}"
        )
    model_name = _qc_model_name(qc)
    staged = Path(output_dir) / "models" / "s2_import"
    staged.mkdir(parents=True, exist_ok=True)
    compiled_root = game / "models" / "s2_import"
    copied = []
    for artifact in compiled_root.glob(model_name + ".*"):
        target = staged / artifact.name
        shutil.copy2(artifact, target)
        copied.append(str(target))
    mdl = staged / (model_name + ".mdl")
    if not mdl.is_file():
        raise RuntimeError(
            f"studiomdl returned success but {mdl.name} was not found under "
            f"{compiled_root}. Check the QC $modelname and CS:S game path.\n{log[-8000:]}"
        )
    return {"model_file": str(mdl), "artifacts": copied, "log_tail": log[-4000:]}


def _qc_model_name(qc_path: Path) -> str:
    for line in qc_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().lower().startswith("$modelname"):
            value = line.split('"')[1]
            return Path(value.replace("\\", "/")).stem
    raise ValueError(f"QC has no $modelname directive: {qc_path}")


def process_model_instances(
    project_root: str | Path,
    rows: Iterable[dict],
    output_dir: str | Path,
    toolchain: dict | None = None,
    progress: Callable[[str], None] | None = None,
    manifest_name: str = "model_pipeline_manifest.json",
) -> dict:
    """Resolve, export and compile unique referenced models; return model-path mappings."""
    root, out = Path(project_root), Path(output_dir)
    tools = toolchain or {}
    blender = str(tools.get("blender", "")).strip()
    studiomdl = str(tools.get("studiomdl", "")).strip()
    game_dir = str(tools.get("game_dir", "")).strip()
    rows = list(rows)
    usages: dict[str, set[str]] = {}
    for row in rows:
        ref = str(row.get("source_model", "")).strip()
        if ref:
            usages.setdefault(ref, set()).add(str(row.get("source_entity_class", "prop_static")).lower())

    result = {"models": [], "compiled_models": {}, "warnings": [], "errors": []}
    source_root = out / "models" / "s2_import"
    source_root.mkdir(parents=True, exist_ok=True)

    for index, (ref, classes) in enumerate(sorted(usages.items(), key=lambda item: item[0].lower()), 1):
        if progress:
            progress(f"Model pipeline [{index}/{len(usages)}]: resolving {ref}")
        source, matches = find_model_source(root, ref)
        record = {
            "source_model": ref,
            "source_file": str(source) if source else None,
            "candidate_files": [str(p) for p in matches],
            "usages": sorted(classes),
            "status": "source_missing" if source is None else "source_found",
            "compiled": {},
        }
        if source is None:
            result["warnings"].append(f"No editable .dmx or .fbx source found for {ref}.")
            result["models"].append(record)
            continue
        if len(matches) > 1:
            result["warnings"].append(
                f"Multiple source files match {ref}; using {source.name}. Candidates: "
                + ", ".join(p.name for p in matches)
            )
        if not blender:
            record["status"] = "awaiting_blender_path"
            result["warnings"].append(
                f"Found {source.name} for {ref}, but Blender is not configured; SMD/QC export was skipped."
            )
            result["models"].append(record)
            continue

        base = f"{safe_name(ref)}_{model_key(ref)}"
        try:
            smd, export_info = export_smd_with_blender(blender, source, source_root, base)
            record["smd_file"] = str(smd)
            record["blender"] = export_info
            record["status"] = "smd_exported"
        except Exception as exc:
            record["status"] = "blender_failed"
            record["error"] = str(exc)
            result["errors"].append(f"{ref}: {exc}")
            result["models"].append(record)
            continue

        variants = set()
        if classes & {"prop_static"}:
            variants.add("static")
        if classes & {"prop_dynamic", "prop_dynamic_override", "prop_physics", "prop_physics_override", "prop_physics_multiplayer"}:
            variants.add("dynamic")
        if not variants:
            variants.add("static")

        for variant in sorted(variants):
            model_name = f"{base}_{variant}"
            qc = write_qc(
                source_root / f"{model_name}.qc", model_name, smd.name,
                static_prop=(variant == "static"), collision=True,
            )
            record.setdefault("qc_files", []).append(str(qc))
            if not studiomdl or not game_dir:
                result["warnings"].append(
                    f"Exported {smd.name} and {qc.name}, but studiomdl and/or the CS:S game directory "
                    "is not configured; compilation was skipped."
                )
                continue
            try:
                compiled = compile_qc(studiomdl, game_dir, qc, out)
                record["compiled"][variant] = compiled
                record["status"] = "compiled"
                result["compiled_models"].setdefault(ref, {})[variant] = (
                    f"models/s2_import/{model_name}.mdl"
                )
            except Exception as exc:
                record["status"] = "compile_failed"
                record.setdefault("errors", []).append(str(exc))
                result["errors"].append(f"{ref} ({variant}): {exc}")
        result["models"].append(record)

    out.mkdir(parents=True, exist_ok=True)
    (out / manifest_name).write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


def build_prop_entities(rows: Iterable[dict], compiled_models: dict, warnings: list[str] | None = None) -> list[dict]:
    """Create VMF prop entities only for compiled models and usable placement records.

    VMAP position and angle values are passed through unchanged for this initial
    integration. A real-map Hammer comparison is still required to certify axis
    conventions and rotation order.
    """
    warnings = warnings if warnings is not None else []
    entities = []
    for row in rows:
        ref = str(row.get("source_model", ""))
        classname = str(row.get("source_entity_class", "prop_static")).lower()
        if classname not in SUPPORTED_PROP_CLASSES:
            classname = "prop_static"
        variant = "static" if classname == "prop_static" else "dynamic"
        model = compiled_models.get(ref, {}).get(variant)
        if not model:
            continue
        origin = row.get("origin") or []
        angles = row.get("angles") or []
        scales = row.get("scales") or []
        if len(origin) < 3 or len(angles) < 3 or any(v is None for v in origin[:3] + angles[:3]):
            warnings.append(f"Skipped {ref} instance {row.get('element_index')}: missing origin or angles.")
            continue
        try:
            xyz = [float(v) for v in origin[:3]]
            pyr = [float(v) for v in angles[:3]]
            scale = [float(v) for v in (scales[:3] if len(scales) >= 3 else [1, 1, 1])]
        except (TypeError, ValueError):
            warnings.append(f"Skipped {ref} instance {row.get('element_index')}: non-numeric transform.")
            continue
        if any(abs(value - 1.0) > 1e-5 for value in scale):
            warnings.append(
                f"Skipped {ref} instance {row.get('element_index')}: non-unit scale {scale} "
                "must be baked into a per-scale model variant for CS:S; no entity scale key is emitted."
            )
            continue
        entity = {
            "id": str(100000 + len(entities)),
            "classname": classname,
            "origin": " ".join(f"{v:.6g}" for v in xyz),
            "angles": " ".join(f"{v:.6g}" for v in pyr),
            "model": model,
            "solid": str(row.get("solid") if row.get("solid") not in (None, "") else "6"),
            "disableshadows": ("1" if row.get("disableshadows") is True else "0" if row.get("disableshadows") is False else str(row.get("disableshadows") or "0")),
        }
        skin = row.get("skin")
        if skin not in (None, ""):
            try:
                entity["skin"] = str(int(skin))
            except (TypeError, ValueError):
                warnings.append(f"Ignored non-numeric skin value {skin!r} on {ref} instance {row.get('element_index')}.")
        rendercolor = row.get("rendercolor")
        if rendercolor not in (None, ""):
            if isinstance(rendercolor, (list, tuple)):
                channels = [str(value) for value in rendercolor]
            else:
                channels = str(rendercolor).replace(",", " ").replace("[", " ").replace("]", " ").split()
            if len(channels) >= 3:
                entity["rendercolor"] = " ".join(channels[:3])
        # Preserve common Source 1 prop keyvalues that are otherwise lost when
        # the Source 2 entity is replaced by a compiled CS:S model instance.
        for key in ("targetname", "parentname", "spawnflags", "renderamt",
                    "rendermode", "renderfx", "rendertocubemaps", "materialoverride"):
            value = row.get(key)
            if isinstance(value, bool):
                entity[key] = "1" if value else "0"
            elif isinstance(value, (str, int, float)) and str(value).strip():
                entity[key] = str(value)
        # Model props can be I/O targets too. Preserve their structured outputs
        # and let the shared VMF entity writer serialize the connections block.
        props = row.get("entity_properties")
        node_attrs = row.get("entity_node_attributes")
        if isinstance(props, dict) or isinstance(node_attrs, dict):
            from .entity_conversion import _find_connections, _connection_fields
            connection_source = {"entity_properties": props or {}, "entity_node_attributes": node_attrs or {}}
            connections = []
            for connection in _find_connections(connection_source):
                parsed = _connection_fields(connection)
                if parsed: connections.append(parsed)
            if connections:
                entity["__connections__"] = connections
        entities.append(entity)
    return entities
