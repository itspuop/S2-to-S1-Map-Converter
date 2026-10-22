"""Recover referenced Source 2 materials into basic Source 1 VMT/VTF assets.

This is an experimental helper: Source2Viewer-CLI extracts compiled VMAT/VTEX
resources from loose files or VPKs, and VTFCmd converts exported images to VTF.
It intentionally generates conservative LightmappedGeneric materials from the
best available color/albedo texture; PBR properties are not fully translated.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def run_cli(command: list[str], label: str) -> None:
    display_command = " ".join(('"' + part + '"') if " " in part else part for part in command)
    print(f"[{label}] {display_command}", flush=True)
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    if result.stdout:
        print(result.stdout.rstrip(), flush=True)
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {result.returncode}.")


def read_report(path: Path) -> tuple[list[str], dict[str, Path]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    refs = set()
    loose_materials: dict[str, Path] = {}
    for item in data.get("material_scan", {}).get("materials", []):
        ref = item.get("vmat_path")
        if isinstance(ref, str) and ref.lower().endswith(".vmat"):
            normalized = ref.replace("\\", "/").lstrip("/")
            refs.add(normalized)
            for match in item.get("found_in", []):
                candidate = Path(match.get("path", "")) if isinstance(match, dict) else None
                if candidate and candidate.is_file() and candidate.suffix.lower() == ".vmat":
                    loose_materials[normalized] = candidate
                    break
    for mesh in data.get("meshes", []):
        for assignment in mesh.get("face_material_assignments", []):
            ref = assignment.get("source2_material")
            if isinstance(ref, str) and ref.lower().endswith(".vmat"):
                refs.add(ref.replace("\\", "/").lstrip("/"))
    return sorted(refs), loose_materials


def resource_filter(path: str, extension: str) -> str:
    clean = path.replace("\\", "/").lstrip("/")
    if clean.lower().startswith("materials/"):
        clean = clean[len("materials/"):]
    return "materials/" + str(Path(clean).with_suffix("." + extension)).replace("\\", "/")


def extract_referenced_resources(
    cli: Path,
    game_root: Path,
    refs: list[str],
    extension: str,
    output: Path,
    label: str,
) -> None:
    """Extract exact referenced resources from root-level game VPKs only.

    Do not pass the whole game folder to Source2Viewer with --recursive_vpk:
    that makes it enumerate VPKs inside map folders as well. Editable-map
    resources should be resolved from the report/loose addon files first; this
    fallback checks only the shared game VPKs directly inside game_root.
    """
    # The caller may provide either .../game or .../game/csgo.
    # Search only the supplied root and known shared-content directories;
    # never recurse into addon/map folders.
    archive_dirs = [game_root, game_root / "csgo", game_root / "core",
                    game_root / "platform"]
    archives = sorted({p.resolve() for folder in archive_dirs if folder.is_dir()
                       for p in folder.glob("*_dir.vpk")})
    if not archives:
        print(
            f"No shared *_dir.vpk archives found in {game_root} or its known game subfolders; "
            "skipping shared-VPK extraction rather than recursively scanning map folders.",
            flush=True,
        )
        return

    filters = list(dict.fromkeys(resource_filter(ref, extension) for ref in refs))
    # Keep the command line comfortably below Windows' command-length limit.
    batches: list[list[str]] = []
    batch: list[str] = []
    batch_chars = 0
    for item in filters:
        extra = len(item) + (1 if batch else 0)
        if batch and batch_chars + extra > 7000:
            batches.append(batch)
            batch = []
            batch_chars = 0
            extra = len(item)
        batch.append(item)
        batch_chars += extra
    if batch:
        batches.append(batch)

    for archive in archives:
        for batch in batches:
            run_cli([
                str(cli), "-i", str(archive),
                "--vpk_extensions", extension,
                "--vpk_filepath", ",".join(batch),
                "--vpk_decompile",
                "-o", str(output),
            ], f"{label} ({archive.name})")


def find_exported(root: Path, relative_stem: str, suffixes: tuple[str, ...]) -> Path | None:
    rel = Path(relative_stem)
    candidates = [root / rel.with_suffix(suffix) for suffix in suffixes]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    # Some CLI versions normalize output paths differently; fall back to a unique basename.
    matches = [p for p in root.rglob("*") if p.is_file() and p.stem.casefold() == rel.stem.casefold()
               and p.suffix.casefold() in suffixes]
    return matches[0] if len(matches) == 1 else None


def parse_texture_refs(vmat_text: str) -> list[tuple[str, str]]:
    """Read texture references from both legacy KV1 and Source 2 KV3 VMAT text."""
    found: list[tuple[str, str]] = []

    # KV1 form: "g_tColor" "materials/foo.vtex"
    pairs = re.findall(r'"([^"]+)"\s+"([^"]+)"', vmat_text)
    # KV3 commonly uses: g_tColor = resource:"materials/foo.vtex"
    pairs.extend(re.findall(
        r'([A-Za-z_][A-Za-z0-9_.]*)\s*=\s*(?:resource\s*:\s*)?"([^"]+)"',
        vmat_text, flags=re.I,
    ))

    for key, value in pairs:
        value = value.replace("\\", "/").strip().strip('"')
        if ".vtex" not in value.lower():
            continue
        path = value.split("?", 1)[0]
        path = re.sub(r"\.vtex_c$", ".vtex", path, flags=re.I)
        if not path.lower().startswith("materials/"):
            path = "materials/" + path.lstrip("/")
        if not path.lower().endswith(".vtex"):
            continue
        found.append((key, path))

    # Fallback for KV3 resource references that don't match the key/value patterns.
    for match in re.finditer(r'([^"\s]+\.vtex(?:_c)?)', vmat_text, re.I):
        value = match.group(1).rstrip('",;')
        path = re.sub(r"\.vtex_c$", ".vtex", value, flags=re.I)
        if not path.lower().startswith("materials/"):
            continue
        prefix = vmat_text[max(0, match.start() - 180):match.start()]
        key_match = re.search(
            r'([A-Za-z_][A-Za-z0-9_.]*)\s*=\s*(?:resource\s*:\s*)?$',
            prefix,
            re.I,
        )
        key = key_match.group(1) if key_match else "texture"
        found.append((key, path))

    return list(dict.fromkeys(found))

def choose_color_texture(refs: list[tuple[str, str]]) -> str | None:
    if not refs:
        return None
    preferred = ("color", "albedo", "basecolor", "base_color", "diffuse")
    for key, path in refs:
        if any(token in key.lower() for token in preferred):
            return path
    for _, path in refs:
        if not any(token in path.lower() for token in ("normal", "rough", "metal", "ao", "mask", "height")):
            return path
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True, help="JSON report created by the VMF exporter")
    parser.add_argument("--game-root", type=Path, required=True, help="CS2 game content folder, usually .../game/csgo")
    parser.add_argument("--source2viewer-cli", type=Path, required=True, help="Path to Source2Viewer-CLI.exe")
    parser.add_argument("--vtfcmd", type=Path, required=True, help="Path to VTFCmd.exe")
    parser.add_argument("--output-materials", type=Path, required=True, help="Source 1 materials output folder")
    parser.add_argument("--work", type=Path, help="Temporary extraction folder (defaults beside output)")
    args = parser.parse_args(argv)

    for path, label in ((args.report, "Report"), (args.source2viewer_cli, "Source2Viewer CLI"),
                        (args.vtfcmd, "VTFCmd"), (args.game_root, "CS2 game root")):
        if not path.exists():
            parser.error(f"{label} path does not exist: {path}")
    if not args.report.is_file() or not args.source2viewer_cli.is_file() or not args.vtfcmd.is_file():
        parser.error("Report and executable paths must point to files.")
    if not args.game_root.is_dir():
        parser.error(f"CS2 game root must be a folder: {args.game_root}")

    refs, loose_materials = read_report(args.report)
    if not refs:
        print("No referenced .vmat paths were found in the report.", flush=True)
        return 0

    work = args.work or (args.output_materials.parent / "_s2_material_recovery")
    extracted_materials = work / "decompiled_materials"
    extracted_textures = work / "decompiled_textures"
    extracted_materials.mkdir(parents=True, exist_ok=True)
    extracted_textures.mkdir(parents=True, exist_ok=True)
    args.output_materials.mkdir(parents=True, exist_ok=True)

    # Only inspect referenced VMATs in shared game VPKs located directly
    # under game_root; never recurse into each map's own VPK/material folders.
    vpk_material_refs = [ref for ref in refs if ref not in loose_materials]
    if vpk_material_refs:
        extract_referenced_resources(
            args.source2viewer_cli, args.game_root, vpk_material_refs,
            "vmat_c", extracted_materials, "Source 2 material extraction",
        )

    material_records = []
    texture_refs: list[tuple[str, str, str, Path]] = []
    for ref in refs:
        relative = ref[len("materials/"):] if ref.lower().startswith("materials/") else ref
        stem = str(Path(relative).with_suffix(""))
        vmat_file = loose_materials.get(ref) or find_exported(extracted_materials, stem, (".vmat",))
        if vmat_file is None:
            print(f"NOT FOUND: {ref} (not found in scanned loose/VPK assets)", flush=True)
            material_records.append({"source2_material": ref, "status": "not_found"})
            continue
        text = vmat_file.read_text(encoding="utf-8-sig", errors="replace")
        refs_for_material = parse_texture_refs(text)
        color_texture = choose_color_texture(refs_for_material)
        for key, texture_ref in refs_for_material:
            texture_refs.append((ref, key, texture_ref, vmat_file))
        material_records.append({
            "source2_material": ref,
            "status": "material_decompiled",
            "decompiled_file": str(vmat_file),
            "shader": (re.search(r'"(?:shader|m_shaderName)"\s+"([^"]+)"', text, re.I) or [None, None])[1],
            "texture_refs": [{"key": key, "path": path} for key, path in refs_for_material],
            "color_texture": color_texture,
        })

    unique_textures = sorted({path for _, _, path, _ in texture_refs})
    if unique_textures:
        extract_referenced_resources(
            args.source2viewer_cli, args.game_root, unique_textures,
            "vtex_c", extracted_textures, "Source 2 texture extraction",
        )

    converted: dict[str, str] = {}
    for texture_ref in unique_textures:
        relative = texture_ref[len("materials/"):] if texture_ref.lower().startswith("materials/") else texture_ref
        stem = str(Path(relative).with_suffix(""))
        image_path = find_exported(extracted_textures, stem, (".png", ".tga", ".jpg", ".jpeg"))
        if image_path is None:
            print(f"TEXTURE NOT FOUND: {texture_ref}", flush=True)
            continue
        target_relative = Path("s2converted") / "textures" / Path(relative).with_suffix(".vtf")
        target_file = args.output_materials / target_relative
        target_file.parent.mkdir(parents=True, exist_ok=True)
        run_cli([
            str(args.vtfcmd), "-file", str(image_path), "-output", str(target_file.parent),
            "-format", "dxt1", "-alphaformat", "dxt5", "-silent",
        ], "VTFCmd")
        expected = target_file
        if not expected.is_file():
            # VTFCmd normally preserves the input stem; normalize into the requested relative path.
            alternatives = list(target_file.parent.glob(image_path.stem + ".vtf"))
            if alternatives:
                expected = alternatives[0]
        if expected.is_file():
            converted[texture_ref] = str(target_relative.with_suffix("")).replace("\\", "/")
        else:
            print(f"VTF CONVERSION FAILED: {image_path}", flush=True)

    material_map: dict[str, str] = {}
    for record in material_records:
        if record.get("status") != "material_decompiled":
            continue
        ref = record["source2_material"]
        color = record.get("color_texture")
        if not color or color not in converted:
            record["status"] = "no_usable_color_texture"
            continue
        material_relative = Path("s2converted") / Path(
            (ref[len("materials/"):] if ref.lower().startswith("materials/") else ref)
        ).with_suffix(".vmt")
        vmt_path = args.output_materials / material_relative
        vmt_path.parent.mkdir(parents=True, exist_ok=True)
        base_texture = converted[color]
        vmt_path.write_text(
            '"LightmappedGeneric"\n{\n'
            f'    "$basetexture" "{base_texture}"\n'
            '    "$surfaceprop" "concrete"\n'
            '}\n',
            encoding="utf-8",
        )
        source1_name = str(material_relative.with_suffix("")).replace("\\", "/")
        # VMF material names omit the leading materials/ directory.
        if source1_name.lower().startswith("s2converted/"):
            source1_name = source1_name[len("s2converted/"):]
            source1_name = "s2converted/" + source1_name
        material_map[ref] = source1_name
        record["status"] = "converted"
        record["source1_material"] = source1_name
        record["vmt_file"] = str(vmt_path)
        record["vtf_file"] = str(args.output_materials / Path("s2converted") / "textures" / Path(color[len("materials/"):] if color.lower().startswith("materials/") else color).with_suffix(".vtf"))

    mapping_path = args.output_materials / "s2_material_map.json"
    mapping_path.write_text(json.dumps({"material_map": material_map}, indent=2), encoding="utf-8")
    report_path = args.output_materials / "s2_material_recovery_report.json"
    report_path.write_text(json.dumps({
        "source_report": str(args.report),
        "game_root": str(args.game_root),
        "output_materials": str(args.output_materials),
        "source2viewer_cli": str(args.source2viewer_cli),
        "vtfcmd": str(args.vtfcmd),
        "material_map_file": str(mapping_path),
        "material_map": material_map,
        "materials": material_records,
    }, indent=2), encoding="utf-8")
    print(f"Material mapping: {mapping_path}", flush=True)
    print(f"Recovery report: {report_path}", flush=True)
    print(f"Generated mappings: {len(material_map)} / {len(refs)} referenced materials", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
, '.vtex', value, flags=re.I)
        if not path.lower().startswith("materials/"):
            continue
        prefix = vmat_text[max(0, match.start() - 180):match.start()]
        key_match = re.search(
            r'([A-Za-z_][A-Za-z0-9_.]*)\\s*=\\s*(?:resource\\s*:\\s*)?$',
            prefix,
            re.I,
        )
        key = key_match.group(1) if key_match else "texture"
        found.append((key, path))

    return list(dict.fromkeys(found))


def choose_color_texture(refs: list[tuple[str, str]]) -> str | None:
    if not refs:
        return None
    preferred = ("color", "albedo", "basecolor", "base_color", "diffuse")
    for key, path in refs:
        if any(token in key.lower() for token in preferred):
            return path
    for _, path in refs:
        if not any(token in path.lower() for token in ("normal", "rough", "metal", "ao", "mask", "height")):
            return path
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True, help="JSON report created by the VMF exporter")
    parser.add_argument("--game-root", type=Path, required=True, help="CS2 game content folder, usually .../game/csgo")
    parser.add_argument("--source2viewer-cli", type=Path, required=True, help="Path to Source2Viewer-CLI.exe")
    parser.add_argument("--vtfcmd", type=Path, required=True, help="Path to VTFCmd.exe")
    parser.add_argument("--output-materials", type=Path, required=True, help="Source 1 materials output folder")
    parser.add_argument("--work", type=Path, help="Temporary extraction folder (defaults beside output)")
    args = parser.parse_args(argv)

    for path, label in ((args.report, "Report"), (args.source2viewer_cli, "Source2Viewer CLI"),
                        (args.vtfcmd, "VTFCmd"), (args.game_root, "CS2 game root")):
        if not path.exists():
            parser.error(f"{label} path does not exist: {path}")
    if not args.report.is_file() or not args.source2viewer_cli.is_file() or not args.vtfcmd.is_file():
        parser.error("Report and executable paths must point to files.")
    if not args.game_root.is_dir():
        parser.error(f"CS2 game root must be a folder: {args.game_root}")

    refs, loose_materials = read_report(args.report)
    if not refs:
        print("No referenced .vmat paths were found in the report.", flush=True)
        return 0

    work = args.work or (args.output_materials.parent / "_s2_material_recovery")
    extracted_materials = work / "decompiled_materials"
    extracted_textures = work / "decompiled_textures"
    extracted_materials.mkdir(parents=True, exist_ok=True)
    extracted_textures.mkdir(parents=True, exist_ok=True)
    args.output_materials.mkdir(parents=True, exist_ok=True)

    # Only inspect referenced VMATs in shared game VPKs located directly
    # under game_root; never recurse into each map's own VPK/material folders.
    vpk_material_refs = [ref for ref in refs if ref not in loose_materials]
    if vpk_material_refs:
        extract_referenced_resources(
            args.source2viewer_cli, args.game_root, vpk_material_refs,
            "vmat_c", extracted_materials, "Source 2 material extraction",
        )

    material_records = []
    texture_refs: list[tuple[str, str, str, Path]] = []
    for ref in refs:
        relative = ref[len("materials/"):] if ref.lower().startswith("materials/") else ref
        stem = str(Path(relative).with_suffix(""))
        vmat_file = loose_materials.get(ref) or find_exported(extracted_materials, stem, (".vmat",))
        if vmat_file is None:
            print(f"NOT FOUND: {ref} (not found in scanned loose/VPK assets)", flush=True)
            material_records.append({"source2_material": ref, "status": "not_found"})
            continue
        text = vmat_file.read_text(encoding="utf-8-sig", errors="replace")
        refs_for_material = parse_texture_refs(text)
        color_texture = choose_color_texture(refs_for_material)
        for key, texture_ref in refs_for_material:
            texture_refs.append((ref, key, texture_ref, vmat_file))
        material_records.append({
            "source2_material": ref,
            "status": "material_decompiled",
            "decompiled_file": str(vmat_file),
            "shader": (re.search(r'"(?:shader|m_shaderName)"\s+"([^"]+)"', text, re.I) or [None, None])[1],
            "texture_refs": [{"key": key, "path": path} for key, path in refs_for_material],
            "color_texture": color_texture,
        })

    unique_textures = sorted({path for _, _, path, _ in texture_refs})
    if unique_textures:
        extract_referenced_resources(
            args.source2viewer_cli, args.game_root, unique_textures,
            "vtex_c", extracted_textures, "Source 2 texture extraction",
        )

    converted: dict[str, str] = {}
    for texture_ref in unique_textures:
        relative = texture_ref[len("materials/"):] if texture_ref.lower().startswith("materials/") else texture_ref
        stem = str(Path(relative).with_suffix(""))
        image_path = find_exported(extracted_textures, stem, (".png", ".tga", ".jpg", ".jpeg"))
        if image_path is None:
            print(f"TEXTURE NOT FOUND: {texture_ref}", flush=True)
            continue
        target_relative = Path("s2converted") / "textures" / Path(relative).with_suffix(".vtf")
        target_file = args.output_materials / target_relative
        target_file.parent.mkdir(parents=True, exist_ok=True)
        run_cli([
            str(args.vtfcmd), "-file", str(image_path), "-output", str(target_file.parent),
            "-format", "dxt1", "-alphaformat", "dxt5", "-silent",
        ], "VTFCmd")
        expected = target_file
        if not expected.is_file():
            # VTFCmd normally preserves the input stem; normalize into the requested relative path.
            alternatives = list(target_file.parent.glob(image_path.stem + ".vtf"))
            if alternatives:
                expected = alternatives[0]
        if expected.is_file():
            converted[texture_ref] = str(target_relative.with_suffix("")).replace("\\", "/")
        else:
            print(f"VTF CONVERSION FAILED: {image_path}", flush=True)

    material_map: dict[str, str] = {}
    for record in material_records:
        if record.get("status") != "material_decompiled":
            continue
        ref = record["source2_material"]
        color = record.get("color_texture")
        if not color or color not in converted:
            record["status"] = "no_usable_color_texture"
            continue
        material_relative = Path("s2converted") / Path(
            (ref[len("materials/"):] if ref.lower().startswith("materials/") else ref)
        ).with_suffix(".vmt")
        vmt_path = args.output_materials / material_relative
        vmt_path.parent.mkdir(parents=True, exist_ok=True)
        base_texture = converted[color]
        vmt_path.write_text(
            '"LightmappedGeneric"\n{\n'
            f'    "$basetexture" "{base_texture}"\n'
            '    "$surfaceprop" "concrete"\n'
            '}\n',
            encoding="utf-8",
        )
        source1_name = str(material_relative.with_suffix("")).replace("\\", "/")
        # VMF material names omit the leading materials/ directory.
        if source1_name.lower().startswith("s2converted/"):
            source1_name = source1_name[len("s2converted/"):]
            source1_name = "s2converted/" + source1_name
        material_map[ref] = source1_name
        record["status"] = "converted"
        record["source1_material"] = source1_name
        record["vmt_file"] = str(vmt_path)
        record["vtf_file"] = str(args.output_materials / Path("s2converted") / "textures" / Path(color[len("materials/"):] if color.lower().startswith("materials/") else color).with_suffix(".vtf"))

    mapping_path = args.output_materials / "s2_material_map.json"
    mapping_path.write_text(json.dumps({"material_map": material_map}, indent=2), encoding="utf-8")
    report_path = args.output_materials / "s2_material_recovery_report.json"
    report_path.write_text(json.dumps({
        "source_report": str(args.report),
        "game_root": str(args.game_root),
        "output_materials": str(args.output_materials),
        "source2viewer_cli": str(args.source2viewer_cli),
        "vtfcmd": str(args.vtfcmd),
        "material_map_file": str(mapping_path),
        "material_map": material_map,
        "materials": material_records,
    }, indent=2), encoding="utf-8")
    print(f"Material mapping: {mapping_path}", flush=True)
    print(f"Recovery report: {report_path}", flush=True)
    print(f"Generated mappings: {len(material_map)} / {len(refs)} referenced materials", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
,
            prefix,
            re.I,
        )
        key = key_match.group(1) if key_match else "texture"
        found.append((key, path))

    return list(dict.fromkeys(found))


def choose_color_texture(refs: list[tuple[str, str]]) -> str | None:
    if not refs:
        return None
    preferred = ("color", "albedo", "basecolor", "base_color", "diffuse")
    for key, path in refs:
        if any(token in key.lower() for token in preferred):
            return path
    for _, path in refs:
        if not any(token in path.lower() for token in ("normal", "rough", "metal", "ao", "mask", "height")):
            return path
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True, help="JSON report created by the VMF exporter")
    parser.add_argument("--game-root", type=Path, required=True, help="CS2 game content folder, usually .../game/csgo")
    parser.add_argument("--source2viewer-cli", type=Path, required=True, help="Path to Source2Viewer-CLI.exe")
    parser.add_argument("--vtfcmd", type=Path, required=True, help="Path to VTFCmd.exe")
    parser.add_argument("--output-materials", type=Path, required=True, help="Source 1 materials output folder")
    parser.add_argument("--work", type=Path, help="Temporary extraction folder (defaults beside output)")
    args = parser.parse_args(argv)

    for path, label in ((args.report, "Report"), (args.source2viewer_cli, "Source2Viewer CLI"),
                        (args.vtfcmd, "VTFCmd"), (args.game_root, "CS2 game root")):
        if not path.exists():
            parser.error(f"{label} path does not exist: {path}")
    if not args.report.is_file() or not args.source2viewer_cli.is_file() or not args.vtfcmd.is_file():
        parser.error("Report and executable paths must point to files.")
    if not args.game_root.is_dir():
        parser.error(f"CS2 game root must be a folder: {args.game_root}")

    refs, loose_materials = read_report(args.report)
    if not refs:
        print("No referenced .vmat paths were found in the report.", flush=True)
        return 0

    work = args.work or (args.output_materials.parent / "_s2_material_recovery")
    extracted_materials = work / "decompiled_materials"
    extracted_textures = work / "decompiled_textures"
    extracted_materials.mkdir(parents=True, exist_ok=True)
    extracted_textures.mkdir(parents=True, exist_ok=True)
    args.output_materials.mkdir(parents=True, exist_ok=True)

    # Only inspect referenced VMATs in shared game VPKs located directly
    # under game_root; never recurse into each map's own VPK/material folders.
    vpk_material_refs = [ref for ref in refs if ref not in loose_materials]
    if vpk_material_refs:
        extract_referenced_resources(
            args.source2viewer_cli, args.game_root, vpk_material_refs,
            "vmat_c", extracted_materials, "Source 2 material extraction",
        )

    material_records = []
    texture_refs: list[tuple[str, str, str, Path]] = []
    for ref in refs:
        relative = ref[len("materials/"):] if ref.lower().startswith("materials/") else ref
        stem = str(Path(relative).with_suffix(""))
        vmat_file = loose_materials.get(ref) or find_exported(extracted_materials, stem, (".vmat",))
        if vmat_file is None:
            print(f"NOT FOUND: {ref} (not found in scanned loose/VPK assets)", flush=True)
            material_records.append({"source2_material": ref, "status": "not_found"})
            continue
        text = vmat_file.read_text(encoding="utf-8-sig", errors="replace")
        refs_for_material = parse_texture_refs(text)
        color_texture = choose_color_texture(refs_for_material)
        for key, texture_ref in refs_for_material:
            texture_refs.append((ref, key, texture_ref, vmat_file))
        material_records.append({
            "source2_material": ref,
            "status": "material_decompiled",
            "decompiled_file": str(vmat_file),
            "shader": (re.search(r'"(?:shader|m_shaderName)"\s+"([^"]+)"', text, re.I) or [None, None])[1],
            "texture_refs": [{"key": key, "path": path} for key, path in refs_for_material],
            "color_texture": color_texture,
        })

    unique_textures = sorted({path for _, _, path, _ in texture_refs})
    if unique_textures:
        extract_referenced_resources(
            args.source2viewer_cli, args.game_root, unique_textures,
            "vtex_c", extracted_textures, "Source 2 texture extraction",
        )

    converted: dict[str, str] = {}
    for texture_ref in unique_textures:
        relative = texture_ref[len("materials/"):] if texture_ref.lower().startswith("materials/") else texture_ref
        stem = str(Path(relative).with_suffix(""))
        image_path = find_exported(extracted_textures, stem, (".png", ".tga", ".jpg", ".jpeg"))
        if image_path is None:
            print(f"TEXTURE NOT FOUND: {texture_ref}", flush=True)
            continue
        target_relative = Path("s2converted") / "textures" / Path(relative).with_suffix(".vtf")
        target_file = args.output_materials / target_relative
        target_file.parent.mkdir(parents=True, exist_ok=True)
        run_cli([
            str(args.vtfcmd), "-file", str(image_path), "-output", str(target_file.parent),
            "-format", "dxt1", "-alphaformat", "dxt5", "-silent",
        ], "VTFCmd")
        expected = target_file
        if not expected.is_file():
            # VTFCmd normally preserves the input stem; normalize into the requested relative path.
            alternatives = list(target_file.parent.glob(image_path.stem + ".vtf"))
            if alternatives:
                expected = alternatives[0]
        if expected.is_file():
            converted[texture_ref] = str(target_relative.with_suffix("")).replace("\\", "/")
        else:
            print(f"VTF CONVERSION FAILED: {image_path}", flush=True)

    material_map: dict[str, str] = {}
    for record in material_records:
        if record.get("status") != "material_decompiled":
            continue
        ref = record["source2_material"]
        color = record.get("color_texture")
        if not color or color not in converted:
            record["status"] = "no_usable_color_texture"
            continue
        material_relative = Path("s2converted") / Path(
            (ref[len("materials/"):] if ref.lower().startswith("materials/") else ref)
        ).with_suffix(".vmt")
        vmt_path = args.output_materials / material_relative
        vmt_path.parent.mkdir(parents=True, exist_ok=True)
        base_texture = converted[color]
        vmt_path.write_text(
            '"LightmappedGeneric"\n{\n'
            f'    "$basetexture" "{base_texture}"\n'
            '    "$surfaceprop" "concrete"\n'
            '}\n',
            encoding="utf-8",
        )
        source1_name = str(material_relative.with_suffix("")).replace("\\", "/")
        # VMF material names omit the leading materials/ directory.
        if source1_name.lower().startswith("s2converted/"):
            source1_name = source1_name[len("s2converted/"):]
            source1_name = "s2converted/" + source1_name
        material_map[ref] = source1_name
        record["status"] = "converted"
        record["source1_material"] = source1_name
        record["vmt_file"] = str(vmt_path)
        record["vtf_file"] = str(args.output_materials / Path("s2converted") / "textures" / Path(color[len("materials/"):] if color.lower().startswith("materials/") else color).with_suffix(".vtf"))

    mapping_path = args.output_materials / "s2_material_map.json"
    mapping_path.write_text(json.dumps({"material_map": material_map}, indent=2), encoding="utf-8")
    report_path = args.output_materials / "s2_material_recovery_report.json"
    report_path.write_text(json.dumps({
        "source_report": str(args.report),
        "game_root": str(args.game_root),
        "output_materials": str(args.output_materials),
        "source2viewer_cli": str(args.source2viewer_cli),
        "vtfcmd": str(args.vtfcmd),
        "material_map_file": str(mapping_path),
        "material_map": material_map,
        "materials": material_records,
    }, indent=2), encoding="utf-8")
    print(f"Material mapping: {mapping_path}", flush=True)
    print(f"Recovery report: {report_path}", flush=True)
    print(f"Generated mappings: {len(material_map)} / {len(refs)} referenced materials", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
, '.vtex', value, flags=re.I)
        if not path.lower().startswith("materials/"):
            continue
        prefix = vmat_text[max(0, match.start() - 180):match.start()]
        key_match = re.search(
            r'([A-Za-z_][A-Za-z0-9_.]*)\s*=\s*(?:resource\s*:\s*)?,
            prefix,
            re.I,
        )
        key = key_match.group(1) if key_match else "texture"
        found.append((key, path))

    return list(dict.fromkeys(found))


def choose_color_texture(refs: list[tuple[str, str]]) -> str | None:
    if not refs:
        return None
    preferred = ("color", "albedo", "basecolor", "base_color", "diffuse")
    for key, path in refs:
        if any(token in key.lower() for token in preferred):
            return path
    for _, path in refs:
        if not any(token in path.lower() for token in ("normal", "rough", "metal", "ao", "mask", "height")):
            return path
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True, help="JSON report created by the VMF exporter")
    parser.add_argument("--game-root", type=Path, required=True, help="CS2 game content folder, usually .../game/csgo")
    parser.add_argument("--source2viewer-cli", type=Path, required=True, help="Path to Source2Viewer-CLI.exe")
    parser.add_argument("--vtfcmd", type=Path, required=True, help="Path to VTFCmd.exe")
    parser.add_argument("--output-materials", type=Path, required=True, help="Source 1 materials output folder")
    parser.add_argument("--work", type=Path, help="Temporary extraction folder (defaults beside output)")
    args = parser.parse_args(argv)

    for path, label in ((args.report, "Report"), (args.source2viewer_cli, "Source2Viewer CLI"),
                        (args.vtfcmd, "VTFCmd"), (args.game_root, "CS2 game root")):
        if not path.exists():
            parser.error(f"{label} path does not exist: {path}")
    if not args.report.is_file() or not args.source2viewer_cli.is_file() or not args.vtfcmd.is_file():
        parser.error("Report and executable paths must point to files.")
    if not args.game_root.is_dir():
        parser.error(f"CS2 game root must be a folder: {args.game_root}")

    refs, loose_materials = read_report(args.report)
    if not refs:
        print("No referenced .vmat paths were found in the report.", flush=True)
        return 0

    work = args.work or (args.output_materials.parent / "_s2_material_recovery")
    extracted_materials = work / "decompiled_materials"
    extracted_textures = work / "decompiled_textures"
    extracted_materials.mkdir(parents=True, exist_ok=True)
    extracted_textures.mkdir(parents=True, exist_ok=True)
    args.output_materials.mkdir(parents=True, exist_ok=True)

    # Only inspect referenced VMATs in shared game VPKs located directly
    # under game_root; never recurse into each map's own VPK/material folders.
    vpk_material_refs = [ref for ref in refs if ref not in loose_materials]
    if vpk_material_refs:
        extract_referenced_resources(
            args.source2viewer_cli, args.game_root, vpk_material_refs,
            "vmat_c", extracted_materials, "Source 2 material extraction",
        )

    material_records = []
    texture_refs: list[tuple[str, str, str, Path]] = []
    for ref in refs:
        relative = ref[len("materials/"):] if ref.lower().startswith("materials/") else ref
        stem = str(Path(relative).with_suffix(""))
        vmat_file = loose_materials.get(ref) or find_exported(extracted_materials, stem, (".vmat",))
        if vmat_file is None:
            print(f"NOT FOUND: {ref} (not found in scanned loose/VPK assets)", flush=True)
            material_records.append({"source2_material": ref, "status": "not_found"})
            continue
        text = vmat_file.read_text(encoding="utf-8-sig", errors="replace")
        refs_for_material = parse_texture_refs(text)
        color_texture = choose_color_texture(refs_for_material)
        for key, texture_ref in refs_for_material:
            texture_refs.append((ref, key, texture_ref, vmat_file))
        material_records.append({
            "source2_material": ref,
            "status": "material_decompiled",
            "decompiled_file": str(vmat_file),
            "shader": (re.search(r'"(?:shader|m_shaderName)"\s+"([^"]+)"', text, re.I) or [None, None])[1],
            "texture_refs": [{"key": key, "path": path} for key, path in refs_for_material],
            "color_texture": color_texture,
        })

    unique_textures = sorted({path for _, _, path, _ in texture_refs})
    if unique_textures:
        extract_referenced_resources(
            args.source2viewer_cli, args.game_root, unique_textures,
            "vtex_c", extracted_textures, "Source 2 texture extraction",
        )

    converted: dict[str, str] = {}
    for texture_ref in unique_textures:
        relative = texture_ref[len("materials/"):] if texture_ref.lower().startswith("materials/") else texture_ref
        stem = str(Path(relative).with_suffix(""))
        image_path = find_exported(extracted_textures, stem, (".png", ".tga", ".jpg", ".jpeg"))
        if image_path is None:
            print(f"TEXTURE NOT FOUND: {texture_ref}", flush=True)
            continue
        target_relative = Path("s2converted") / "textures" / Path(relative).with_suffix(".vtf")
        target_file = args.output_materials / target_relative
        target_file.parent.mkdir(parents=True, exist_ok=True)
        run_cli([
            str(args.vtfcmd), "-file", str(image_path), "-output", str(target_file.parent),
            "-format", "dxt1", "-alphaformat", "dxt5", "-silent",
        ], "VTFCmd")
        expected = target_file
        if not expected.is_file():
            # VTFCmd normally preserves the input stem; normalize into the requested relative path.
            alternatives = list(target_file.parent.glob(image_path.stem + ".vtf"))
            if alternatives:
                expected = alternatives[0]
        if expected.is_file():
            converted[texture_ref] = str(target_relative.with_suffix("")).replace("\\", "/")
        else:
            print(f"VTF CONVERSION FAILED: {image_path}", flush=True)

    material_map: dict[str, str] = {}
    for record in material_records:
        if record.get("status") != "material_decompiled":
            continue
        ref = record["source2_material"]
        color = record.get("color_texture")
        if not color or color not in converted:
            record["status"] = "no_usable_color_texture"
            continue
        material_relative = Path("s2converted") / Path(
            (ref[len("materials/"):] if ref.lower().startswith("materials/") else ref)
        ).with_suffix(".vmt")
        vmt_path = args.output_materials / material_relative
        vmt_path.parent.mkdir(parents=True, exist_ok=True)
        base_texture = converted[color]
        vmt_path.write_text(
            '"LightmappedGeneric"\n{\n'
            f'    "$basetexture" "{base_texture}"\n'
            '    "$surfaceprop" "concrete"\n'
            '}\n',
            encoding="utf-8",
        )
        source1_name = str(material_relative.with_suffix("")).replace("\\", "/")
        # VMF material names omit the leading materials/ directory.
        if source1_name.lower().startswith("s2converted/"):
            source1_name = source1_name[len("s2converted/"):]
            source1_name = "s2converted/" + source1_name
        material_map[ref] = source1_name
        record["status"] = "converted"
        record["source1_material"] = source1_name
        record["vmt_file"] = str(vmt_path)
        record["vtf_file"] = str(args.output_materials / Path("s2converted") / "textures" / Path(color[len("materials/"):] if color.lower().startswith("materials/") else color).with_suffix(".vtf"))

    mapping_path = args.output_materials / "s2_material_map.json"
    mapping_path.write_text(json.dumps({"material_map": material_map}, indent=2), encoding="utf-8")
    report_path = args.output_materials / "s2_material_recovery_report.json"
    report_path.write_text(json.dumps({
        "source_report": str(args.report),
        "game_root": str(args.game_root),
        "output_materials": str(args.output_materials),
        "source2viewer_cli": str(args.source2viewer_cli),
        "vtfcmd": str(args.vtfcmd),
        "material_map_file": str(mapping_path),
        "material_map": material_map,
        "materials": material_records,
    }, indent=2), encoding="utf-8")
    print(f"Material mapping: {mapping_path}", flush=True)
    print(f"Recovery report: {report_path}", flush=True)
    print(f"Generated mappings: {len(material_map)} / {len(refs)} referenced materials", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
,
            prefix,
            re.I,
        )
        key = key_match.group(1) if key_match else "texture"
        found.append((key, path))

    return list(dict.fromkeys(found))


def choose_color_texture(refs: list[tuple[str, str]]) -> str | None:
    if not refs:
        return None
    preferred = ("color", "albedo", "basecolor", "base_color", "diffuse")
    for key, path in refs:
        if any(token in key.lower() for token in preferred):
            return path
    for _, path in refs:
        if not any(token in path.lower() for token in ("normal", "rough", "metal", "ao", "mask", "height")):
            return path
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True, help="JSON report created by the VMF exporter")
    parser.add_argument("--game-root", type=Path, required=True, help="CS2 game content folder, usually .../game/csgo")
    parser.add_argument("--source2viewer-cli", type=Path, required=True, help="Path to Source2Viewer-CLI.exe")
    parser.add_argument("--vtfcmd", type=Path, required=True, help="Path to VTFCmd.exe")
    parser.add_argument("--output-materials", type=Path, required=True, help="Source 1 materials output folder")
    parser.add_argument("--work", type=Path, help="Temporary extraction folder (defaults beside output)")
    args = parser.parse_args(argv)

    for path, label in ((args.report, "Report"), (args.source2viewer_cli, "Source2Viewer CLI"),
                        (args.vtfcmd, "VTFCmd"), (args.game_root, "CS2 game root")):
        if not path.exists():
            parser.error(f"{label} path does not exist: {path}")
    if not args.report.is_file() or not args.source2viewer_cli.is_file() or not args.vtfcmd.is_file():
        parser.error("Report and executable paths must point to files.")
    if not args.game_root.is_dir():
        parser.error(f"CS2 game root must be a folder: {args.game_root}")

    refs, loose_materials = read_report(args.report)
    if not refs:
        print("No referenced .vmat paths were found in the report.", flush=True)
        return 0

    work = args.work or (args.output_materials.parent / "_s2_material_recovery")
    extracted_materials = work / "decompiled_materials"
    extracted_textures = work / "decompiled_textures"
    extracted_materials.mkdir(parents=True, exist_ok=True)
    extracted_textures.mkdir(parents=True, exist_ok=True)
    args.output_materials.mkdir(parents=True, exist_ok=True)

    # Only inspect referenced VMATs in shared game VPKs located directly
    # under game_root; never recurse into each map's own VPK/material folders.
    vpk_material_refs = [ref for ref in refs if ref not in loose_materials]
    if vpk_material_refs:
        extract_referenced_resources(
            args.source2viewer_cli, args.game_root, vpk_material_refs,
            "vmat_c", extracted_materials, "Source 2 material extraction",
        )

    material_records = []
    texture_refs: list[tuple[str, str, str, Path]] = []
    for ref in refs:
        relative = ref[len("materials/"):] if ref.lower().startswith("materials/") else ref
        stem = str(Path(relative).with_suffix(""))
        vmat_file = loose_materials.get(ref) or find_exported(extracted_materials, stem, (".vmat",))
        if vmat_file is None:
            print(f"NOT FOUND: {ref} (not found in scanned loose/VPK assets)", flush=True)
            material_records.append({"source2_material": ref, "status": "not_found"})
            continue
        text = vmat_file.read_text(encoding="utf-8-sig", errors="replace")
        refs_for_material = parse_texture_refs(text)
        color_texture = choose_color_texture(refs_for_material)
        for key, texture_ref in refs_for_material:
            texture_refs.append((ref, key, texture_ref, vmat_file))
        material_records.append({
            "source2_material": ref,
            "status": "material_decompiled",
            "decompiled_file": str(vmat_file),
            "shader": (re.search(r'"(?:shader|m_shaderName)"\s+"([^"]+)"', text, re.I) or [None, None])[1],
            "texture_refs": [{"key": key, "path": path} for key, path in refs_for_material],
            "color_texture": color_texture,
        })

    unique_textures = sorted({path for _, _, path, _ in texture_refs})
    if unique_textures:
        extract_referenced_resources(
            args.source2viewer_cli, args.game_root, unique_textures,
            "vtex_c", extracted_textures, "Source 2 texture extraction",
        )

    converted: dict[str, str] = {}
    for texture_ref in unique_textures:
        relative = texture_ref[len("materials/"):] if texture_ref.lower().startswith("materials/") else texture_ref
        stem = str(Path(relative).with_suffix(""))
        image_path = find_exported(extracted_textures, stem, (".png", ".tga", ".jpg", ".jpeg"))
        if image_path is None:
            print(f"TEXTURE NOT FOUND: {texture_ref}", flush=True)
            continue
        target_relative = Path("s2converted") / "textures" / Path(relative).with_suffix(".vtf")
        target_file = args.output_materials / target_relative
        target_file.parent.mkdir(parents=True, exist_ok=True)
        run_cli([
            str(args.vtfcmd), "-file", str(image_path), "-output", str(target_file.parent),
            "-format", "dxt1", "-alphaformat", "dxt5", "-silent",
        ], "VTFCmd")
        expected = target_file
        if not expected.is_file():
            # VTFCmd normally preserves the input stem; normalize into the requested relative path.
            alternatives = list(target_file.parent.glob(image_path.stem + ".vtf"))
            if alternatives:
                expected = alternatives[0]
        if expected.is_file():
            converted[texture_ref] = str(target_relative.with_suffix("")).replace("\\", "/")
        else:
            print(f"VTF CONVERSION FAILED: {image_path}", flush=True)

    material_map: dict[str, str] = {}
    for record in material_records:
        if record.get("status") != "material_decompiled":
            continue
        ref = record["source2_material"]
        color = record.get("color_texture")
        if not color or color not in converted:
            record["status"] = "no_usable_color_texture"
            continue
        material_relative = Path("s2converted") / Path(
            (ref[len("materials/"):] if ref.lower().startswith("materials/") else ref)
        ).with_suffix(".vmt")
        vmt_path = args.output_materials / material_relative
        vmt_path.parent.mkdir(parents=True, exist_ok=True)
        base_texture = converted[color]
        vmt_path.write_text(
            '"LightmappedGeneric"\n{\n'
            f'    "$basetexture" "{base_texture}"\n'
            '    "$surfaceprop" "concrete"\n'
            '}\n',
            encoding="utf-8",
        )
        source1_name = str(material_relative.with_suffix("")).replace("\\", "/")
        # VMF material names omit the leading materials/ directory.
        if source1_name.lower().startswith("s2converted/"):
            source1_name = source1_name[len("s2converted/"):]
            source1_name = "s2converted/" + source1_name
        material_map[ref] = source1_name
        record["status"] = "converted"
        record["source1_material"] = source1_name
        record["vmt_file"] = str(vmt_path)
        record["vtf_file"] = str(args.output_materials / Path("s2converted") / "textures" / Path(color[len("materials/"):] if color.lower().startswith("materials/") else color).with_suffix(".vtf"))

    mapping_path = args.output_materials / "s2_material_map.json"
    mapping_path.write_text(json.dumps({"material_map": material_map}, indent=2), encoding="utf-8")
    report_path = args.output_materials / "s2_material_recovery_report.json"
    report_path.write_text(json.dumps({
        "source_report": str(args.report),
        "game_root": str(args.game_root),
        "output_materials": str(args.output_materials),
        "source2viewer_cli": str(args.source2viewer_cli),
        "vtfcmd": str(args.vtfcmd),
        "material_map_file": str(mapping_path),
        "material_map": material_map,
        "materials": material_records,
    }, indent=2), encoding="utf-8")
    print(f"Material mapping: {mapping_path}", flush=True)
    print(f"Recovery report: {report_path}", flush=True)
    print(f"Generated mappings: {len(material_map)} / {len(refs)} referenced materials", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
