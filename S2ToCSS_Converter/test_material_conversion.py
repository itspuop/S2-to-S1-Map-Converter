import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from s2css.materials import parse_keyvalues, convert_vmat_references, collect_vmat_references, stage_materials_to_game

class MaterialConversionTests(unittest.TestCase):
    def test_stages_generated_materials_into_css_game_directory(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "output" / "materials" / "s2_import"
            game = Path(tmp) / "cstrike"
            source.mkdir(parents=True)
            game.mkdir()
            (source / "crate.vmt").write_text('"LightmappedGeneric" {}', encoding="utf-8")
            (source / "crate.vtf").write_bytes(b"vtf")
            copied = stage_materials_to_game(source, game)
            self.assertEqual(copied, 2)
            self.assertTrue((game / "materials" / "s2_import" / "crate.vmt").is_file())
            self.assertTrue((game / "materials" / "s2_import" / "crate.vtf").is_file())

    def test_collects_nested_dmx_material_paths(self):
        refs = collect_vmat_references({
            "name": r"materials\models\corals\coral.vmat",
            "nested": [{"material": "materials/props/metal.vmat"}, "not_a_material.png"],
        })
        self.assertEqual(refs, [
            "materials/models/corals/coral.vmat",
            "materials/props/metal.vmat",
        ])

    def test_parses_nested_vmat_and_ignores_kv3_header(self):
        tree = parse_keyvalues('<!-- kv3 encoding:text:version{...} -->\n"Layer0" { "shader" "csgo_complex.vfx" "TextureColor" { "g_tColor" "materials/test/color.vtex" } }')
        self.assertEqual(tree["Layer0"]["shader"], "csgo_complex.vfx")
        self.assertEqual(tree["Layer0"]["TextureColor"]["g_tColor"], "materials/test/color.vtex")

    def test_parses_modern_kv3_parameter_arrays(self):
        tree = parse_keyvalues('''<!-- kv3 encoding:text:version{...} -->
        {
            m_shaderName = "csgo_complex.vfx"
            m_textureParams = [
                { m_name = "g_tColor" m_pValue = resource:"materials/test/color.vtex" }
            ]
        }''')
        self.assertEqual(tree["m_shaderName"], "csgo_complex.vfx")
        self.assertEqual(tree["m_textureParams"][0]["m_name"], "g_tColor")
        self.assertEqual(tree["m_textureParams"][0]["m_pValue"], "resource:materials/test/color.vtex")

    def test_resolves_loose_image_from_vtex_source(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "materials"
            out = Path(tmp) / "out" / "materials" / "s2_import"
            (root / "props").mkdir(parents=True)
            (root / "props" / "stone.vmat").write_text(
                '{ m_shaderName = "csgo_complex.vfx" m_textureParams = [ '
                '{ m_name = "g_tColor" m_pValue = resource:"materials/props/stone_color.vtex" } ] }',
                encoding="utf-8",
            )
            (root / "props" / "stone_color.vtex").write_text(
                '''<!-- dmx encoding keyvalues2_noids 1 format vtex 1 -->
                "CDmeVtex" {
                    "m_inputTextureArray" "element_array"
                    [
                        "CDmeInputTexture" {
                            "m_name" "string" "InputTexture0"
                            "m_fileName" "string" "materials/props/stone_color.tga"
                        }
                    ]
                }''',
                encoding="utf-8",
            )
            (root / "props" / "stone_color.tga").write_bytes(b"image")
            result = convert_vmat_references(["materials/props/stone.vmat"], root, out)
            self.assertEqual(result["converted_count"], 1)
            self.assertTrue((out / "props" / "stone.vmt").is_file())
            self.assertTrue((out / "props" / "stone_color.tga").is_file())

    def test_recognizes_legacy_texturecolor_and_texturenormal_aliases(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "materials"
            out = Path(tmp) / "out" / "materials" / "s2_import"
            (root / "models").mkdir(parents=True)
            (root / "models" / "legacy.vmat").write_text(
                '{ m_shaderName = "csgo_complex.vfx" m_textureParams = [ '
                '{ m_name = "TextureColor" m_pValue = resource:"materials/models/albedo.png" } '
                '{ m_name = "TextureNormal" m_pValue = resource:"materials/models/normal.png" } '
                '{ m_name = "TextureDetail" m_pValue = resource:"materials/models/detail.png" } ] }',
                encoding="utf-8",
            )
            for name in ("albedo", "normal", "detail"):
                (root / "models" / f"{name}.png").write_bytes(b"image")
            result = convert_vmat_references(["materials/models/legacy.vmat"], root, out)
            self.assertEqual(result["converted_count"], 1)
            params = result["results"][0]["parameters"]
            self.assertEqual(params["$basetexture"], "s2_import/models/albedo")
            self.assertEqual(params["$bumpmap"], "s2_import/models/normal")
            self.assertEqual(params["$detail"], "s2_import/models/detail")

    def test_model_materials_use_vertexlitgeneric(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "materials"
            out = Path(tmp) / "out" / "materials" / "s2_import"
            (root / "models").mkdir(parents=True)
            (root / "models" / "crate.vmat").write_text(
                '{ m_shaderName = "csgo_complex.vfx" m_textureParams = [ '
                '{ m_name = "g_tColor" m_pValue = resource:"materials/models/crate.png" } ] }',
                encoding="utf-8",
            )
            (root / "models" / "crate.png").write_bytes(b"image")
            result = convert_vmat_references(
                ["materials/models/crate.vmat"], root, out, brush_material=False
            )
            self.assertEqual(result["converted_count"], 1)
            self.assertTrue((out / "models" / "crate.vmt").read_text(encoding="utf-8").startswith('"VertexLitGeneric"'))

    def test_resolves_shared_content_vmat_and_texture_roots(self):
        with TemporaryDirectory() as tmp:
            addon_root = Path(tmp) / "addon_materials"
            shared_root = Path(tmp) / "shared_materials"
            output_root = Path(tmp) / "out" / "materials" / "s2_import"
            (shared_root / "props").mkdir(parents=True)
            (shared_root / "props" / "shared.vmat").write_text(
                '{ m_shaderName = "csgo_complex.vfx" m_textureParams = [ '
                '{ m_name = "g_tColor" m_pValue = resource:"materials/props/shared.png" } ] }',
                encoding="utf-8",
            )
            (shared_root / "props" / "shared.png").write_bytes(b"image")
            result = convert_vmat_references(
                ["materials/props/shared.vmat"], addon_root, output_root,
                search_roots=[shared_root],
            )
            self.assertEqual(result["converted_count"], 1)
            self.assertEqual(result["results"][0]["source_vmat_ref"], "materials/props/shared.vmat")
            self.assertTrue((output_root / "props" / "shared.vmt").is_file())
            self.assertTrue((output_root / "props" / "shared.png").is_file())

    def test_writes_vmt_and_copies_source_texture_when_vtfcmd_missing(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "materials"
            out = Path(tmp) / "out" / "materials" / "s2_import"
            (root / "test").mkdir(parents=True)
            (root / "test" / "color.vmat").write_text(
                '''{ m_shaderName = "csgo_complex.vfx"
                    m_textureParams = [ { m_name = "g_tColor" m_pValue = resource:"materials/test/color.png" } ]
                    m_intParams = [ { m_name = "F_ALPHA_TEST" m_nValue = 1 } ]
                    m_vectorParams = [ { m_name = "g_vColorTint" m_vValue = [1, 1, 1] } ]
                }''',
                encoding="utf-8",
            )
            (root / "test" / "color.png").write_bytes(b"image")
            result = convert_vmat_references(["materials/test/color.vmat"], root, out)
            self.assertEqual(result["converted_count"], 1)
            vmt = out / "test" / "color.vmt"
            self.assertTrue(vmt.is_file())
            vmt_text = vmt.read_text(encoding="utf-8")
            self.assertIn('"$basetexture" "s2_import/test/color"', vmt_text)
            self.assertIn('"$alphatest" "1"', vmt_text)
            self.assertIn('"$color" "1 1 1"', vmt_text)
            self.assertTrue((out / "test" / "color.png").is_file())
            self.assertTrue(result["warnings"])

if __name__ == "__main__":
    unittest.main()
