import threading, tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from .core import run_conversion

class App:
    def __init__(self, root):
        self.root=root; root.title('S2ToCSS v0.9 — Source 2 to Counter-Strike: Source'); root.geometry('1050x820'); root.minsize(850,650)
        self.src=tk.StringVar(); self.out=tk.StringVar(value=str(Path.cwd()/'converted_css'))
        self.vtfcmd=tk.StringVar(); self.blender=tk.StringVar(); self.studiomdl=tk.StringVar(); self.game_dir=tk.StringVar(); self.materials_root=tk.StringVar(); self.material_map=tk.StringVar(); self.status=tk.StringVar(value='Ready')
        frame=ttk.Frame(root,padding=14); frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Source 2 → Counter-Strike: Source  |  v0.9',font=('Segoe UI',16,'bold')).pack(anchor='w')
        ttk.Label(frame,text='Native editable-VMAP parsing • transform inventory • VMF/material workflow • batch reports').pack(anchor='w',pady=(2,12))
        self._inputrow(frame)
        self._pathrow(frame,'Output folder',self.out,self.pick_output)
        self._pathrow(frame,'VTFCmd.exe (optional)',self.vtfcmd,self.pick_vtf)
        self._pathrow(frame,'Blender.exe (optional)',self.blender,self.pick_blender)
        self._pathrow(frame,'CS:S studiomdl.exe',self.studiomdl,self.pick_studiomdl)
        self._pathrow(frame,'CS:S game folder',self.game_dir,self.pick_game_dir)
        self._pathrow(frame,'Source 2 materials folder',self.materials_root,self.pick_materials_root)
        self._pathrow(frame,'Material map JSON (optional)',self.material_map,self.pick_material_map)
        buttons=ttk.Frame(frame); buttons.pack(fill='x',pady=10)
        self.go=ttk.Button(buttons,text='Convert / Scan',command=self.start); self.go.pack(side='left')
        ttk.Button(buttons,text='Open output folder',command=self.open_output).pack(side='left',padx=8)
        ttk.Button(buttons,text='About limitations',command=self.about).pack(side='left')
        ttk.Label(frame,textvariable=self.status).pack(anchor='w',pady=(0,5))
        self.log=tk.Text(frame,wrap='word',height=22); self.log.pack(fill='both',expand=True)
        self.log.insert('end','Ready. Choose a single VMAP file or use Select project folder for an entire asset tree.\n\nLive progress will appear here and in the command window. Current stages: native binary-DMX v9 parsing, model/material inventory, optional Blender Source Tools FBX/DMX → SMD/QC export, CS:S studiomdl compilation, compiled model staging, model prop entity VMF output, geometry-export handling, loose texture conversion, and reports. Configure Blender, studiomdl, and the CS:S game folder to enable automatic model conversion. Validated convex CMapMesh brush export is enabled; unsupported/complex meshes are skipped with reasons in the mesh report.\n')
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
        p=filedialog.askopenfilename(parent=self.root,title='Select a source map or geometry file',filetypes=[('Source 2 maps, models and geometry','*.vmap *.vmap_c *.dmx *.fbx *.obj *.gltf *.glb *.ply *.stl'),('All files','*.*')])
        if p:
            self.src.set(p)
            selected=Path(p)
            root=selected.parent.parent if selected.is_file() and selected.parent.name.lower()=='maps' else (selected.parent if selected.is_file() else selected)
            materials=root/'materials'
            if materials.is_dir(): self.materials_root.set(str(materials))
    def pick_source_folder(self):
        p=filedialog.askdirectory(parent=self.root,title='Select project folder containing editable VMAPs and associated assets',mustexist=True)
        if p:
            self.src.set(p)
            selected=Path(p)
            root=selected.parent if selected.name.lower() in {'maps','models','materials'} else selected
            materials=root/'materials'
            if materials.is_dir(): self.materials_root.set(str(materials))
    def pick_output(self):
        p=filedialog.askdirectory(parent=self.root,title='Select output folder',mustexist=False)
        if p: self.out.set(p)
    def pick_vtf(self):
        p=filedialog.askopenfilename(parent=self.root,title='Select VTFCmd.exe',filetypes=[('VTFCmd','VTFCmd.exe'),('Executables','*.exe')])
        if p: self.vtfcmd.set(p)
    def pick_blender(self):
        p=filedialog.askopenfilename(parent=self.root,title='Select Blender executable',filetypes=[('Blender','blender.exe'),('Executables','*.exe')])
        if p: self.blender.set(p)
    def pick_studiomdl(self):
        p=filedialog.askopenfilename(parent=self.root,title='Select Counter-Strike: Source studiomdl.exe',filetypes=[('studiomdl','studiomdl.exe'),('Executables','*.exe')])
        if p: self.studiomdl.set(p)
    def pick_game_dir(self):
        p=filedialog.askdirectory(parent=self.root,title='Select the Counter-Strike: Source game folder (the folder containing gameinfo.txt)',mustexist=True)
        if p: self.game_dir.set(p)
    def pick_materials_root(self):
        p=filedialog.askdirectory(parent=self.root,title='Select the addon materials folder',mustexist=True)
        if p: self.materials_root.set(p)
    def pick_material_map(self):
        p=filedialog.askopenfilename(parent=self.root,title='Select Source 1 material mapping JSON',filetypes=[('JSON','*.json'),('All files','*.*')])
        if p: self.material_map.set(p)
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
                r=run_conversion(src,out,self.vtfcmd.get(),progress_callback=progress,toolchain={'blender':self.blender.get(),'studiomdl':self.studiomdl.get(),'game_dir':self.game_dir.get(),'materials_root':self.materials_root.get(),'material_map':self.material_map.get()})
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
        messagebox.showinfo('Current stage','The app shows live progress in this window. It decodes editable binary-DMX VMAP CMapMesh topology, exports supported closed planar convex brushes to VMF, inventories model-backed entities, and can run Blender Source Tools FBX/DMX to SMD/QC plus CS:S studiomdl. It also performs best-effort text-KV3 VMAT-to-VMT conversion, resolves editable VTEX image sources, converts loose textures with VTFCmd, scans model DMX material dependencies, and stages generated materials into the configured CS:S game directory. Common Source 1 entities and structured I/O connections are emitted, including names and keyvalues for compiled model props. Unsupported shaders/parameters, compiled VTEX_C extraction, unknown entity classes, non-unit prop scales, and coordinate conventions still require further work; inspect every output in Hammer.')

def launch():
    root=tk.Tk();
    try: ttk.Style().theme_use('vista')
    except Exception: pass
    App(root); root.mainloop()
