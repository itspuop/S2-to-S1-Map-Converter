"""Best-effort Source 2 VMAT -> Source 1 VMT conversion.

Source 2 shader graphs are not one-to-one with Source 1. Recognized parameters are
translated explicitly; unsupported inputs are reported instead of guessed.
"""
from __future__ import annotations
import re, shutil, subprocess
from pathlib import Path
from typing import Any

_TOKEN = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|[{}]|[^\s{}]+')
_TEXTURE_KEYS = {
    "g_tcolor": "$basetexture", "g_tcolor1": "$basetexture",
    "g_tnormal": "$bumpmap", "g_tnormalmap": "$bumpmap",
    "g_tselfillummask": "$selfillummask", "g_temissive": "$selfillummask",
    "g_tambientocclusion": "$ambientocclusiontexture",
    "g_troughness": "$phongexponenttexture", "g_tmetalness": "$metalness",
    "g_tdetail": "$detail",
}
_SCALAR_KEYS = {
    "g_flalphatestreference": "$alphatestreference",
    "g_falpha_test_reference": "$alphatestreference",
    "g_flselfillum": "$selfillum", "g_fltranslucent": "$translucent",
    "g_flphong": "$phong", "g_flfresnelreflection": "$envmapfresnel",
}
_BOOL_KEYS = {"g_balphatest": "$alphatest", "g_btranslucent": "$translucent",
              "g_bselfillum": "$selfillum", "g_bphong": "$phong"}

def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return bytes(value[1:-1], "utf-8").decode("unicode_escape")
    return value

def parse_keyvalues(text: str) -> dict[str, Any]:
    tokens = [_unquote(t) for t in _TOKEN.findall(text)
              if not t.startswith("//") and not t.startswith("/*")]
    pos = 0
    def block(expect_close: bool = False) -> dict[str, Any]:
        nonlocal pos
        result: dict[str, Any] = {}
        while pos < len(tokens):
            token = tokens[pos]
            if token == "}":
                if not expect_close: raise ValueError("Unexpected closing brace")
                pos += 1
                return result
            if token == "{": raise ValueError("Unexpected opening brace without a key")
            key = token
            pos += 1
            if pos >= len(tokens): break
            if tokens[pos] == "{":
                pos += 1
                value = block(True)
            else:
                value = tokens[pos]
                pos += 1
            if key in result:
                if not isinstance(result[key], list): result[key] = [result[key]]
                result[key].append(value)
            else: result[key] = value
        if expect_close: raise ValueError("Unclosed block")
        return result
    return block()

def _walk(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}/{key}" if prefix else key
            yield path, key, child
            yield from _walk(child, path)
    elif isinstance(value, list):
        for child in value: yield from _walk(child, prefix)

def _truth(value: Any) -> str:
    value = str(value).strip().lower()
    return "1" if value in {"1", "true", "yes", "on"} else "0" if value in {"0", "false", "no", "off"} else str(value)

def _texture_reference(value: Any) -> str:
    path = str(value).strip().replace("\\", "/").strip('"')
    path = re.sub(r"(?i)^materials/", "", path)
    path = re.sub(r"(?i)\.(vtex|vtex_c|tga|png|jpg|jpeg|psd|vtf)$", "", path)
    return path.strip("/")

def _resolve_vmat(root: Path, ref: str) -> Path | None:
    rel = ref.replace("\\", "/").lstrip("/")
    if rel.lower().startswith("materials/"): rel = rel[10:]
    rel = re.sub(r"(?i)\.vmat(?:_c)?$", ".vmat", rel)
    direct = root / rel
    if direct.is_file(): return direct
    stem = Path(rel).stem.lower()
    matches = [p for p in root.rglob("*.vmat") if p.stem.lower() == stem]
    return sorted(matches, key=lambda p: (len(p.parts), str(p).lower()))[0] if matches else None

