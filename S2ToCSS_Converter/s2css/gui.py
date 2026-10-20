import threading, tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from .core import run_conversion

class App:
    def __init__(self, root):
        self.root=root; root.title('S2ToCSS v0.6 — Source 2 to Counter-Strike: Source'); root.geometry('1050x700'); root.minsize(850,580)
        self.src=tk.StringVar(); self.out=tk.StringVar(value=str(Path.cwd()/'converted_css'))
        self.vtfcmd=tk.StringVar(); self.status=tk.StringVar(value='Ready')
        frame=ttk.Frame(root,padding=14); frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Source 2 → Counter-Strike: Source  |  v0.6',font=('Segoe UI',16,'bold')).pack(anchor='w')
        ttk.Label(frame,text='Native editable-VMAP parsing • transform inventory • VMF/material workflow • batch reports').pack(anchor='w',pady=(2,12))
        self._inputrow(frame)
        self._pathrow(frame,'Output folder',self.out,self.pick_output)
        self._pathrow(frame,'VTFCmd.exe (optional)',self.vtfcmd,self.pick_vtf)
        buttons=ttk.Frame(frame); buttons.pack(fill='x',pady=10)
        self.go=ttk.Button(buttons,text='Convert / Scan',command=self.start); self.go.pack(side='left')
        ttk.Button(buttons,text='Open output folder',command=self.open_output).pack(side='left',padx=8)
        ttk.Button(buttons,text='About limitations',command=self.about).pack(side='left')
        ttk.Label(frame,textvariable=self.status).pack(anchor='w',pady=(0,5))
        self.log=tk.Text(frame,wrap='word',height=22); self.log.pack(fill='both',expand=True)
        self.log.insert('end','Ready. Choose a single VMAP file or use Select project folder for an entire asset tree.\n\nLive progress will appear here and in the command window. Current stages: input discovery, native binary-DMX v9 graph parsing, model/material reference inventory, transform CSV export, geometry-export handling, loose texture conversion, and reports. No Source 2 Viewer installation is needed. VMF brush reconstruction is still in development.\n')
    def _inputrow(self,parent):
        row=ttk.Frame(parent); row.pack(fill='x',pady=4)
        ttk.Label(row,text='Input file / folder',width=24).pack(side='left')
        ttk.Entry(row,textvariable=self.src).pack(side='left',fill='x',expand=True,padx=6)
        ttk.Button(row,text='Select file…',command=self.pick_source).pack(side='left',padx=(0,4))
        ttk.Button(row,text='Select project folder…',command=self.pick_source_folder).pack(side='left')
    def _pathrow(self,parent,label,var,command):
        row=ttk.Frame(parent); row.pack(fill='x',pady=4)
        ttk.Label(row,text=label,width=24).pack(side='left')
        ttk.Entry(row,textvariable=var).pack(side='left',fill='x',expand=True,padx=6)
        ttk.Button(row,text='Browse…',command=command).pack(side='right')
    def pick_source(self):
        p=filedialog.askopenfilename(parent=self.root,title='Select a source map or geometry file',filetypes=[('Source 2 maps and geometry','*.vmap *.vmap_c *.obj *.gltf *.glb *.ply *.stl'),('All files','*.*')])
        if p: self.src.set(p)
    def pick_source_folder(self):
        p=filedialog.askdirectory(parent=self.root,title='Select project folder containing editable VMAPs and associated assets',mustexist=True)
        if p: self.src.set(p)
    def pick_output(self):
        p=filedialog.askdirectory(parent=self.root,title='Select output folder',mustexist=False)
        if p: self.out.set(p)
    def pick_vtf(self):
        p=filedialog.askopenfilename(parent=self.root,title='Select VTFCmd.exe',filetypes=[('VTFCmd','VTFCmd.exe'),('Executables','*.exe')])
        if p: self.vtfcmd.set(p)
    def start(self):
        if not self.src.get(): messagebox.showerror('Missing input','Choose an input file or folder.'); return
        src=Path(self.src.get()).expanduser()
        if not src.exists(): messagebox.showerror('Input not found',f'The selected input does not exist:\n{src}'); return
        out=Path(self.out.get()).expanduser()
        self.go.configure(state='disabled'); self.status.set('Starting…'); self.log.insert('end','\n--- Run started ---\n'); self.log.see('end')
        def progress(message):
            self.root.after(0,lambda m=message:self.add_log(m))
        def worker():
            try:
                r=run_conversion(src,out,self.vtfcmd.get(),progress_callback=progress)
                result=f'\nFinished. Status: {r.status}\nWarnings: {len(r.warnings)} | Errors: {len(r.errors)}\nReport: {out / "conversion_report.txt"}\n'
                self.root.after(0,lambda:self.finish(result,r.status))
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.root.after(0,lambda:self.finish('Fatal error: '+str(e),'failed'))
        threading.Thread(target=worker,daemon=True).start()
    def add_log(self,message):
        self.log.insert('end',message+'\n'); self.log.see('end'); self.status.set(message[:90])
    def finish(self,msg,status):
        self.log.insert('end',msg+'\n'); self.log.see('end'); self.status.set(status.capitalize()); self.go.configure(state='normal')
    def open_output(self):
        p=Path(self.out.get())
        if p.exists():
            import os; os.startfile(str(p))
        else: messagebox.showinfo('Output','Output folder does not exist yet.')
    def about(self):
        messagebox.showinfo('Current stage','The app now shows live stages in this window and the command prompt. Folder selection is a separate button from file selection. Current stages include project scanning and resource inventory, supported geometry-export processing, texture conversion, and report generation. Source 2 Viewer is not required. Binary DMX v9 graph parsing and transform inventory are now implemented. VMF brush reconstruction from CMapMesh topology is still the next stage, so this is not yet a complete playable CS:S conversion.')

def launch():
    root=tk.Tk();
    try: ttk.Style().theme_use('vista')
    except Exception: pass
    App(root); root.mainloop()
