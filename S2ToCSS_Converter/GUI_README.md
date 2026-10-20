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

## Requirements

- Windows and Python installed.
- The same Python environment and dependencies used by the existing exporter.
- The complete `S2ToCSS_Converter` project folder. Do not copy the GUI by itself and expect it to convert maps.

The GUI starts the exporter without showing a separate Command Prompt window. It does not require Source 2 Viewer. Review exported geometry in Hammer; this experimental exporter does not yet convert every entity, material, or complex mesh automatically.
