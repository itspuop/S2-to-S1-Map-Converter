import unittest

from s2css.mesh_schema import _shape


class MeshSchemaShapeTests(unittest.TestCase):
    def setUp(self):
        self.elements = [
            {"type": "CMapMesh", "name": "mesh_a"},
            {"type": "CDmePolygonMesh", "name": "poly_a"},
        ]

    def test_element_reference_is_resolved_for_report(self):
        self.assertEqual(
            _shape({"element_index": 1}, self.elements),
            {"reference": 1, "type": "CDmePolygonMesh", "name": "poly_a"},
        )

    def test_invalid_reference_is_flagged(self):
        self.assertEqual(
            _shape({"element_index": 9}, self.elements),
            {"reference": 9, "invalid": True},
        )

    def test_binary_payload_reports_length_not_contents(self):
        self.assertEqual(
            _shape({"binary_bytes": 2048, "hex": None}, self.elements),
            {"binary_bytes": 2048},
        )

    def test_large_array_is_summarized(self):
        result = _shape(list(range(20)), self.elements)
        self.assertEqual(result["array_length"], 20)
        self.assertEqual(result["sample"], [0, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()
