# S2ToCSS Converter v0.9 development branch

Windows Python GUI and batch-processing foundation for converting editable Source 2 Hammer projects into Counter-Strike: Source VMF/assets.

## v0.8 development: automated model handoff

The optional model pipeline now connects the model-instance inventory to the user's
installed Blender Source Tools and Counter-Strike: Source compiler:

- Resolves each referenced `.vmdl` to an editable same-path/same-stem `.dmx` or
  `.fbx` source asset in the selected project tree.
- Runs Blender in background mode and imports DMX through Blender Source Tools or
  FBX through Blender's importer.
- Exports the imported static mesh through the Blender Source Tools
  `export_scene.smd` operator.
- Writes a QC for each required static/dynamic model variant and optionally runs
  the configured CS:S `studiomdl.exe`.
- Copies compiled model artifacts into the conversion output and writes
  a per-map `*_model_pipeline_manifest.json`.
- Appends prop entities for successfully compiled models to the map VMF; if brush
  export fails, it writes a separate entity-only VMF.

### Configure the model toolchain

In the GUI, browse to:

1. `Blender.exe` (Blender 5.0.1 was used for development).
2. The Counter-Strike: Source-compatible `studiomdl.exe`.
3. The CS:S game folder containing `gameinfo.txt` (commonly the `cstrike`
   directory, not the parent Steam common folder).

The model pipeline is optional. If paths are omitted, the converter still writes
its model inventory and source-resolution manifest without launching external tools.
For best source matching, keep editable DMX/FBX files in the same relative asset
folder structure as the VMAP's `.vmdl` references. Prefix matches such as
`model_body_lod0.dmx` are supported when the model document is named `model.vmdl`.
When both formats match, DMX is preferred and LOD0 is prioritized; ambiguous
matches are listed in the manifest and conversion report.

The compiler writes model artifacts into the configured CS:S game directory before
the converter stages matching outputs under `models/s2_import` in the output
folder. Ensure the game directory is writable and back up any files with colliding
names before compiling.

### Model pipeline boundaries

The model pipeline is now integrated with the VMAP brush exporter described below.
Model prop positions and angles are currently passed through unchanged; compare
representative placements in Hammer before treating the coordinate/rotation
mapping as certified. Non-unit model scales are skipped rather than written to
unsupported CS:S prop scale keys; per-scale baked model variants remain future
work. VMAT-to-VMT and Source 2 entity/I/O conversion are now partially implemented;
see the material/entity section below for current coverage and limitations.

## v0.9 development: integrated VMAP brushes and model props

The converter now has an integrated editable-VMAP geometry and model workflow:

- Parses the editable binary-DMX VMAP and decodes the `CMapMesh → CDmePolygonMesh`
  vertex-position and edge/face-loop topology.
- Applies the current Source-style origin / pitch-yaw-roll / scale transform to
  decoded mesh vertices.
- Validates each candidate brush for closed manifold edges, planar faces,
  convex half-spaces, duplicate geometric faces, and practical size limits.
- Writes accepted convex meshes into one `<map>_brushes.vmf` incrementally and
  records every exported or skipped mesh in `<map>_brushes_report.json`.
- Resolves referenced model assets to editable DMX/FBX files, imports them with
  Blender Source Tools, exports SMD/QC, optionally compiles static/dynamic
  variants with CS:S `studiomdl.exe`, and appends compiled prop entities to the
  same VMF.
- Writes model inventory CSV/JSON and a per-map model-pipeline manifest.

### GUI setup

Select the editable `.vmap` file or the project folder. Configure the following
optional paths when using the model/material workflows:

- **Blender.exe** — Blender 5.0.1 was used for development.
- **CS:S studiomdl.exe** — use the compiler from the Counter-Strike: Source toolchain.
- **CS:S game folder** — select the folder containing CS:S `gameinfo.txt`.
- **Source 2 materials folder** — optional; restricts material-reference analysis to
  the selected addon's materials.
- **Material map JSON** — optional mapping from Source 2 VMAT paths to existing
  Source 1 VMT material names.
- **VTFCmd.exe** — optional conversion of loose raster images to VTF.

When both DMX and FBX sources match a referenced `.vmdl`, DMX is preferred.
Ambiguous matches are listed in the model manifest. Compiled model artifacts are
staged under `models/s2_import` in the output folder after compilation.

### Geometry and conversion limits

The brush exporter intentionally emits only meshes that pass its safety checks.
Large, ambiguous, open, non-planar, non-manifold, non-convex, or otherwise
unsupported meshes are skipped with a reason in the mesh report so they can be
handled as models in Hammer. It does not fabricate geometry for failed decodes.

Known tool materials are mapped per face. Other Source 2 materials use generated
VMT mappings when their VMATs and source textures can be resolved; unsupported
shader parameters and compiled `.vtex_c` extraction remain limitations. Common
Source 1 entities and recognizable I/O connections are emitted, but Source 2-specific
entity behavior, unsupported classes/connection encodings, displacements, overlays,
and special map features are not fully translated. Model prop positions and
angles currently pass through unchanged; compare representative instances in
Hammer before treating the coordinate/rotation mapping as certified. Non-unit
model scales are skipped rather than approximated with unsupported CS:S entity
scale keys. The output is therefore a substantial base converter, not a
guaranteed one-click playable-map conversion for every VMAP.

