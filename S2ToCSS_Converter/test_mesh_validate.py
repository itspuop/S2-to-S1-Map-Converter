import unittest
from s2css.mesh_validate import validate_decoded_mesh

def cube_decode():
    points=[[0,0,0],[1,0,0],[1,1,0],[0,1,0],[0,0,1],[1,0,1],[1,1,1],[0,1,1]]
    loops=[[0,3,2,1],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]
    return {"node_index":0,"meshdata_index":1,"origin":[10,20,30],"angles":[0,0,0],"scales":[1,1,1],
      "positions_local":points,"faces":[{"face_index":i,"vertex_indices":loop,"valid":True} for i,loop in enumerate(loops)]}

class MeshValidateTests(unittest.TestCase):
    def test_closed_cube(self):
        r=validate_decoded_mesh(cube_decode())
        self.assertTrue(r["all_faces_planar"]); self.assertTrue(r["closed_two_manifold"])
        self.assertTrue(r["all_faces_bound_convex_halfspaces"]); self.assertEqual(r["boundary_edges"],[])
        self.assertFalse(r["vmf_brush_ready"])
    def test_open_cube(self):
        d=cube_decode(); d["faces"].pop(); r=validate_decoded_mesh(d)
        self.assertFalse(r["closed_two_manifold"]); self.assertTrue(r["boundary_edges"])
    def test_nonplanar_face(self):
        d=cube_decode(); d["positions_local"][6]=[1,1,1.25]
        self.assertFalse(validate_decoded_mesh(d)["all_faces_planar"])
    def test_bad_index(self):
        d=cube_decode(); d["faces"][0]["vertex_indices"]=[0,1,99]
        self.assertFalse(validate_decoded_mesh(d)["face_reports"][0]["valid"])

if __name__=="__main__": unittest.main()
