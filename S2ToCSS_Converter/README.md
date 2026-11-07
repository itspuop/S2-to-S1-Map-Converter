# S2ToCSS Converter v0.7 development branch

Windows Python GUI and batch-processing foundation for converting editable Source 2 Hammer projects into Counter-Strike: Source VMF/assets.

## v0.7 development: native mesh schema inspection

This development branch adds a diagnostic pass for the real editable VMAP DMX graph:

- Finds CMapMesh nodes and mesh-related data elements.
- Reports attribute names and compact values, including element references, array lengths/samples, and binary payload byte counts.
- Writes a JSON report without requiring .vmap_c or Source 2 Viewer.
- Includes a command-line entry point for gathering real-world schema evidence.

This is deliberately **schema inspection, not mesh decoding yet**. The generic DMX parser currently records binary payload lengths, not their contents, and the precise vertex stream layout must be confirmed from real map data before decoding positions and topology safely. It does not create VMF brushes or claim that geometry is playable.

## Generate a mesh schema report

From the extracted S2ToCSS_Converter_v06 directory, run:

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

This is an inventory/handoff stage only. It does not yet create Source 1
`prop_static` entities or compile MDLs. Transform values and selected entity properties are preserved exactly
as decoded from the VMAP. The inventory also records the source entity class
(e.g. `prop_static` / `prop_dynamic`), skin, solidity, render color, shadow
setting, cubemap setting, and material override when present. Coordinate/angle
conversion must be validated before these values are emitted into a playable
VMF. The next stage is to associate these records with manually exported
Source 1 model assets and then generate VMF entities only for verified mappings.

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

This branch does **not** yet create a playable CS:S map directly from VMAP. Native mesh schema inspection is the first verification step toward vertex-stream decoding, polygon reconstruction, transform composition, closed-solid/convexity checks, and VMF generation. Complex meshes will continue to be flagged for the manual model workflow discussed for this project. Source 2 materials, model compilation, entity/I/O conversion, and full texture translation also remain future work.

## Tests

Run:

```bat
py -m unittest test_mesh_schema.py
py test_smoke.py
```

The schema tests cover report-shape helpers. A real editable VMAP fixture is still needed to validate the exact mesh attribute and vertex-stream encoding before enabling automatic geometry export.
