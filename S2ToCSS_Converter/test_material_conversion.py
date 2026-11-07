import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from s2css.materials import parse_keyvalues, convert_vmat_references

class MaterialConversionTests(unittest.TestCase):
    def test_parses_nested_vmat_and_ignores_kv3_header(self):
        tree = parse_keyvalues('<!-- kv3 encoding:text:version{...} -->\n"Layer0" { "shader" "csgo_complex.vfx" "TextureColor" { "g_tColor" "materials/test/color.vtex" } }')
        self.assertEqual(tree["Layer0"]["shader"], "csgo_complex.vfx")
        self.assertEqual(tree["Layer0"]["TextureColor"]["g_tColor"], "materials/test/color.vtex")

    def test_writes_vmt_and_copies_source_texture_when_vtfcmd_missing(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "materials"
            out = Path(tmp) / "out" / "materials" / "s2_import"
            (root / "test").mkdir(parents=True)
            (root / "test" / "color.vmat").write_text(
                '"Layer0" { "shader" "csgo_complex.vfx" "TextureColor" { "g_tColor" "materials/test/color.png" } }',
                encoding="utf-8",
            )
            (root / "test" / "color.png").write_bytes(b"image")
            result = convert_vmat_references(["materials/test/color.vmat"], root, out)
            self.assertEqual(result["converted_count"], 1)
            vmt = out / "test" / "color.vmt"
            self.assertTrue(vmt.is_file())
            self.assertIn('"$basetexture" "s2_import/test/color"', vmt.read_text(encoding="utf-8"))
            self.assertTrue((out / "test" / "color.png").is_file())
            self.assertTrue(result["warnings"])

if __name__ == "__main__":
    unittest.main()
