import unittest

from s2css.mesh_decode import decode_polygon_mesh


def triangle_graph():
    return [
        {
            "type": "CMapMesh",
            "guid": "test-guid",
            "attributes": {
                "meshData": {"element_index": 1},
                "origin": [10, 20, 30],
                "angles": [0, 0, 0],
                "scales": [1, 1, 1],
            },
        },
        {
            "type": "CDmePolygonMesh",
            "attributes": {
                "vertexData": {"element_index": 2},
                "edgeVertexIndices": [0, 1, 2],
                "edgeNextIndices": [1, 2, 0],
                "edgeFaceIndices": [0, 0, 0],
                "faceEdgeIndices": [0],
                "materials": ["materials/test.vmat"],
            },
        },
        {
            "type": "CDmePolygonMeshDataArray",
            "attributes": {"streams": [{"element_index": 3}]},
        },
        {
            "type": "CDmePolygonMeshDataStream",
            "attributes": {
                "semanticName": "position",
                "data": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
            },
        },
    ]


class MeshDecodeTests(unittest.TestCase):
    def test_decodes_positions_and_closed_face_loop(self):
        result = decode_polygon_mesh(triangle_graph(), 0)
        self.assertEqual(result["positions_local"], [[0, 0, 0], [1, 0, 0], [0, 1, 0]])
        self.assertEqual(result["faces"][0]["vertex_indices"], [0, 1, 2])
        self.assertTrue(result["faces"][0]["closed"])
        self.assertTrue(result["faces"][0]["valid"])
        self.assertEqual(result["valid_face_count"], 1)
        self.assertEqual(result["invalid_face_count"], 0)
        self.assertFalse(result["vmf_brush_ready"])

    def test_reports_non_closing_loop_invalid(self):
        graph = triangle_graph()
        graph[1]["attributes"]["edgeNextIndices"] = [1, 1, 0]
        result = decode_polygon_mesh(graph, 0)
        self.assertFalse(result["faces"][0]["valid"])
        self.assertEqual(result["invalid_face_count"], 1)

    def test_rejects_non_mesh_element(self):
        with self.assertRaises(ValueError):
            decode_polygon_mesh(triangle_graph(), 1)

    def test_rejects_missing_position_stream(self):
        graph = triangle_graph()
        graph[3]["attributes"]["semanticName"] = "normal"
        with self.assertRaises(ValueError):
            decode_polygon_mesh(graph, 0)


if __name__ == "__main__":
    unittest.main()
