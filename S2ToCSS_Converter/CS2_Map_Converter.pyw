"""Windows GUI launcher for export_vmap_to_vmf.py.

Place this file in the S2ToCSS_Converter directory, beside export_vmap_to_vmf.py.
Run it by double-clicking the .pyw file; it launches without a console window.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


APP_TITLE = "CS2 → CSS Map Converter"


def python_executable() -> str:
    """Prefer python.exe for subprocesses, even when this GUI runs under pythonw.exe."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        console_exe = exe.with_name("python.exe")
        if console_exe.exists():
            return str(console_exe)
    return str(exe)


class ConverterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("820x620")
        self.root.minsize(700, 520)

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.process: subprocess.Popen[str] | None = None

        default_dir = Path(__file__).resolve().parent
        self.converter_dir = tk.StringVar(value=str(default_dir))
        self.input_file = tk.StringVar()
        self.output_file = tk.StringVar()
        self.report_file = tk.StringVar()
        self.status = tk.StringVar(value="Ready — choose an editable .vmap file.")
        self.open_output = tk.BooleanVar(value=False)

        outer = ttk.Frame(root, padding=14)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="CS2 Map Converter", font=("Segoe UI", 17, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Convert editable Source 2 .vmap geometry to a Source 1 .vmf. "
                 "Choose files and run the existing exporter without typing commands.",
            wraplength=770,
        ).pack(anchor="w", pady=(3, 14))

        self.path_row(outer, "Converter folder", self.converter_dir, self.pick_converter, "Browse…")
        self.path_row(outer, "Input .vmap", self.input_file, self.pick_input, "Choose map…")
        self.path_row(outer, "Output .vmf", self.output_file, self.pick_output, "Save as…")
        self.path_row(outer, "JSON report", self.report_file, self.pick_report, "Save as…")

        ttk.Checkbutton(
            outer, text="Open output folder when finished", variable=self.open_output
        ).pack(anchor="w", pady=(6, 8))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(0, 8))
        self.start_button = ttk.Button(buttons, text="Start conversion", command=self.start)
        self.start_button.pack(side="left")
        ttk.Button(buttons, text="Open converter folder", command=self.open_converter_folder).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(buttons, text="Clear log", command=self.clear_log).pack(side="left", padx=(8, 0))

        ttk.Label(outer, textvariable=self.status).pack(anchor="w", pady=(2, 4))
        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 8))

        log_frame = ttk.LabelFrame(outer, text="Conversion log", padding=6)
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(log_frame, height=12, wrap="word", state="disabled", font=("Consolas", 9))
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.root.after(100, self.poll_events)

    @staticmethod
    def path_row(parent, label, variable, command, button_label):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=label, width=16).pack(side="left", anchor="w")
        ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(row, text=button_label, command=command).pack(side="left")

    def pick_converter(self):
        path = filedialog.askdirectory(title="Choose the S2ToCSS_Converter folder")
        if path:
            self.converter_dir.set(path)

    def pick_input(self):
        path = filedialog.askopenfilename(
            title="Choose editable CS2 map",
            filetypes=[("Editable VMAP", "*.vmap"), ("All files", "*.*")],
        )
        if path:
            self.input_file.set(path)
            source = Path(path)
            self.output_file.set(str(source.with_name(source.stem + "_brushes.vmf")))
            self.report_file.set(str(source.with_name(source.stem + "_brushes_report.json")))

    def pick_output(self):
        path = filedialog.asksaveasfilename(
            title="Save exported VMF",
            defaultextension=".vmf",
            filetypes=[("VMF map", "*.vmf")],
            initialfile=Path(self.output_file.get()).name if self.output_file.get() else "map_brushes.vmf",
        )
        if path:
            self.output_file.set(path)
            if not self.report_file.get():
                self.report_file.set(str(Path(path).with_name(Path(path).stem + "_report.json")))

    def pick_report(self):
        path = filedialog.asksaveasfilename(
            title="Save JSON report",
            defaultextension=".json",
            filetypes=[("JSON report", "*.json")],
            initialfile=Path(self.report_file.get()).name if self.report_file.get() else "map_report.json",
        )
        if path:
            self.report_file.set(path)

    def append_log(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def open_converter_folder(self):
        path = Path(self.converter_dir.get())
        if path.is_dir():
            os.startfile(str(path))
        else:
            messagebox.showerror(APP_TITLE, "That converter folder does not exist.")

    def start(self):
        if self.worker and self.worker.is_alive():
            return

        folder = Path(self.converter_dir.get()).expanduser()
        source = Path(self.input_file.get()).expanduser()
        output = Path(self.output_file.get()).expanduser()
        report = Path(self.report_file.get()).expanduser()
        script = folder / "export_vmap_to_vmf.py"

        if not folder.is_dir():
            messagebox.showerror(APP_TITLE, "Choose the folder containing export_vmap_to_vmf.py.")
            return
        if not script.is_file():
            messagebox.showerror(
                APP_TITLE,
                f"Could not find:\n{script}\n\nChoose the S2ToCSS_Converter folder itself, not its parent.",
            )
            return
        if not source.is_file() or source.suffix.lower() != ".vmap":
            messagebox.showerror(APP_TITLE, "Choose an existing editable .vmap file, not .vmap_c.")
            return
        if not output.name or not report.name:
            messagebox.showerror(APP_TITLE, "Choose both an output VMF and a JSON report path.")
            return
        if output.resolve() == source.resolve():
            messagebox.showerror(APP_TITLE, "The output VMF must not overwrite the input VMAP.")
            return

        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            report.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Could not create output folder:\n{exc}")
            return

        command = [
            python_executable(), str(script), str(source),
            "--output", str(output), "--report", str(report),
        ]
        self.start_button.configure(state="disabled")
        self.progress.start(10)
        self.status.set("Converting… progress and errors will appear below.")
        self.append_log("Starting conversion")
        self.append_log(f"Input:  {source}")
        self.append_log(f"Output: {output}")
        self.append_log(f"Report: {report}")
        self.append_log("-" * 60)

        self.worker = threading.Thread(target=self.run_process, args=(command, folder), daemon=True)
        self.worker.start()

    def run_process(self, command: list[str], cwd: Path):
        try:
            self.process = subprocess.Popen(
                command,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.events.put(("line", line))
            code = self.process.wait()
            self.events.put(("done", code))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def poll_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "line":
                    self.append_log(str(value))
                elif kind == "done":
                    code = int(value)
                    self.progress.stop()
                    self.start_button.configure(state="normal")
                    self.process = None
                    if code == 0:
                        self.status.set("Finished successfully.")
                        self.append_log("Conversion completed successfully.")
                        if self.open_output.get():
                            os.startfile(str(Path(self.output_file.get()).parent))
                        messagebox.showinfo(
                            APP_TITLE,
                            "Conversion completed successfully.\n\nYour VMF and JSON report are ready.",
                        )
                    else:
                        self.status.set(f"Conversion failed (exit code {code}). See the log.")
                        self.append_log(f"Conversion failed with exit code {code}.")
                        messagebox.showerror(APP_TITLE, "Conversion failed. See the log in the app.")
                elif kind == "error":
                    self.progress.stop()
                    self.start_button.configure(state="normal")
                    self.status.set("Could not start converter.")
                    self.append_log("ERROR: " + str(value))
                    messagebox.showerror(APP_TITLE, "Could not start the converter:\n" + str(value))
        except queue.Empty:
            pass
        self.root.after(100, self.poll_events)


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    ConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
