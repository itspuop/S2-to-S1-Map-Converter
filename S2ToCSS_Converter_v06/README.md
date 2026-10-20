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

## Current limitations

This branch does **not** yet create a playable CS:S map directly from VMAP. Native mesh schema inspection is the first verification step toward vertex-stream decoding, polygon reconstruction, transform composition, closed-solid/convexity checks, and VMF generation. Complex meshes will continue to be flagged for the manual model workflow discussed for this project. Source 2 materials, model compilation, entity/I/O conversion, and full texture translation also remain future work.

## Tests

Run:

```bat
py -m unittest test_mesh_schema.py
py test_smoke.py
```

The schema tests cover report-shape helpers. A real editable VMAP fixture is still needed to validate the exact mesh attribute and vertex-stream encoding before enabling automatic geometry export.

## Dump full topology for one mesh

The compact schema report summarizes long integer arrays. To inspect every connectivity index and the actual vertex/face data streams from the VMAP itself, run:

```bat
py dump_mesh_topology.py "D:\\path\\to\\editable_map.vmap"
```

It dumps the first CMapMesh by default. To select a specific CMapMesh element index from the schema report, pass `--mesh-index`:

```bat
py dump_mesh_topology.py "D:\\path\\to\\editable_map.vmap" --mesh-index 7
```

This prints JSON to the terminal and does not modify the map. The dump can be large; redirect it to a text file if needed:

```bat
py dump_mesh_topology.py "D:\\path\\to\\editable_map.vmap" --mesh-index 7 > mesh_topology.txt
```

## Decode polygon loops for one mesh (experimental)

The branch now includes an experimental decoder that reads the position stream and walks each face's half-edge loop using `faceEdgeIndices`, `edgeNextIndices`, and `edgeVertexIndices`. It writes diagnostic JSON only; it does not transform vertices into world space or generate VMF brushes yet.

Run:

```bat
py decode_vmap_mesh.py "P:\\SteamLibrary\\steamapps\\common\\Counter-Strike Global Offensive\\content\\csgo_addons\\surf_the_wave\\maps\\surf_the_wave.vmap" --mesh-index 7 --output decoded_mesh_7.json
```

Review `valid_face_count`, `invalid_face_count`, each face's `vertex_indices`, and `positions_local`. Do not treat a valid loop as proof of a closed convex solid. The decoder is experimental and should be validated against more than one real mesh before it is used for conversion.

Run its synthetic tests with:

```bat
py -m unittest test_mesh_decode.py
```