Run the expanded tests with:

```bat
py -m unittest test_model_inventory test_model_pipeline test_mesh_decode test_mesh_validate test_vmf_export test_mesh_schema test_material_conversion test_entity_conversion
py test_smoke.py
```

## v0.7 history: native mesh schema inspection

This development branch adds a diagnostic pass for the real editable VMAP DMX graph:

- Finds CMapMesh nodes and mesh-related data elements.
- Reports attribute names and compact values, including element references, array lengths/samples, and binary payload byte counts.
- Writes a JSON report without requiring .vmap_c or Source 2 Viewer.
- Includes a command-line entry point for gathering real-world schema evidence.

This is deliberately **schema inspection, not mesh decoding yet**. The generic DMX parser currently records binary payload lengths, not their contents, and the precise vertex stream layout must be confirmed from real map data before decoding positions and topology safely. It does not create VMF brushes or claim that geometry is playable.

## Generate a mesh schema report

From the extracted S2ToCSS_Converter directory, run:

```bat
py inspect_mesh_schema.py "D:\\path\\to\\editable_map.vmap"
```

By default, the report is written beside the VMAP as editable_map_mesh_schema.json. An optional second argument selects the report path:

```bat
py inspect_mesh_schema.py "D:\\path\\to\\editable_map.vmap" "D:\\reports\\mesh_schema.json"
```

Use the editable .vmap, not .vmap_c. The JSON may contain a lot of mesh attributes, so open it in a text editor or VS Code.

## Existing v0.6 workflow

- Run run_converter.bat to open the GUI.
- Choose **Select file…** for one VMAP, or **Select project folder…** for the editable map and associated assets.
- The existing inventory writes project_inventory.json, project_inventory.txt, and vmap_transform_inventory.csv (or per-map equivalents).
- Source 2 Viewer is not required, configured, or launched.
- Optional mesh import dependencies: py -m pip install -r requirements.txt.

Python 3.10+ is recommended. The core DMX inventory and schema inspector use the Python standard library.

## Model support: first implementation stage

The model-instance inventory is now integrated into editable VMAP scans. For each
binary DMX v9 map, the converter inspects resolved `CMapEntity` entity properties
for `.vmdl` / `.vmdl_c` references and writes:

- `<map>_model_instances.json`: structured model references and placement records.
- `<map>_model_instances.csv`: spreadsheet-friendly placement list with origin,
  pitch/yaw/roll, scale, source node identity, and an explicit unmapped status.

The inventory also feeds the optional model-conversion pipeline. When Blender,
Blender Source Tools, and the CS:S `studiomdl.exe` paths are configured, the
converter resolves editable DMX/FBX sources, exports SMD/QC files, compiles
static/dynamic model variants, and emits VMF prop entities only for models that
compiled successfully. Candidate selection prefers render meshes and LOD0 over
physics/collision sidecars. For Source 2 `binary_seqids` DMX files, the exporter
normalizes only the temporary import copy's header; the original asset is left
untouched. If the toolchain is not configured, the inventory is still written
and the model manifest records which stages are pending. When the CS:S game
folder is selected but the compiler field is blank, the pipeline also checks
the standard sibling `bin/studiomdl.exe` locations automatically.

Transform values and selected entity properties are preserved exactly as decoded
from the VMAP. The inventory records the source entity class (e.g. `prop_static`
/ `prop_dynamic`), skin, solidity, render color, shadow setting, cubemap setting,
and material override when present. Coordinate/angle conversion is still passed
through unchanged and must be validated in Hammer before the VMF is treated as a
playable map.

### Validation against the supplied surf_the_wave.vmap

The uploaded editable map was successfully parsed as binary DMX v9:

- 32,506 DMX elements and 1,070 `CMapMesh` nodes.
- 2,630 `CMapEntity` nodes.
- 2,075 model-backed entities: 771 `prop_static` and 1,304 `prop_dynamic`.
- 55 distinct referenced `.vmdl` paths.
- All 2,075 model-backed entities contain an origin, angles, and scale.
- Every model-backed entity has a direct `model` property matching its discovered model path.

The map itself is used as a local validation input; it is not included in the
repository. These counts validate model-reference discovery and raw transform
capture, not Source 1 transform conversion, model compilation, or final VMF
placement.

Run the regression tests with:

```bat
py -m unittest test_model_inventory.py
```

## Current limitations

This branch now creates a partial VMF from supported convex CMapMesh geometry, compiled model props, common Source 1 entities, and recognizable I/O connections. It is not a guaranteed complete playable-map converter: unsupported meshes and non-prop Source 2 model entities are skipped, model/entity transforms still need Hammer validation, VMAT shader conversion is best-effort, compiled VTEX_C extraction is unavailable, and Source 2-specific entity behavior, displacements, overlays, and special map features remain unfinished.

