"""Model-instance inventory helpers for editable Source 2 VMAPs.

This stage inventories model-backed CMapEntity nodes without guessing at
Source 2 -> Source 1 coordinate conversion or claiming that Source 1 MDLs
have been compiled. It produces a stable handoff for the manual model pipeline.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable

_MODEL_SUFFIX = re.compile(r"(?i)\.vmdl(?:_c)?$")


def _find_model_paths(value: Any) -> list[str]:
    """Find VM(D)L references inside nested resolved DMX entity properties."""
    found: set[str] = set()
    if isinstance(value, dict):
        for child in value.values():
            found.update(_find_model_paths(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            found.update(_find_model_paths(child))
    elif isinstance(value, str):
        normalized = value.strip().replace("\\", "/")
        for match in re.findall(
            r"(?i)(?:[a-z0-9_ .()\-]+/)*[a-z0-9_ .()\-]+\.vmdl(?:_c)?",
            normalized,
        ):
            path = match.strip().strip('"').replace("\\", "/")
            if _MODEL_SUFFIX.search(path):
                found.add(path)
    return sorted(found, key=str.lower)


def build_model_instance_inventory(vmap_inventory: dict) -> list[dict]:
    """Return model-backed CMapEntity instances with their original VMAP metadata."""
    rows: list[dict] = []
    for record in vmap_inventory.get("dmx_transform_records", []):
        properties = record.get("entity_properties")
        if not isinstance(properties, (dict, list)):
            continue

        paths = _find_model_paths(properties)
        if not paths:
            continue

        origin = list(record.get("origin") or [])[:3]
        angles = list(record.get("angles") or [])[:3]
        scales = list(record.get("scales") or [])[:3]
        origin += [None] * (3 - len(origin))
        angles += [None] * (3 - len(angles))
        scales += [None] * (3 - len(scales))

        # The current VMAP schema stores the Hammer entity classname and model
        # path as ordinary properties on EditGameClassProps.
        props = properties if isinstance(properties, dict) else {}
        prop_lookup = {str(key).lower(): value for key, value in props.items()}
        def prop_value(*keys):
            return next((prop_lookup[key.lower()] for key in keys if key.lower() in prop_lookup), "")
        entity_class = prop_value("classname", "m_classname")
        model_property = prop_value("model", "m_model")
        if not isinstance(model_property, str):
            model_property = ""

        for path in paths:
            rows.append({
                "source_map": vmap_inventory.get("file", ""),
                "element_index": record.get("index"),
                "source_node_class": record.get("class", ""),
                "source_node_name": record.get("name", ""),
                "source_node_guid": record.get("guid", ""),
                "entity_properties_class": record.get("entity_properties_class", ""),
                "source_entity_class": entity_class,
                "source_model_property": model_property,
                "source_model": path,
                "origin": origin,
                "angles": angles,
                "scales": scales,
                "entity_properties": props,
                "entity_node_attributes": record.get("entity_node_attributes", {}),
                "targetname": prop_value("targetname", "m_targetname", "name", "m_name"),
                "parentname": prop_value("parentname", "m_parentname"),
                "spawnflags": prop_value("spawnflags", "m_spawnflags"),
                "skin": prop_value("skin", "m_skin"),
                "solid": prop_value("solid", "m_solid"),
                "rendercolor": prop_value("rendercolor", "m_rendercolor"),
                "renderamt": prop_value("renderamt", "m_renderamt"),
                "rendermode": prop_value("rendermode", "m_rendermode"),
                "renderfx": prop_value("renderfx", "m_renderfx"),
                "disableshadows": prop_value("disableshadows", "m_disableshadows"),
                "rendertocubemaps": prop_value("rendertocubemaps", "m_rendertocubemaps"),
                "materialoverride": prop_value("materialoverride", "m_materialoverride"),
                "source1_model": "",
                "mapping_status": "unmapped",
                "notes": "Raw VMAP transform and entity properties preserved; Source 1 axis/angle conversion and model mapping are not yet validated.",
            })
    return rows


def write_model_instance_inventory(rows: Iterable[dict], output_dir: str | Path, map_stem: str) -> tuple[Path, Path]:
    """Write JSON and spreadsheet-friendly CSV model placement inventories."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{map_stem}_model_instances.json"
    csv_path = out / f"{map_stem}_model_instances.csv"
    rows = list(rows)
    json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    fields = [
        "source_map", "element_index", "source_node_class", "source_node_name",
        "source_node_guid", "entity_properties_class", "source_entity_class",
        "source_model_property", "source_model", "origin_x", "origin_y", "origin_z",
        "pitch", "yaw", "roll", "scale_x", "scale_y", "scale_z", "skin", "solid",
        "targetname", "parentname", "spawnflags", "rendercolor", "renderamt", "rendermode", "renderfx",
        "disableshadows", "rendertocubemaps", "materialoverride",
        "source1_model", "mapping_status", "notes",
    ]
    vector_fields = {
        "origin_x", "origin_y", "origin_z", "pitch", "yaw", "roll",
        "scale_x", "scale_y", "scale_z",
    }
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            origin = (list(row.get("origin") or []) + [None] * 3)[:3]
            angles = (list(row.get("angles") or []) + [None] * 3)[:3]
            scales = (list(row.get("scales") or []) + [None] * 3)[:3]
            values = {key: row.get(key, "") for key in fields if key not in vector_fields}
            values.update({
                "origin_x": origin[0], "origin_y": origin[1], "origin_z": origin[2],
                "pitch": angles[0], "yaw": angles[1], "roll": angles[2],
                "scale_x": scales[0], "scale_y": scales[1], "scale_z": scales[2],
            })
            writer.writerow(values)
    return json_path, csv_path
