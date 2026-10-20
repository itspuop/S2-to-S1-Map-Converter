import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from s2css.mesh_schema import _shape, inspect_mesh_schema


class MeshSchemaShapeTests(unittest.TestCase):
    def setUp(self):
        self.elements = [
            {"type": "CMapMesh", "name": "mesh_a", "guid": "mesh-guid",
             "attributes": {"meshData": {"element_index": 1}, "origin": [1.0, 2.0, 3.0]}},
            {"type": "CDmePolygonMesh", "name": "poly_a", "guid": "poly-guid",
             "attributes": {"faceEdgeIndices": [0, 1, 2], "vertexData": {"element_index": 2}}},
            {"type": "CDmeVertexData", "name": "verts", "guid": "vert-guid",
             "attributes": {"data": {"binary_bytes": 64, "hex": None}}},
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

    def test_inspector_reports_mesh_and_vertex_data_schema(self):
        graph = {"format": "vmap", "format_version": 40, "elements": self.elements}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.vmap"
            path.write_bytes(b"fixture")
            with patch("s2css.mesh_schema.parse_binary_v9", return_value=graph):
                report = inspect_mesh_schema(path)
        self.assertEqual(report["cmapmesh_count"], 1)
        self.assertEqual(report["mesh_related_element_count"], 3)
        self.assertFalse(report["interpretation"]["vmf_brush_ready"])
        mesh_node = report["mesh_nodes"][0]
        self.assertEqual(mesh_node["attributes"]["meshData"]["type"], "CDmePolygonMesh")


if __name__ == "__main__":
    unittest.main()
