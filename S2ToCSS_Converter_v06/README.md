# S2ToCSS Converter v0.6

Windows Python GUI and batch-processing foundation for converting editable Source 2 Hammer projects into Counter-Strike: Source VMF/assets.

## New in v0.6: Source 2 Viewer removed as a dependency

Source 2 Viewer is not required, configured, or launched by this application. The converter reads editable VMAP files directly with its native Python binary-DMX parser. Compiled Source 2 assets that need extraction are reported as unsupported rather than triggering an external viewer.

## Binary DMX v9 parsing

This version adds a defensive Python reader for Source 2 binary DMX encoding version 9, used by editable CS2 `.vmap` files. It parses the prefix element, string table, element headers, attribute bodies, arrays, and generic element references. For Hammer node types including `CMapMesh`, `CMapEntity`, `CMapGroup`, `CMapPathNode`, and `CMapStaticOverlay`, it records transforms and available mesh/material metadata.

When you select a project folder, the converter writes:

- `project_inventory.json` — parsed graph summaries, element-type counts, resource references, and transform records.
- `project_inventory.txt` — human-readable summary.
- `vmap_transform_inventory.csv` — model/mesh/entity placement records that can be inspected in Excel.

When you select one `.vmap`, it writes `<mapname>_inventory.json` and `<mapname>_transform_inventory.csv`.

## Install / run

1. Install Python 3.10+ on Windows.
2. Extract the ZIP.
3. Optional mesh import dependencies: `py -m pip install -r requirements.txt`.
4. Run `run_converter.bat`. Keep its Command Prompt window open; live progress is printed there and in the GUI log.
5. Choose **Select file…** for one VMAP, or **Select project folder…** for the full editable map and associated asset folders.

No compiled map (`.vmap_c`) is required for the binary DMX inventory workflow.

## What is implemented

- Windows GUI with separate file/folder pickers and live progress logs.
- Recursive discovery and inventory of editable VMAPs and associated assets.
- Binary DMX v9 graph parsing for real editable VMAPs.
- Element class counts, model/material references, transform extraction, and CSV export.
- Best-effort dependency path resolution.
- Preliminary mesh-to-VMF and loose-raster texture workflow for externally exported geometry/assets.
- JSON and text conversion reports.

## What is not implemented yet

**v0.5 is not a complete VMAP-to-VMF converter and does not yet create a playable CS:S map from an editable VMAP.** The new parser reads the object graph and selected transforms, but does not yet reconstruct `CDmePolygonMesh` face loops and vertex streams into valid Source 1 convex brush solids. Model source conversion/compilation, full entity/I/O conversion, and complete Source 2 shader translation also remain future work.

The next milestone is schema-aware `CMapMesh` topology decoding: resolve vertex and face data streams, reconstruct polygons, apply the correct Hammer transform conventions, classify suitable convex solids, and validate generated VMF brushes. Complex models are expected to be converted manually to VMDLs in CS2 Hammer, as agreed; the converter will later map their associated source meshes and placement records into Source 1 model instances.

## Optional external tools

- Blender may be used manually to inspect or prepare mesh sources, but is not required to scan editable VMAPs.
- VTFCmd/VTFEdit and Source SDK tools are optional and must be installed separately for their respective asset-conversion stages.
- Source 2 Viewer is not a dependency and is not called by this program.
