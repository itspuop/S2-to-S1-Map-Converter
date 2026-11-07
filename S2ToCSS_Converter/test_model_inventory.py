import tempfile
import unittest
from pathlib import Path

from s2css.model_inventory import build_model_instance_inventory, write_model_instance_inventory


class ModelInventoryTests(unittest.TestCase):
    def test_extracts_model_path_and_preserves_transform(self):
        inventory = {
            "file": "surf_test.vmap",
            "dmx_transform_records": [{
                "index": 42,
                "class": "CMapEntity",
                "name": "prop_crate",
                "guid": "guid-42",
                "origin": [10, 20, 30],
                "angles": [0, 90, 0],
                "scales": [1, 1, 1],
                "entity_properties_class": "CMapEntity",
                "entity_properties": {
                    "classname": "prop_static",
                    "model": "models/props/crate.vmdl",
                },
            }],
        }
        rows = build_model_instance_inventory(inventory)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_model"], "models/props/crate.vmdl")
        self.assertEqual(rows[0]["origin"], [10, 20, 30])
        self.assertEqual(rows[0]["angles"], [0, 90, 0])
        self.assertEqual(rows[0]["mapping_status"], "unmapped")

    def test_ignores_non_model_properties(self):
        inventory = {"dmx_transform_records": [{
            "class": "CMapEntity",
            "entity_properties": {"classname": "light_omni", "intensity": 100},
        }]}
        self.assertEqual(build_model_instance_inventory(inventory), [])

    def test_writes_json_and_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [{
                "source_map": "map.vmap", "element_index": 1,
                "source_node_class": "CMapEntity", "source_node_name": "crate",
                "source_node_guid": "g", "entity_properties_class": "CMapEntity",
                "source_model": "models/crate.vmdl", "origin": [1, 2, 3],
                "angles": [4, 5, 6], "scales": [1, 1, 1],
                "source1_model": "", "mapping_status": "unmapped", "notes": "",
            }]
            jp, cp = write_model_instance_inventory(rows, tmp, "map")
            self.assertTrue(jp.exists())
            self.assertTrue(cp.exists())
            self.assertIn("models/crate.vmdl", jp.read_text(encoding="utf-8"))
            self.assertIn("origin_x", cp.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
