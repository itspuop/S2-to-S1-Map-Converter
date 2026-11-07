import tempfile
import unittest
from pathlib import Path

from s2css.model_pipeline import (
    build_prop_entities,
    find_model_source,
    safe_name,
    write_qc,
)


class ModelPipelineTests(unittest.TestCase):
    def test_resolves_exact_relative_dmx_before_fbx(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "models/props").mkdir(parents=True)
            dmx = root / "models/props/crate.dmx"
            fbx = root / "models/props/crate.fbx"
            dmx.write_bytes(b"dmx")
            fbx.write_bytes(b"fbx")
            chosen, candidates = find_model_source(root, "models/props/crate.vmdl")
            self.assertEqual(chosen, dmx)
            self.assertEqual(len(candidates), 2)

    def test_finds_lod0_dmx_with_model_name_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "models/props").mkdir(parents=True)
            lod0 = root / "models/props/coral_3_1_scale2_bg_body_lod0.dmx"
            lod1 = root / "models/props/coral_3_1_scale2_bg_body_lod1.dmx"
            lod0.write_bytes(b"lod0")
            lod1.write_bytes(b"lod1")
            chosen, matches = find_model_source(root, "models/props/coral_3_1_scale2_bg.vmdl")
            self.assertEqual(chosen, lod0)
            self.assertEqual(len(matches), 2)

    def test_finds_by_stem_when_source_tree_layout_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "exported").mkdir()
            fbx = root / "exported/Crate.FBX"
            fbx.write_bytes(b"fbx")
            chosen, _ = find_model_source(root, "models/props/crate.vmdl")
            self.assertEqual(chosen, fbx)

    def test_qc_has_staticprop_and_collision_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            qc = write_qc(Path(tmp) / "crate.qc", "crate_static", "crate.smd", True)
            text = qc.read_text(encoding="utf-8")
            self.assertIn('$modelname "models/s2_import/crate_static.mdl"', text)
            self.assertIn("$staticprop", text)
            self.assertIn('$cdmaterials "s2_import"', text)
            self.assertIn('$collisionmodel "crate.smd"', text)

    def test_builds_entity_only_for_compiled_model_with_unit_scale(self):
        rows = [{
            "source_model": "models/props/crate.vmdl",
            "source_entity_class": "prop_static",
            "element_index": 10,
            "origin": [1, 2, 3],
            "angles": [0, 90, 0],
            "scales": [1, 1, 1],
            "skin": "1",
        }]
        compiled = {"models/props/crate.vmdl": {"static": "models/s2_import/crate_static.mdl"}}
        warnings = []
        entities = build_prop_entities(rows, compiled, warnings)
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]["origin"], "1 2 3")
        self.assertEqual(entities[0]["skin"], "1")
        self.assertEqual(entities[0]["model"], "models/s2_import/crate_static.mdl")

    def test_non_unit_scale_is_skipped_for_css(self):
        rows = [{
            "source_model": "models/props/crate.vmdl",
            "source_entity_class": "prop_static",
            "origin": [1, 2, 3], "angles": [0, 0, 0], "scales": [2, 2, 2],
        }]
        compiled = {"models/props/crate.vmdl": {"static": "models/s2_import/crate_static.mdl"}}
        warnings = []
        self.assertEqual(build_prop_entities(rows, compiled, warnings), [])
        self.assertTrue(warnings)


if __name__ == "__main__":
    unittest.main()
