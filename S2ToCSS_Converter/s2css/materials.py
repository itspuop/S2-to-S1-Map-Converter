"""Best-effort Source 2 VMAT -> Source 1 VMT conversion.

Source 2 shader graphs are not one-to-one with Source 1. Recognized parameters are
translated explicitly; unsupported inputs are reported instead of guessed.
"""
from __future__ import annotations
import re, shutil, subprocess
from pathlib import Path
from typing import Any

_TOKEN = re.compile(r'<!--[\s\S]*?-->|//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|[{}\[\]=,]|[^\s{}\[\]=,"]+')

def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value

def parse_keyvalues(text: str) -> dict[str, Any]:
    """Parse legacy KeyValues and the assignment/array subset of text KV3 VMATs."""
    tokens = [_unquote(t) for t in _TOKEN.findall(text)
              if not t.startswith("//") and not t.startswith("/*") and not t.startswith("<!--")]
    pos = 0
    def value():
        nonlocal pos
        if pos >= len(tokens): return ""
        token = tokens[pos]
        if token == "{":
            pos += 1
            return mapping("}")
        if token == "[":
            pos += 1
            values = []
            while pos < len(tokens) and tokens[pos] != "]":
                if tokens[pos] == ",": pos += 1; continue
                values.append(value())
            if pos < len(tokens) and tokens[pos] == "]": pos += 1
            return values
        pos += 1
        if token.endswith(":") and pos < len(tokens):
            token += tokens[pos]
            pos += 1
        return token
    def mapping(close: str | None = None):
        nonlocal pos
        result: dict[str, Any] = {}
        while pos < len(tokens):
            if close and tokens[pos] == close:
                pos += 1
                return result
            if tokens[pos] == ",":
                pos += 1
                continue
            key = tokens[pos]
            if key in {"}", "]", "{", "["}:
                raise ValueError(f"Unexpected token {key!r} while parsing VMAT")
            pos += 1
            if pos < len(tokens) and tokens[pos] == "=":
                pos += 1
            child = value()
            if key in result:
                if not isinstance(result[key], list): result[key] = [result[key]]
                result[key].append(child)
            else:
                result[key] = child
        if close:
            raise ValueError(f"Unclosed {close!r} block in VMAT")
        return result
    if tokens and tokens[0] == "{":
        return value()
    return mapping()

