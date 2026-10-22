"""Inventory model assets and placement candidates in an editable Source 2 VMAP.

This is a schema-discovery step for model export: it reports explicit .vmdl paths,
model/instance-like DMX elements, their transforms, and resolved element references.
It does not write VMF props until the placement schema is confirmed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from s2css.dmx_binary import DMXError, parse_binary_v9


TRANSFORM_KEYS = {
    "origin", "angles", "rotation", "scales", "scale", "transform",
    "position", "orientation", "localtransform", "worldtransform",
}
MODEL_KEYS = {
    "model", "modelname", "modelpath", "modeldoc", "modelasset",
    "assetpath", "modelreference", "instance", "instancedata",
}


def safe_value(value: Any, elements: list[dict], depth: int = 0) -> Any:
    """Resolve DMX element references while keeping output JSON-serializable."""
    if depth > 8:
        return "<max-depth>"
    if isinstance(value, dict):
        if isinstance(value.get("element_index"), int):
            idx = value["element_index"]
            if 0 <= idx < len(elements):
                element = elements[idx]
                return {
                    "element_index": idx,
                    "type": element.get("type"),
                    "name": element.get("name"),
                    "guid": element.get("guid"),
                    "attributes": {
                        str(k): safe_value(v, elements, depth + 1)
                        for k, v in element.get("attributes", {}).items()
                        if str(k).lower() in TRANSFORM_KEYS | MODEL_KEYS
                        or _contains_model_path(v)
                    },
                }
            return dict(value, resolution_error="element index out of range")
        return {str(k): safe_value(v, elements, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [safe_value(v, elements, depth + 1) for v in value]
    return value


def _contains_model_path(value: Any) -> bool:
    if isinstance(value, str):
        return value.replace("\\", "/").lower().endswith(".vmdl")
    if isinstance(value, dict):
        return any(_contains_model_path(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_model_path(v) for v in value)
    return False


def _collect_model_paths(value: Any, paths: list[str]) -> None:
    if isinstance(value, str):
        normalized = value.replace("\\", "/").strip()
        if normalized.lower().endswith(".vmdl"):
            paths.append(normalized)
    elif isinstance(value, dict):
        for child in value.values():
            _collect_model_paths(child, paths)
    elif isinstance(value, list):
        for child in value:
            _collect_model_paths(child, paths)


def inventory_models(vmap_path: Path) -> dict:
    graph = parse_binary_v9(vmap_path, include_binary=False)
    elements = graph.get("elements", [])
    rows = []
    all_paths = set()

    for index, element in enumerate(elements):
        attrs = element.get("attributes", {})
        paths: list[str] = []
        _collect_model_paths(attrs, paths)
        all_paths.update(paths)

        typ = str(element.get("type", ""))
        name = str(element.get("name", ""))
        key_names = [str(k) for k in attrs if str(k).lower() in MODEL_KEYS | TRANSFORM_KEYS]
        is_candidate = bool(paths) or any(
            token in typ.lower() or token in name.lower()
            for token in ("model", "instance", "staticprop", "prop")
        ) or any(k.lower() in MODEL_KEYS for k in attrs)
        if not is_candidate:
            continue

        transforms = {
            str(k): safe_value(v, elements)
            for k, v in attrs.items()
            if str(k).lower() in TRANSFORM_KEYS
        }
        model_related = {
            str(k): safe_value(v, elements)
            for k, v in attrs.items()
            if str(k).lower() in MODEL_KEYS or _contains_model_path(v)
        }
        rows.append({
            "element_index": index,
            "type": typ,
            "name": name,
            "guid": element.get("guid"),
            "model_paths": sorted(set(paths)),
            "transform_attributes": transforms,
            "model_related_attributes": model_related,
            "candidate_attribute_names": key_names,
        })

    return {
        "source_file": str(vmap_path),
        "element_count": len(elements),
        "unique_vmdl_path_count": len(all_paths),
        "model_paths": sorted(all_paths),
        "candidate_count": len(rows),
        "model_instance_candidates": rows,
        "note": (
            "Inventory only. Candidate elements may be model definitions rather than placed instances. "
            "Confirm instance class, asset path, coordinate space, rotation representation, and scale "
            "before generating prop_static entities."
        ),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vmap", type=Path, help="Editable binary-DMX .vmap, not .vmap_c")
    parser.add_argument("--output", type=Path, help="JSON report path (default: <map>_models_report.json)")
    args = parser.parse_args(argv)
    if not args.vmap.is_file():
        parser.error(f"VMAP file not found: {args.vmap}")
    output = args.output or args.vmap.with_name(args.vmap.stem + "_models_report.json")
    try:
        report = inventory_models(args.vmap)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except (OSError, DMXError, ValueError, TypeError, KeyError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Model inventory written: {output}")
    print(f"Unique .vmdl paths: {report['unique_vmdl_path_count']}")
    print(f"Model/instance candidates: {report['candidate_count']}")
    print("This is a diagnostic inventory; no VMF props were created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
