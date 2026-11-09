"""Source 2 VMAP entity and I/O conversion helpers."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any
from .entity_substitutions import substitute_entity_class, summarize_substitutions

_ALIASES = {
    "m_targetname": "targetname", "m_name": "targetname",
    "m_origin": "origin", "m_angles": "angles", "m_classname": "classname",
    "m_model": "model", "m_parentname": "parentname",
    "m_rendercolor": "rendercolor", "m_renderamt": "renderamt",
    "m_spawnflags": "spawnflags", "m_startdisabled": "StartDisabled", "m_flstartdisabled": "StartDisabled", "m_bstartdisabled": "StartDisabled",
    "m_rendermode": "rendermode", "m_renderfx": "renderfx",
    "m_disableshadows": "disableshadows", "m_rendertocubemaps": "rendertocubemaps",
    "m_materialoverride": "materialoverride", "m_solid": "solid", "m_skin": "skin",
    "m_skyname": "skyname", "m_detailmaterial": "detailmaterial",
    "m_detailvbsp": "detailvbsp", "m_maxpropscreenwidth": "maxpropscreenwidth",
}
_SKIP = {"classname", "m_editoronly", "editoronly", "m_editorclass", "m_classname",
         "m_connections", "connections", "outputs", "outputconnections",
         "m_entityname", "m_entityid", "m_entityproperties"}
_ALLOWED_PREFIXES = ("logic_", "trigger_", "func_", "info_", "point_", "env_",
                     "filter_", "path_", "move_", "game_", "npc_", "weapon_", "light_", "prop_")
_ALLOWED_EXACT = {"light", "ambient_generic", "prop_detail",
                  "prop_static", "prop_dynamic", "prop_dynamic_override",
                  "prop_physics", "prop_physics_override", "prop_physics_multiplayer", "light_environment", "light_dynamic"}

def _scalar(value: Any) -> str | None:
    if isinstance(value, bool): return "1" if value else "0"
    if isinstance(value, (str, int, float)): return str(value)
    if isinstance(value, (list, tuple)) and len(value) in (2, 3, 4) and all(isinstance(x, (int, float)) for x in value):
        return " ".join(str(x) for x in value)
    return None

def _norm_key(key: str) -> str:
    return _ALIASES.get(key.strip().lower(), key[2:] if key.lower().startswith("m_") else key)

def _find_connections(value: Any):
    found = []
    def visit(node):
        if isinstance(node, dict):
            attrs = node.get("attributes") if isinstance(node.get("attributes"), dict) else {}
            merged = dict(attrs)
            merged.update(node)
            lowered = {str(k).lower(): v for k, v in merged.items()}
            if any(k in lowered for k in ("output", "outputname", "m_outputname")) and any(
                k in lowered for k in ("target", "targetname", "m_targetname", "m_target", "input", "inputname", "m_inputname")
            ):
                found.append(merged)
                return
            for key, child in node.items():
                output_key = str(key)
                if output_key.lower().startswith("on"):
                    if isinstance(child, str):
                        parts = child.split(",", 4)
                        if len(parts) >= 2:
                            found.append({
                                "output": output_key, "target": parts[0].strip(),
                                "input": parts[1].strip(),
                                "parameter": parts[2].strip() if len(parts) > 2 else "",
                                "delay": parts[3].strip() if len(parts) > 3 else "0",
                                "times_to_fire": parts[4].strip() if len(parts) > 4 else "-1",
                            })
                    elif isinstance(child, dict):
                        mapped = dict(child)
                        mapped.setdefault("output", output_key)
                        lowered_child = {str(k).lower() for k in mapped}
                        if any(k in lowered_child for k in ("target", "targetname", "m_targetname", "m_target")) and any(
                            k in lowered_child for k in ("input", "inputname", "m_inputname")
                        ):
                            found.append(mapped)
                        else:
                            visit(child)
                    elif isinstance(child, list):
                        for item in child:
                            if isinstance(item, str):
                                parts = item.split(",", 4)
                                if len(parts) >= 2:
                                    found.append({
                                        "output": output_key, "target": parts[0].strip(),
                                        "input": parts[1].strip(),
                                        "parameter": parts[2].strip() if len(parts) > 2 else "",
                                        "delay": parts[3].strip() if len(parts) > 3 else "0",
                                        "times_to_fire": parts[4].strip() if len(parts) > 4 else "-1",
                                    })
                            elif isinstance(item, (dict, list)): visit(item)
                elif isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(node, list):
            for child in node: visit(child)
    visit(value)
    return found

def _connection_fields(record: dict) -> dict | None:
    low = {str(k).lower(): v for k, v in record.items()}
    def get(*keys, default=""):
        for key in keys:
            if key in low: return low[key]
        return default
    output = get("output", "outputname", "m_outputname")
    target = get("target", "targetname", "m_targetname", "m_target")
    input_name = get("input", "inputname", "m_inputname")
    if not all(isinstance(x, str) and x.strip() for x in (output, target, input_name)): return None
    parameter = get("parameter", "param", "m_parameter", "parameteroverride", "m_overrideparam")
    delay = get("delay", "m_delay", "m_fldelay", default=0)
    times = get("times_to_fire", "timesfired", "m_times_to_fire", "m_ntimestofire", default=-1)
    return {"output": output, "target": target, "input": input_name,
            "parameter": _scalar(parameter) or "", "delay": _scalar(delay) or "0",
            "times": _scalar(times) or "-1"}

def _find_model_value(props: dict) -> bool:
    return any(str(k).lower() in {"model", "m_model"} and isinstance(v, str) and ".vmdl" in v.lower()
               for k, v in props.items())

def build_entity_conversion(records: list[dict], substitutions: dict[str, str] | None = None) -> dict:
    entities, skipped, unsupported_properties, model_prop_connections = [], [], [], []
    substitution_diagnostics = []
    worldspawn_properties = {}
    known_targets = set()
    for record in records:
        if record.get("class") != "CMapEntity": continue
        props = record.get("entity_properties")
        if not isinstance(props, dict): continue
        lowered_props = {str(k).lower(): v for k, v in props.items()}
        for key in ("targetname", "m_targetname", "name", "m_name"):
            value = lowered_props.get(key)
            if isinstance(value, str) and value.strip():
                known_targets.add(value.strip().casefold())
    for record in records:
        if record.get("class") != "CMapEntity": continue
        props = record.get("entity_properties")
        if not isinstance(props, dict): continue
        node_attrs = record.get("entity_node_attributes")
        if isinstance(node_attrs, dict):
            # Node-level properties can contain outputs/connections on some VMAP versions.
            for key, value in node_attrs.items():
                if key not in props and key.lower() in {"connections", "outputs", "m_connections", "outputconnections"}:
                    props[key] = value
        lowered_props = {str(k).lower(): v for k, v in props.items()}
        raw_class = lowered_props.get("classname", lowered_props.get("m_classname", ""))
        classname = str(raw_class).strip().lower()
        if not classname: continue
        source_classname = classname
        classname, substitution = substitute_entity_class(classname, props, substitutions)
        if substitution:
            substitution_diagnostics.append({"element_index": record.get("index"), **substitution})
        if substitution and substitution.get("status") == "rejected":
            skipped.append({"element_index": record.get("index"), "classname": source_classname,
                            "reason": substitution.get("reason", "Entity substitution rejected.")})
            continue
        if classname == "worldspawn":
            for key, value in props.items():
                normalized = _norm_key(str(key))
                if str(key).lower() in _SKIP or normalized.lower() in _SKIP:
                    continue
                scalar = _scalar(value)
                if scalar is not None and normalized.lower() not in {"id", "classname"}:
                    worldspawn_properties[normalized] = scalar
            continue
        if not (classname in _ALLOWED_EXACT or classname.startswith(_ALLOWED_PREFIXES)):
            skipped.append({"element_index": record.get("index"), "classname": classname,
                            "reason": "Class is not in the conservative Source 1 passthrough allowlist."})
            continue
        if classname.startswith("prop_") and _find_model_value(props):
            prop_connections = []
            for connection in _find_connections(props):
                parsed = _connection_fields(connection)
                if parsed: prop_connections.append(parsed)
            if prop_connections:
                model_prop_connections.append({
                    "element_index": record.get("index"),
                    "targetname": lowered_props.get("targetname", lowered_props.get("m_targetname", lowered_props.get("m_name", ""))),
                    "connections": prop_connections,
                })
            continue
        if _find_model_value(props):
            skipped.append({"element_index": record.get("index"), "classname": classname,
                            "reason": "Source 2 model-backed non-prop entity requires a dedicated brush/model conversion."})
            continue
        keys = {"id": str(2000000 + int(record.get("index") or 0)), "classname": classname}
        if record.get("origin") is not None: keys["origin"] = _scalar(record["origin"]) or ""
        if record.get("angles") is not None: keys["angles"] = _scalar(record["angles"]) or ""
        for key, value in props.items():
            normalized = _norm_key(str(key))
            if str(key).lower() in _SKIP or normalized.lower() in _SKIP: continue
            if normalized.lower() in {"origin", "angles", "model"} and classname.startswith("prop_"): continue
            scalar = _scalar(value)
            if scalar is None or normalized.lower() in {"id", "classname"}: continue
            if normalized.lower() == "materialoverride" and ".vmat" in scalar.lower():
                material_path = scalar.replace(chr(92), "/").lstrip("/")
                if material_path.lower().startswith("materials/"):
                    material_path = material_path[10:]
                for suffix in (".vmat_c", ".vmat", ".vmt"):
                    if material_path.lower().endswith(suffix):
                        material_path = material_path[:-len(suffix)]
                        break
                if not material_path.lower().startswith("s2_import/"):
                    material_path = "s2_import/" + material_path
                scalar = material_path
            if str(key).lower().startswith("m_") and str(key).lower() not in _ALIASES:
                unsupported_properties.append({"element_index": record.get("index"), "classname": classname, "property": str(key), "value": scalar})
                continue
            keys[normalized] = scalar
        connections = []
        for connection in _find_connections(props):
            parsed = _connection_fields(connection)
            if parsed: connections.append(parsed)
        if connections: keys["__connections__"] = connections
        entities.append(keys)
    unresolved_connections = []
    special_targets = {"!activator", "!caller", "!self", "!player", "!pvsplayer"}
    all_connection_sources = [(entity.get("targetname", ""), entity.get("__connections__", [])) for entity in entities]
    all_connection_sources += [(item.get("targetname", ""), item.get("connections", [])) for item in model_prop_connections]
    for source_name, source_connections in all_connection_sources:
        for connection in source_connections:
            target = connection["target"].strip()
            if target.lower() not in special_targets and target.casefold() not in known_targets:
                unresolved_connections.append({
                    "source_targetname": source_name,
                    "output": connection["output"], "target": target,
                    "input": connection["input"],
                })
    return {"entities": entities, "skipped_entities": skipped, "unsupported_properties": unsupported_properties,
            "unresolved_connections": unresolved_connections,
            "worldspawn_properties": worldspawn_properties,
            "model_prop_connections": model_prop_connections,
            "model_prop_connection_count": sum(len(item.get("connections", [])) for item in model_prop_connections),
            "known_targetname_count": len(known_targets),
            "entity_count": len(entities),
            "entity_substitutions": summarize_substitutions(substitution_diagnostics),
            "connection_count": sum(len(e.get("__connections__", [])) for e in entities) + sum(len(item.get("connections", [])) for item in model_prop_connections)}

def append_worldspawn_properties(vmf_path, properties: dict) -> int:
    """Merge safe Source 1 worldspawn keyvalues into the VMF's existing world block."""
    if not properties:
        return 0
    path = Path(vmf_path)
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"(?m)^world\s*$", text)
    if not match:
        return 0
    opening = text.find("{", match.end())
    if opening < 0:
        return 0
    depth, in_string, escaped, closing = 0, False, False, -1
    for index in range(opening, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                closing = index
                break
    if closing < 0:
        return 0
    block = text[opening + 1:closing]
    changed = 0
    for key, value in properties.items():
        safe_key = str(key).replace('"', '\\"')
        safe_value = str(value).replace("\\", "/").replace('"', '\\"').replace("\n", " ")
        pattern = re.compile(r'(?m)^(\s*)"' + re.escape(safe_key) + r'"\s+"[^"]*"\s*$')
        replacement = f'    "{safe_key}" "{safe_value}"'
        if pattern.search(block):
            block = pattern.sub(lambda _match: replacement, block, count=1)
        else:
            block += f'\n{replacement}\n'
        changed += 1
    path.write_text(text[:opening + 1] + block + text[closing:], encoding="utf-8")
    return changed


def append_entity_blocks(vmf_path, entities: list[dict]) -> int:
    count = 0
    with open(vmf_path, "a", encoding="utf-8", newline="\n") as handle:
        for entity in entities:
            connections = entity.get("__connections__", [])
            handle.write("entity\n{\n")
            for key, value in entity.items():
                if key == "__connections__":
                    continue
                escaped_key = str(key).replace('"', '\\"')
                escaped_value = str(value).replace("\\", "/").replace('"', '\\"').replace("\n", " ")
                handle.write(f' "{escaped_key}" "{escaped_value}"\n')
            if connections:
                handle.write(" connections\n {\n")
                for connection in connections:
                    value = ",".join((
                        connection["target"], connection["input"], connection["parameter"],
                        connection["delay"], connection["times"],
                    ))
                    handle.write(f'  "{connection["output"]}" "{value}"\n')
                handle.write(" }\n")
            handle.write("}\n")
            count += 1
    return count
