# Windows GUI for the experimental VMF exporter

This GUI is a launcher for `export_vmap_to_vmf.py`. It does not replace the exporter or add new conversion features.

## How to use it

1. Download this branch or update your existing checkout:
   `v0.7-vmf-export`
2. Keep `CS2_Map_Converter.pyw` in the `S2ToCSS_Converter` folder, next to `export_vmap_to_vmf.py`.
3. Double-click `CS2_Map_Converter.pyw`. If Windows asks which app to use, select your installed Python Launcher/Python.
4. Confirm the **Converter folder** field points to the folder containing `export_vmap_to_vmf.py`.
5. Click **Choose map…** and select the editable `.vmap` file (not `.vmap_c`).
6. Adjust the output `.vmf` and JSON report paths if desired, then click **Start conversion**.
7. Watch the in-app log for progress and errors.

## Recovering stock Source 2 materials (experimental)

1. Run a geometry conversion once to create the JSON report. This report contains the material paths referenced by the map.
2. Set **Source2Viewer CLI** to `Source2Viewer-CLI.exe` from Source 2 Viewer.
3. Set **VTFCmd** to `VTFCmd.exe` from VTFEdit/VTFEdit-Reloaded.
4. Set **CS2 game folder** to the game's `game\\csgo` folder that contains the VPK archives.
5. Set **Output materials** to the Source 1 `materials` directory where generated assets should be written.
6. Click **Recover Source 2 materials**. The helper searches VPKs for referenced compiled materials and textures, exports images, converts them to VTF, and writes basic VMT files plus `s2_material_map.json`.
7. After recovery, select that `s2_material_map.json` in **Material map JSON** and run the VMF conversion again.

The recovery feature is experimental. It only creates basic `LightmappedGeneric` materials from a detected color/albedo texture; normal maps, masks, roughness/metalness, and other PBR features are not fully translated. Assets not found in the selected game's loose files/VPKs remain unmapped and fall back to nodraw. Keep a backup of your materials folder and inspect generated VMT/VTF assets before using them in a final map.

## Requirements

- Windows and Python installed.
- The same Python environment and dependencies used by the existing exporter.
- Optional material recovery: Source 2 Viewer CLI and VTFCmd. These are only needed for stock-material recovery, not geometry-only conversion.
- The complete `S2ToCSS_Converter` project folder. Do not copy the GUI by itself and expect it to convert maps.

The GUI starts the exporter without showing a separate Command Prompt window. It does not require Source 2 Viewer. Review exported geometry in Hammer; this experimental exporter does not yet convert every entity, material, or complex mesh automatically.
