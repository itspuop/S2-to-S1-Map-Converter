import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from s2css.entity_conversion import build_entity_conversion, append_entity_blocks, append_worldspawn_properties

class EntityConversionTests(unittest.TestCase):
    def test_converts_logic_entity_and_structured_output(self):
        records = [{
            "index": 12, "class": "CMapEntity", "origin": [1, 2, 3], "angles": [0, 90, 0],
            "entity_properties": {
                "classname": "logic_relay", "targetname": "relay_start", "StartDisabled": False,
            },
            "entity_node_attributes": {
                "connections": [{"type": "DmeConnection", "attributes": {
                    "m_outputName": "OnTrigger", "m_targetName": "door_1", "m_inputName": "Open",
                    "m_overrideParam": "", "m_flDelay": 0.25, "m_nTimesToFire": -1,
                }}],
            },
        }]
        result = build_entity_conversion(records)
        self.assertEqual(result["entity_count"], 1)
        self.assertEqual(result["connection_count"], 1)
        self.assertEqual(len(result["unresolved_connections"]), 1)
        entity = result["entities"][0]
        self.assertEqual(entity["classname"], "logic_relay")
        self.assertEqual(entity["origin"], "1 2 3")
        self.assertEqual(entity["__connections__"][0]["output"], "OnTrigger")
        with TemporaryDirectory() as tmp:
            vmf = Path(tmp) / "entities.vmf"
            vmf.write_text("world\\n{\\n}\\n", encoding="utf-8")
            append_entity_blocks(vmf, result["entities"])
            text = vmf.read_text(encoding="utf-8")
            self.assertIn('"targetname" "relay_start"', text)
            self.assertIn('"OnTrigger" "door_1,Open,,0.25,-1"', text)

    def test_does_not_emit_duplicate_worldspawn(self):
        result = build_entity_conversion([{
            "index": 2, "class": "CMapEntity",
            "entity_properties": {"classname": "worldspawn", "m_skyname": "sky_day01_01"},
        }])
        self.assertEqual(result["entity_count"], 0)
        self.assertEqual(result["worldspawn_properties"]["skyname"], "sky_day01_01")

    def test_merges_worldspawn_keyvalues_into_existing_world_block(self):
        with TemporaryDirectory() as tmp:
            vmf = Path(tmp) / "world.vmf"
            vmf.write_text('world\n{\n "id" "1"\n "classname" "worldspawn"\n}\n', encoding="utf-8")
            count = append_worldspawn_properties(vmf, {"skyname": "sky_day01_01", "maxpropscreenwidth": "-1"})
            self.assertEqual(count, 2)
            text = vmf.read_text(encoding="utf-8")
            self.assertIn('"skyname" "sky_day01_01"', text)
            self.assertIn('"maxpropscreenwidth" "-1"', text)

    def test_parses_legacy_output_key_to_connection_string(self):
        records = [{
            "index": 15, "class": "CMapEntity",
            "entity_properties": {
                "classname": "logic_relay", "targetname": "relay_start",
                "connections": {"OnTrigger": "door_1,Open,,0.5,-1"},
            },
        }]
        result = build_entity_conversion(records)
        self.assertEqual(result["connection_count"], 1)
        self.assertEqual(result["entities"][0]["__connections__"][0]["delay"], "0.5")

    def test_skips_unknown_class_and_model_backed_prop(self):
        records = [
            {"index": 1, "class": "CMapEntity", "entity_properties": {"classname": "cs2_only_thing"}},
            {"index": 2, "class": "CMapEntity", "entity_properties": {"classname": "prop_static", "model": "models/a.vmdl", "targetname": "prop_a", "connections": [{"output": "OnBreak", "target": "relay_a", "input": "Trigger"}]}},
        ]
        result = build_entity_conversion(records)
        self.assertEqual(result["entity_count"], 0)
        self.assertEqual(len(result["skipped_entities"]), 1)
        self.assertEqual(result["model_prop_connection_count"], 1)
        self.assertEqual(len(result["unresolved_connections"]), 1)

if __name__ == "__main__":
    unittest.main()