## VMAT, VMT, entities, and I/O (new development stage)

The converter now has an initial automatic VMAT-to-VMT stage for referenced map
materials. It reads text VMAT/KV3 key/value blocks, maps recognized color/normal/
emissive and selected scalar inputs, writes VMTs under
`materials/s2_import/`, and resolves loose raster/VTF texture dependencies.
When VTFCmd is configured, loose raster textures are compiled to VTF; editable `.vtex`
documents are also inspected to locate their loose image source. Compiled `.vtex_c`
extraction remains unsupported. The resolver
checks the selected addon materials folder and the shared content/game material roots
reported by the VMAP scan. Referenced model DMX files are scanned for their own VMAT
dependencies as well, so prop materials are included even when absent from world brushes.
Legacy decompiler aliases such as `TextureColor`, `TextureNormal`, and
`TextureDetail` are also recognized alongside native `g_t*` VMAT parameters.
The Blender export stage normalizes VMAT paths in SMD triangle material rows to match
the generated VMT paths under the QC `$cdmaterials "s2_import"` directory. Generated
VMT/VTF files are staged into the configured CS:S game directory under
`materials/s2_import/` when that path is supplied. SMD material names are checked
against generated and existing game VMTs, with missing model materials reported. Generated brush VMTs use `LightmappedGeneric`; model DMX materials use `VertexLitGeneric`. Generated VMT names are fed back into per-face VMF material assignment.

This is a compatibility layer, not a complete Source 2 shader reimplementation.
Unknown shader parameters are recorded in `*_material_conversion.json`; missing
VMATs, unavailable textures, and VTEX/VTEX_C extraction limitations are reported.
Review the generated VMTs in Hammer and in-game.

The entity stage now attempts conservative passthrough of common Source 1
`logic_`, `trigger_`, `func_`, `info_`, `point_`, `env_`, and related entity
classes. It merges safe scalar worldspawn properties into the existing world block,
preserves entity scalar keyvalues and transforms, and skips model-backed props
already handled by the compiled-model pipeline. Compiled model props retain common
keyvalues such as targetname/parentname and their structured output connections. It writes
`*_entity_conversion.json` with skipped classes. Structured output records with
recognizable output/target/input fields are serialized into VMF `connections`
blocks, preserving parameter, delay, and fire count.

Entity and I/O conversion remains schema-dependent: unsupported Source 2 entity
classes and connection encodings are not guessed. Coordinate/angle conventions,
entity-specific Source 2 behavior, keyvalue differences, and output target
resolution still require real-map Hammer testing. The report also lists output targets
that do not match any inventoried targetname. The report is the authoritative record
of what was emitted, skipped, or left unresolved.

## Tests

Run:

```bat
py -m unittest test_model_inventory test_model_pipeline test_mesh_decode test_mesh_validate test_vmf_export test_mesh_schema test_material_conversion test_entity_conversion
py test_smoke.py
```

The automated tests use synthetic mesh fixtures. Real-map coverage is based on the previously inspected `surf_the_wave.vmap` for DMX/model inventory; the newly integrated geometry exporter and headless Blender pipeline still need a fresh end-to-end run on your Windows setup.


## Entity substitutions

The VMAP entity converter includes a conservative Source 2-to-Source 1 class substitution table.
Current defaults include `light_omni2 -> light`, `light_spot2 -> light_spot`,
and `light_environment2 -> light_environment`.

For project-specific overrides, copy `entity_substitutions.json` from the converter folder
into the selected addon/project root and edit its `substitutions` object. Source 1 class
replacements are validated against the converter's conservative class allowlist. The conversion
report records each substitution. Light color/brightness and spotlight cone values are translated
where possible, but Source 2 intensity units, falloff, range behavior, and runtime lighting are not
identical to Source 1; inspect converted lights in Hammer and expect approximation warnings.


## Automatic complex-mesh conversion

Meshes that cannot safely become convex VMF brushes are now exported as intermediate JSON
geometry packages and can be converted directly by the configured Blender + Blender Source
Tools + CS:S `studiomdl` pipeline. Blender constructs the mesh from decoded VMAP vertices,
faces and per-face material slots, generates fallback UVs when no UV layer is present, exports
SMD/QC, and compiles a static prop. The original Source 2 instance transform is baked into the
mesh coordinates; the generated VMF prop is therefore placed at world origin with identity
angles. This preserves the mesh's world-space placement but means its model pivot is at map
origin rather than its original local origin.

The converter first attempts a concave collision model. If that collision compile fails, it
retries as a visual-only static prop and records the missing collision in the mesh model
manifest. Meshes exceeding the hard decode safety limits remain in the report without model
conversion. This pipeline requires configured Blender, Blender Source Tools, CS:S game
directory, and `studiomdl.exe`; without these it still writes the intermediate geometry
packages and reports the pending conversion.

This is an initial automated recovery path, not a guarantee that every arbitrary/open/non-manifold
mesh will produce valid collision or render correctly. Review the generated model manifest and
inspect the VMF in Hammer before compiling the map.
