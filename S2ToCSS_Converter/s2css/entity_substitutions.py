"""Configurable Source 2 -> Source 1 entity-class substitutions.

Mappings are intentionally conservative: omni lights become point lights; spot
lights become spot lights. A class is only substituted when the replacement is
a known Source 1 class. Project-local JSON may override or extend the defaults.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import json
from typing import Any

DEFAULT_SUBSTITUTIONS = {
    "light_omni2": "light",
    "light_spot2": "light_spot",
    "light_environment2": "light_environment",
}

SOURCE1_LIGHT_CLASSES = {
    "light", "light_spot", "light_environment", "light_dynamic",
}


def load_entity_substitutions(project_root: str | Path | None = None) -> dict[str, str]:
    """Load optional project overrides from entity_substitutions.json."""
    mappings = dict(DEFAULT_SUBSTITUTIONS)
    if project_root is None:
        return mappings
    config = Path(project_root) / "entity_substitutions.json"
    if not config.is_file():
        return mappings
    try:
        data = json.loads(config.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return mappings
    if isinstance(data, dict):
        data = data.get("substitutions", data)
    if isinstance(data, dict):
        for source, target in data.items():
            if isinstance(source, str) and isinstance(target, str) and source.strip() and target.strip():
                mappings[source.strip().lower()] = target.strip().lower()
    return mappings


def substitute_entity_class(
    classname: str,
    properties: dict[str, Any] | None = None,
    mappings: dict[str, str] | None = None,
) -> tuple[str, dict[str, str] | None]:
    """Return (Source 1 classname, diagnostic) without guessing unsupported semantics."""
    source = str(classname or "").strip().lower()
    table = mappings if mappings is not None else DEFAULT_SUBSTITUTIONS
    target = table.get(source)
    if not target:
        return source, None
    target = str(target).strip().lower()
    # Guard against a bad custom mapping silently creating a non-Source-1 classname.
    if not target or not (target in SOURCE1_LIGHT_CLASSES or target.startswith((
        "logic_", "trigger_", "func_", "info_", "point_", "env_", "filter_",
        "path_", "move_", "game_", "npc_", "weapon_", "light_", "prop_",
    ))):
        return source, {"source": source, "requested_target": target,
                        "status": "rejected", "reason": "Replacement is outside the conservative Source 1 class allowlist."}
    note = None
    if source == "light_omni2" and target == "light_spot":
        note = "An omni light has no cone direction; light_spot is only valid when a user explicitly overrides this mapping."
    if source == "light_spot2" and target == "light":
        note = "Spotlight cone behavior is lost when mapped to a point light."
    return target, {
        "source": source, "target": target, "status": "substituted",
        "note": note or "Class-name substitution applied; verify Source 1 keyvalue semantics in Hammer.",
    }


def summarize_substitutions(diagnostics: list[dict]) -> dict:
    counts = Counter(
        f"{item.get('source')} -> {item.get('target')}"
        for item in diagnostics if item.get("status") == "substituted"
    )
    return {"count": sum(counts.values()), "by_mapping": dict(sorted(counts.items())),
            "diagnostics": diagnostics}
