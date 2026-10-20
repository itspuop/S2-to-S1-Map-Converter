import unittest
from s2css.mesh_decode import MeshDecodeError, decode_polygon_mesh

def ref(i): return {"element_index": i}

class DecodeMeshTests(unittest.TestCase):
    def test_decode_cube_topology(self):
        graph = {"elements": [
            {"type":"CMapMesh","name":"cube","guid":"abc","attributes":{"meshData":ref(1),"origin":[10,20,30],"angles":[0,0,0],"scales":[1,1,1]}},
            {"type":"CDmePolygonMesh","name":"cube_data","attributes":{
                "vertexData":ref(2),
                "edgeVertexIndices":[0,1,5,2,4,3,6,7,4,7,0,2,5,1,6,3,3,4,2,5,1,0,7,6],
                "edgeNextIndices":[1,2,3,0,5,6,7,4,9,10,11,8,13,14,15,12,17,18,19,16,21,22,23,20],
                "faceEdgeIndices":[0,4,8,12,16,20],"materials":["materials/test.vmat"]}},
            {"type":"CDmeVertexData","name":"vertex_data","attributes":{"streams":[ref(3)]}},
            {"type":"CDmeVertexDataStream","name":"position","attributes":{"semantic":"position","data":[
                [-1,-1,1],[1,-1,1],[-1,1,1],[1,1,-1],[-1,1,-1],[1,1,1],[1,-1,-1],[-1,-1,-1]]}},
        ]}
        result=decode_polygon_mesh(graph,0)
        self.assertEqual(result["counts"],{"vertices":8,"faces":6,"edges":24})
        self.assertEqual(result["origin"],[10,20,30])
        self.assertEqual(result["face_loops"][0],[0,1,5,2])

    def test_wrong_element_type_fails(self):
        with self.assertRaises(MeshDecodeError):
            decode_polygon_mesh({"elements":[{"type":"CDmePolygonMesh","attributes":{}}]},0)

if __name__=="__main__": unittest.main()