_TEXTURE_KEYS = {
    "g_tcolor": "$basetexture",
    "g_tnormal": "$bumpmap", "g_tnormalmap": "$bumpmap",
    "g_tselfillummask": "$selfillummask", "g_temissive": "$selfillummask",
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

_VECTOR_KEYS = {"g_vcolortint": "$color", "g_venvmaptint": "$envmaptint"}
_FLAG_KEYS = {"f_phong": "$phong", "f_vertex_color": "$vertexcolor",
              "f_vertex_alpha": "$vertexalpha", "f_additive": "$additive"}

def _format_parameter(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return " ".join(str(item) for item in value)
    return _truth(value)

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
    path = re.sub(r"(?i)^(resource:|file:)", "", path).strip('"')
    path = re.sub(r"(?i)^materials/", "", path)
    path = re.sub(r"(?i)\.(vtex|vtex_c|tga|png|jpg|jpeg|psd|vtf)$", "", path)
    return path.strip("/")

def _parameter_records(value: Any):
    if isinstance(value, dict):
        keys = {str(k).lower(): v for k, v in value.items()}
        name = keys.get("m_name", keys.get("name"))
        value_keys = ("m_pvalue", "m_flvalue", "m_nvalue", "m_vvalue",
                      "m_cvalue", "m_bvalue", "m_value", "value")
        selected = next((keys[k] for k in value_keys if k in keys), None)
        if isinstance(name, str) and selected is not None:
            yield name, selected
        for child in value.values():
            yield from _parameter_records(child)
    elif isinstance(value, list):
        for child in value: yield from _parameter_records(child)

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
                     vtfcmd: str, warnings: list[str], search_roots=None) -> bool:
    rel = _texture_reference(source_ref)
    if not rel: return False
    roots = [source_root] + [Path(p) for p in (search_roots or []) if Path(p) != source_root]
    source = None
    for root in roots:
        candidates = [root / (rel + ext) for ext in (".tga", ".png", ".jpg", ".jpeg", ".psd", ".vtf")]
        source = next((p for p in candidates if p.is_file()), None)
        if source is None:
            candidates = [root / (rel + ext) for ext in (".vtex", ".vtex_c")]
            source = next((p for p in candidates if p.is_file()), None)
        if source is not None: break
    if source is None:
        warnings.append(f"Missing texture source for {source_ref}")
        return False
    target = output_root / (rel + ".vtf")
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() == ".vtex":
        try:
            vtex_tree = parse_keyvalues(source.read_text(encoding="utf-8-sig", errors="replace"))
            image_refs = [str(value) for _, key, value in _walk(vtex_tree)
                          if key.lower() in {"m_filename", "filename"} and isinstance(value, str)]
            image_source = None
            for image_ref in image_refs:
                image_rel = _texture_reference(image_ref)
                for root in roots:
                    image_candidates = [root / (image_rel + ext) for ext in (".tga", ".png", ".jpg", ".jpeg", ".psd", ".vtf")]
                    image_source = next((p for p in image_candidates if p.is_file()), None)
                    if image_source is not None: break
                if image_source is not None: break
            if image_source is None:
                warnings.append(f"{source.name}: no loose image source was resolved from its VTEX document.")
                return False
            if len(image_refs) > 1:
                warnings.append(f"{source.name}: multiple VTEX input frames/layers were found; only the first resolved image is converted.")
            warnings.append(f"Resolved VTEX source {source.name} to {image_source.name}.")
            source = image_source
        except Exception as exc:
            warnings.append(f"Could not parse VTEX source {source}: {exc}")
            return False
    elif source.suffix.lower() == ".vtex_c":
        warnings.append(f"{source.name}: compiled VTEX extraction is not supported; provide the editable .vtex document or loose raster source.")
        return False
    if source.suffix.lower() == ".vtf":
        if source.resolve() != target.resolve(): shutil.copy2(source, target)
        return True
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
                      vtfcmd: str = "", brush_material: bool = True, search_roots=None) -> dict:
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
        if low in _VECTOR_KEYS:
            params[_VECTOR_KEYS[low]] = _format_parameter(value)
            continue
        if low in _FLAG_KEYS:
            params[_FLAG_KEYS[low]] = _truth(value)
            continue
        if low in {"f_alpha_test", "alpha_test"}:
            params["$alphatest"] = _truth(value)
            continue
        if low in {"f_translucent", "translucent"}:
            params["$translucent"] = _truth(value)
            continue
        if low in {"f_self_illum", "self_illum"}:
            params["$selfillum"] = _truth(value)
            continue
        if low in {"surfaceprop", "m_surfaceproperty", "m_surfacepropname"}:
            params["$surfaceprop"] = str(value)
            continue
        if isinstance(value, (dict, list)): continue
        if low in _TEXTURE_KEYS:
            tex = _texture_reference(value)
            if tex:
                params[_TEXTURE_KEYS[low]] = "s2_import/" + tex
                texture_values.append(str(value))
        elif low in _SCALAR_KEYS:
            params[_SCALAR_KEYS[low]] = _truth(value)
        elif low in _BOOL_KEYS:
            params[_BOOL_KEYS[low]] = _truth(value)
        elif low in {"shader", "m_shadername", "m_nodename", "m_editorclass"}:
            continue
        elif low.startswith(("g_t", "g_fl", "g_b", "g_v", "g_c", "f_")):
            unknown.append({"key": path, "value": value})
    # Modern text KV3 stores shader inputs as arrays of {m_name, m_pValue/...} records.
    for parameter_name, parameter_value in _parameter_records(tree):
        low = parameter_name.lower()
        if low in _TEXTURE_KEYS:
            tex = _texture_reference(parameter_value)
            if tex:
                params[_TEXTURE_KEYS[low]] = "s2_import/" + tex
                texture_values.append(str(parameter_value))
        elif low in _SCALAR_KEYS:
            params[_SCALAR_KEYS[low]] = _truth(parameter_value)
        elif low in _BOOL_KEYS:
            params[_BOOL_KEYS[low]] = _truth(parameter_value)
        elif low in _VECTOR_KEYS:
            params[_VECTOR_KEYS[low]] = _format_parameter(parameter_value)
        elif low in _FLAG_KEYS:
            params[_FLAG_KEYS[low]] = _truth(parameter_value)
        elif low in {"f_alpha_test", "alpha_test"}:
            params["$alphatest"] = _truth(parameter_value)
        elif low in {"f_translucent", "translucent"}:
            params["$translucent"] = _truth(parameter_value)
        elif low in {"f_self_illum", "self_illum"}:
            params["$selfillum"] = _truth(parameter_value)
        elif low.startswith(("g_t", "g_fl", "g_b", "g_v", "g_c", "f_")):
            unknown.append({"key": parameter_name, "value": parameter_value})
    if "$basetexture" not in params:
        warnings.append(f"{vmat_path.name}: no recognized base-color texture parameter; VMT may render as a fallback.")
    for texture in dict.fromkeys(texture_values):
        _convert_texture(texture, materials_root, output_root, vtfcmd, warnings, search_roots)
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
                            output_materials_root: Path, vtfcmd: str = "", search_roots=None) -> dict:
    results, missing, warnings = [], [], []
    roots = [materials_root] + [Path(p) for p in (search_roots or []) if Path(p) != materials_root]
    for ref in sorted(set(material_refs), key=str.lower):
        source = None
        source_root = materials_root
        for root in roots:
            source = _resolve_vmat(root, ref)
            if source is not None:
                source_root = root
                break
        if source is None:
            missing.append(ref)
            continue
        try:
            result = convert_vmat_file(source, source_root, output_materials_root, vtfcmd,
                                       search_roots=roots)
            result["source_vmat_ref"] = ref
            results.append(result)
            warnings.extend(result["warnings"])
        except Exception as exc:
            warnings.append(f"VMAT conversion failed for {ref}: {exc}")
    return {"converted_count": len(results), "missing_vmat": missing,
            "results": results, "warnings": warnings,
            "limitations": ["Source 2 shader graphs are approximated by a Source 1 shader family.",
                            "Unsupported VMAT parameters are reported, not silently translated.",
                            "Compiled .vtex_c extraction and shader-specific procedural features require separate handling."]}
