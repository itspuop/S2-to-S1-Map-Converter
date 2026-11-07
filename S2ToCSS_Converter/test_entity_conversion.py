import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from s2css.entity_conversion import build_entity_conversion, append_entity_blocks

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

    def test_skips_unknown_class_and_model_backed_prop(self):
        records = [
            {"index": 1, "class": "CMapEntity", "entity_properties": {"classname": "cs2_only_thing"}},
            {"index": 2, "class": "CMapEntity", "entity_properties": {"classname": "prop_static", "model": "models/a.vmdl"}},
        ]
        result = build_entity_conversion(records)
        self.assertEqual(result["entity_count"], 0)
        self.assertEqual(len(result["skipped_entities"]), 1)

if __name__ == "__main__":
    unittest.main()
