"""Source 2 VMAP entity and I/O conversion helpers."""
from __future__ import annotations
from typing import Any

_ALIASES = {
    "m_targetname": "targetname", "m_name": "targetname",
    "m_origin": "origin", "m_angles": "angles", "m_classname": "classname",
    "m_model": "model", "m_parentname": "parentname",
    "m_rendercolor": "rendercolor", "m_renderamt": "renderamt",
    "m_spawnflags": "spawnflags", "m_startdisabled": "StartDisabled", "m_flstartdisabled": "StartDisabled",
}
_SKIP = {"classname", "m_editoronly", "editoronly", "m_editorclass", "m_classname",
         "m_connections", "connections", "outputs", "outputconnections",
         "m_entityname", "m_entityid", "m_entityproperties"}
_ALLOWED_PREFIXES = ("logic_", "trigger_", "func_", "info_", "point_", "env_",
                     "filter_", "path_", "move_", "game_", "npc_", "weapon_", "light_", "prop_")
_ALLOWED_EXACT = {"light", "worldspawn", "ambient_generic", "prop_detail",
                  "prop_static", "prop_dynamic", "prop_dynamic_override",
                  "prop_physics", "prop_physics_override", "prop_physics_multiplayer"}

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
            for child in node.values():
                if isinstance(child, (dict, list)): visit(child)
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

def build_entity_conversion(records: list[dict]) -> dict:
    entities, skipped, unsupported_properties, model_prop_connections = [], [], [], []
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
        keys = {"id": str(2000000 + int(record.get("index") or 0)), "classname": classname}
        if record.get("origin") is not None: keys["origin"] = _scalar(record["origin"]) or ""
        if record.get("angles") is not None: keys["angles"] = _scalar(record["angles"]) or ""
        for key, value in props.items():
            normalized = _norm_key(str(key))
            if str(key).lower() in _SKIP or normalized.lower() in _SKIP: continue
            if normalized.lower() in {"origin", "angles", "model"} and classname.startswith("prop_"): continue
            scalar = _scalar(value)
            if scalar is None or normalized.lower() in {"id", "classname"}: continue
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
            "model_prop_connections": model_prop_connections,
            "model_prop_connection_count": sum(len(item.get("connections", [])) for item in model_prop_connections),
            "known_targetname_count": len(known_targets),
            "entity_count": len(entities),
            "connection_count": sum(len(e.get("__connections__", [])) for e in entities) + sum(len(item.get("connections", [])) for item in model_prop_connections)}

def append_entity_blocks(vmf_path, entities: list[dict]) -> int:
    count = 0
    with open(vmf_path, "a", encoding="utf-8", newline="\n") as handle:
        for entity in entities:
            connections = entity.get("__connections__", [])
            handle.write("entity\n{\n")
            for key, value in entity.items():
                if key == "__connections__": continue
                escaped_key = str(key).replace('"', '\\"')
                escaped_value = str(value).replace('"', '\\"')
                handle.write(f' "{escaped_key}" "{escaped_value}"\n')
            if connections:
                handle.write(" connections\n {\n")
                for c in connections:
                    value = ",".join((c["target"], c["input"], c["parameter"], c["delay"], c["times"]))
                    handle.write(f'  "{c["output"]}" "{value}"\n')
                handle.write(" }\n")
            handle.write("}\n")
            count += 1
    return count
