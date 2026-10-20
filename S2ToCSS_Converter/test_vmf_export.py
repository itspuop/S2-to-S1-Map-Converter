import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from s2css.vmf_export import MeshExportError, export_decoded_mesh, validate_convex_brush


CUBE = {
    "origin": [100, 200, 300],
    "angles": [0, 0, 0],
    "scales": [1, 1, 1],
    "positions_local": [
        [-1, -1, 1], [1, -1, 1], [-1, 1, 1], [1, 1, -1],
        [-1, 1, -1], [1, 1, 1], [1, -1, -1], [-1, -1, -1],
    ],
    "face_loops": [
        [0, 1, 5, 2], [4, 3, 6, 7], [4, 7, 0, 2],
        [5, 1, 6, 3], [3, 4, 2, 5], [1, 0, 7, 6],
    ],
}


class VmfExportTests(unittest.TestCase):
    def test_closed_cube_exports_world_brush(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "cube.vmf"
            report = export_decoded_mesh(CUBE, output)
            vmf = output.read_text(encoding="utf-8")
            self.assertTrue(report["valid"])
            self.assertEqual(report["vertex_count"], 8)
            self.assertEqual(report["face_count"], 6)
            self.assertIn('"classname" "worldspawn"', vmf)
            self.assertIn('"plane" "(99 199 301)', vmf)
            self.assertEqual(vmf.count('  side\n  {'), 6)
            self.assertLess(vmf.index('world\n{'), vmf.index('solid\n{'))
            self.assertTrue(vmf.rstrip().endswith("}"))

    def test_open_mesh_is_rejected(self):
        with self.assertRaises(MeshExportError):
            export_decoded_mesh({
                "positions_local": [[0,0,0],[1,0,0],[0,1,0]],
                "face_loops": [[0,1,2]],
            }, Path("unused.vmf"))

    def test_bad_vertex_index_is_rejected(self):
        with self.assertRaises(MeshExportError):
            export_decoded_mesh({
                "positions_local": [[0,0,0],[1,0,0],[0,1,0]],
                "face_loops": [[0,1,8]],
            }, Path("unused.vmf"))

    def test_transform_origin_is_applied(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "cube.vmf"
            export_decoded_mesh(CUBE, output)
            vmf = output.read_text(encoding="utf-8")
            self.assertIn("(99 199 301)", vmf)


if __name__ == "__main__":
    unittest.main()
