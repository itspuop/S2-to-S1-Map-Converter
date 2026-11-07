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
        # DMX properties sometimes contain a path embedded in a longer string.
        for match in re.findall(
            r"(?i)(?:[a-z0-9_ .()\-]+/)*[a-z0-9_ .()\-]+\.vmdl(?:_c)?",
            normalized,
        ):
            path = match.strip().strip('"').replace("\\", "/")
            if _MODEL_SUFFIX.search(path):
                found.add(path)
    return sorted(found, key=str.lower)


def build_model_instance_inventory(vmap_inventory: dict) -> list[dict]:
    """Return entity instances that expose a model path and a transform."""
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
        for path in paths:
            rows.append({
                "source_map": vmap_inventory.get("file", ""),
                "element_index": record.get("index"),
                "source_node_class": record.get("class", ""),
                "source_node_name": record.get("name", ""),
                "source_node_guid": record.get("guid", ""),
                "entity_properties_class": record.get("entity_properties_class", ""),
                "source_model": path,
                "origin": origin,
                "angles": angles,
                "scales": scales,
                "source1_model": "",
                "mapping_status": "unmapped",
                "notes": "Transform values are copied from the VMAP DMX inventory; axis/angle conversion is not yet validated.",
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
        "source_node_guid", "entity_properties_class", "source_model",
        "origin_x", "origin_y", "origin_z", "pitch", "yaw", "roll",
        "scale_x", "scale_y", "scale_z", "source1_model", "mapping_status", "notes",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            origin = (list(row.get("origin") or []) + [None] * 3)[:3]
            angles = (list(row.get("angles") or []) + [None] * 3)[:3]
            scales = (list(row.get("scales") or []) + [None] * 3)[:3]
            writer.writerow({
                **{key: row.get(key, "") for key in fields if key not in {
                    "origin_x", "origin_y", "origin_z", "pitch", "yaw", "roll",
                    "scale_x", "scale_y", "scale_z"}},
                "origin_x": origin[0], "origin_y": origin[1], "origin_z": origin[2],
                "pitch": angles[0], "yaw": angles[1], "roll": angles[2],
                "scale_x": scales[0], "scale_y": scales[1], "scale_z": scales[2],
            })
    return json_path, csv_path