def _convert_texture(source_ref: str, source_root: Path, output_root: Path,
                     vtfcmd: str, warnings: list[str]) -> bool:
    rel = _texture_reference(source_ref)
    if not rel: return False
    candidates = [source_root / (rel + ext) for ext in (".tga", ".png", ".jpg", ".jpeg", ".psd", ".vtf")]
    source = next((p for p in candidates if p.is_file()), None)
    if source is None:
        candidates = [source_root / (rel + ext) for ext in (".vtex", ".vtex_c")]
        source = next((p for p in candidates if p.is_file()), None)
    if source is None:
        warnings.append(f"Missing texture source for {source_ref}")
        return False
    target = output_root / (rel + ".vtf")
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() == ".vtf":
        if source.resolve() != target.resolve(): shutil.copy2(source, target)
        return True
    if source.suffix.lower() in {".vtex", ".vtex_c"}:
        warnings.append(f"{source.name}: VTEX extraction is not supported here; supply its loose raster source.")
        return False
    if not vtfcmd or not Path(vtfcmd).is_file():
        shutil.copy2(source, target.with_suffix(source.suffix))
        warnings.append(f"VTFCmd not configured; copied loose texture {source.name} without VTF conversion.")
        return False
    try:
        proc = subprocess.run([vtfcmd, "-file", str(source), "-output", str(target.parent)],
                              capture_output=True, text=True, check=False)
        generated = target.parent / (source.stem + ".vtf")
        if proc.returncode != 0 or not generated.is_file():
            warnings.append(f"VTFCmd failed for {source}: {(proc.stderr or proc.stdout)[-500:]}")
            return False
        if generated != target and generated.exists(): generated.replace(target)
        return target.is_file()
    except OSError as exc:
        warnings.append(f"Could not run VTFCmd for {source}: {exc}")
        return False

def convert_vmat_file(vmat_path: Path, materials_root: Path, output_root: Path,
                      vtfcmd: str = "", brush_material: bool = True) -> dict:
    warnings: list[str] = []
    source_text = vmat_path.read_text(encoding="utf-8-sig", errors="replace")
    tree = parse_keyvalues(source_text)
    flat = list(_walk(tree))
    shader = next((str(v) for _, k, v in flat if k.lower() in {"shader", "m_shadername"} and isinstance(v, str)), "unknown")
    shader_low = shader.lower()
    vmt_shader = "LightmappedGeneric" if brush_material else "VertexLitGeneric"
    if any(x in shader_low for x in ("unlit", "postprocess", "particle", "ui")):
        vmt_shader = "UnlitGeneric"
    params: dict[str, str] = {}
    unknown: list[dict] = []
    texture_values = []
    for path, key, value in flat:
        low = key.lower()
        if isinstance(value, (dict, list)): continue
        if low in _TEXTURE_KEYS:
            tex = _texture_reference(value)
            if tex:
                params[_TEXTURE_KEYS[low]] = tex
                texture_values.append(str(value))
        elif low in _SCALAR_KEYS:
            params[_SCALAR_KEYS[low]] = _truth(value)
        elif low in _BOOL_KEYS:
            params[_BOOL_KEYS[low]] = _truth(value)
        elif low in {"shader", "m_shadername", "m_nodename", "m_editorclass"}:
            continue
        elif low.startswith(("g_t", "g_fl", "g_b", "g_v", "g_c")):
            unknown.append({"key": path, "value": value})
    if "$basetexture" not in params:
        warnings.append(f"{vmat_path.name}: no recognized base-color texture parameter; VMT may render as a fallback.")
    for texture in dict.fromkeys(texture_values):
        _convert_texture(texture, materials_root, output_root, vtfcmd, warnings)
    vmt_path = output_root / vmat_path.relative_to(materials_root).with_suffix(".vmt")
    vmt_path.parent.mkdir(parents=True, exist_ok=True)
    params.setdefault("$surfaceprop", "default")
    lines = [f'"{vmt_shader}"', "{"]
    lines += [f'    "{k}" "{v}"' for k, v in sorted(params.items())]
    lines.append("}")
    vmt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"source_vmat": str(vmat_path), "output_vmt": str(vmt_path),
            "shader_source": shader, "shader_target": vmt_shader,
            "parameters": params, "unknown_parameters": unknown, "warnings": warnings}

def convert_vmat_references(material_refs: list[str], materials_root: Path,
                            output_materials_root: Path, vtfcmd: str = "") -> dict:
    results, missing, warnings = [], [], []
    for ref in sorted(set(material_refs), key=str.lower):
        source = _resolve_vmat(materials_root, ref)
        if source is None:
            missing.append(ref)
            continue
        try:
            result = convert_vmat_file(source, materials_root, output_materials_root, vtfcmd)
            results.append(result)
            warnings.extend(result["warnings"])
        except Exception as exc:
            warnings.append(f"VMAT conversion failed for {ref}: {exc}")
    return {"converted_count": len(results), "missing_vmat": missing,
            "results": results, "warnings": warnings,
            "limitations": ["Source 2 shader graphs are approximated by a Source 1 shader family.",
                            "Unsupported VMAT parameters are reported, not silently translated.",
                            "Compiled .vtex_c extraction and shader-specific procedural features require separate handling."]}
