"""Source 2 to Source 1 conversion scaffold.

Important: VMAP is a DMX document, not a list of VMF brushes. This tool deliberately
uses geometry exports (OBJ/glTF) for deterministic geometry conversion rather than
pretending that arbitrary raw VMAP files can be parsed with regular expressions.
"""
from __future__ import annotations
import csv, json, re, shutil, subprocess, time, traceback
from pathlib import Path
from dataclasses import dataclass, asdict
from .dmx_binary import parse_binary_v9, summarize_graph, extract_transform_records, DMXError

@dataclass
class Report:
    source: str
    output: str
    status: str = "started"
    warnings: list[str] = None
    errors: list[str] = None
    counts: dict = None
    def __post_init__(self):
        self.warnings = self.warnings or []
        self.errors = self.errors or []
        self.counts = self.counts or {}

def discover_inputs(path: Path):
    if path.is_file(): return [path]
    exts={'.vmap','.vmap_c','.obj','.gltf','.glb','.ply','.stl'}
    return sorted(p for p in path.rglob('*') if p.is_file() and (p.suffix.lower() in exts or p.name.endswith('_c')))

def detect_kind(p: Path):
    n=p.name.lower()
    if n.endswith('.vmap_c'): return 'compiled_vmap'
    if p.suffix.lower()=='.vmap': return 'editable_vmap'
    if p.suffix.lower() in ('.obj','.gltf','.glb','.ply','.stl'): return 'geometry_export'
    if n.endswith(('.vmat_c','.vtex_c','.vmdl_c')): return 'compiled_asset'
    return 'unknown'

def _printable_strings(data: bytes, min_len: int = 4) -> list[str]:
    """Recover readable ASCII tokens from binary DMX/VMAP without pretending to decode the graph."""
    return [m.decode('latin1', errors='ignore') for m in re.findall(rb'[\x20-\x7e]{%d,}' % min_len, data)]

def scan_vmap_text(path: Path):
    """Inventory text or binary-DMX VMAP references; not a full geometry parser."""
    data=path.read_bytes()
    strings=_printable_strings(data)
    lower=data[:300].lower()
    encoding_header = strings[0] if strings and strings[0].startswith('<!-- dmx encoding') else ''
    def refs(ext):
        vals=set()
        for token in strings:
            t=token.replace('\\','/')
            # References can be embedded in longer printable strings, so extract paths.
            for match in re.findall(r'(?i)(?:[a-z0-9_ .()\-]+/)*[a-z0-9_ .()\-]+\.'+ext+r'(?=$|[\s\"\x00])', t):
                val=match.strip().strip('"').replace('\\','/')
                if '/' in val or val.lower().endswith('.'+ext): vals.add(val)
        return sorted(vals, key=str.lower)
    result = {
        'file':path.name,
        'bytes':len(data),
        'format_header':encoding_header,
        'encoding':'binary DMX' if b'dmx encoding binary' in lower else ('text DMX' if b'dmx encoding' in lower else 'unknown'),
        'material_references':refs('vmat'),
        'model_references':refs('vmdl'),
        'texture_references':refs('vtex'),
        'note':'String-level reference inventory only.'
    }
    if b'dmx encoding binary 9 format vmap' in lower or b'dmx encoding binary_seqids 9 format vmap' in lower:
        try:
            graph = parse_binary_v9(path)
        except DMXError as parse_error:
            result['dmx_parsed'] = False
            result['dmx_parse_error'] = str(parse_error)
            result['note'] = 'Binary DMX header detected, but the file is incomplete or malformed; references were inventoried from readable strings. Geometry and transforms are not decoded.'
            return result
        summary = summarize_graph(graph)
        transforms = extract_transform_records(graph)
        # Include the VMAP prefix asset list, which is more authoritative than string scanning.
        prefix_refs = []
        for prefix in graph.get('prefix', []):
            values = prefix.get('map_asset_references', [])
            if isinstance(values, list): prefix_refs.extend(x for x in values if isinstance(x, str))
        result.update({
            'dmx_parsed': True,
            'dmx_format': graph['format'],
            'dmx_format_version': graph['format_version'],
            'dmx_element_count': summary['element_count'],
            'dmx_element_type_counts': summary['element_type_counts'],
            'dmx_mesh_type_counts': summary['mesh_type_counts'],
            'dmx_prefix_asset_references': sorted(set(prefix_refs)),
            'dmx_transform_record_count': len(transforms),
            'dmx_transform_records': transforms,
            'dmx_model_references': summary['model_references'],
            'dmx_material_references': summary['material_references'],
            'note':'Binary DMX v9 object graph and transforms are decoded. Mesh coordinates/faces are inventoried but not yet reconstructed into VMF brushes.'
        })
        result['model_references'] = sorted(set(result['model_references']) | set(summary['model_references']))
        result['material_references'] = sorted(set(result['material_references']) | set(summary['material_references']))
    return result

def _resolve_reference(project_root: Path, ref: str, kind: str):
    """Resolve common Source 2 virtual paths against an extracted content tree."""
    normalized=ref.replace('\\','/').lstrip('/')
    candidates=[project_root / normalized]
    if normalized.lower().startswith(('materials/','models/','maps/')):
        candidates.append(project_root / normalized)
    # Search case-insensitively by relative path for Windows-authored projects on Linux too.
    target=normalized.lower()
    for f in project_root.rglob('*'):
        if f.is_file() and f.relative_to(project_root).as_posix().lower()==target:
            return str(f)
    for c in candidates:
        if c.is_file(): return str(c)
    return None

def analyze_project(project_root: Path, output_dir: Path, progress_callback=None):
    """Write a practical dependency inventory for editable VMAPs and loose source assets."""
    def progress(message):
        if progress_callback: progress_callback(message)
    progress(f'Scanning project folder: {project_root}')
    maps=sorted(project_root.rglob('*.vmap'))
    progress(f'Found {len(maps)} editable VMAP file(s). Reading resource references…')
    all_maps=[]; models=set(); materials=set(); textures=set()
    for index, p in enumerate(maps, 1):
        progress(f'[{index}/{len(maps)}] Inventorying VMAP: {p.name}')
        inv=scan_vmap_text(p); all_maps.append(inv)
        models.update(inv['model_references']); materials.update(inv['material_references']); textures.update(inv['texture_references'])
    progress(f'Resolving {len(models)} model, {len(materials)} material, and {len(textures)} texture references…')
    model_rows=[]
    for ref in sorted(models, key=str.lower):
        found=_resolve_reference(project_root, ref, 'model')
        model_rows.append({'reference':ref,'resolved_file':found,'exists':bool(found)})
    material_rows=[]
    for ref in sorted(materials, key=str.lower):
        found=_resolve_reference(project_root, ref, 'material')
        material_rows.append({'reference':ref,'resolved_file':found,'exists':bool(found)})
    texture_rows=[]
    for ref in sorted(textures, key=str.lower):
        found=_resolve_reference(project_root, ref, 'texture')
        texture_rows.append({'reference':ref,'resolved_file':found,'exists':bool(found)})
    counts={}
    progress('Counting project asset types…')
    for ext in ['.vmap','.vmdl','.vmat','.vtex','.dmx','.fbx','.png','.tga','.jpg','.jpeg','.bmp','.vtf','.vmdl_c','.vmat_c','.vtex_c']:
        counts[ext]=sum(1 for f in project_root.rglob('*') if f.is_file() and f.name.lower().endswith(ext))
    report={
        'project_root':str(project_root),
        'map_files':[str(p) for p in maps],
        'file_counts':counts,
        'maps':all_maps,
        'referenced_models':model_rows,
        'referenced_materials':material_rows,
        'referenced_textures':texture_rows,
        'summary':{
            'editable_maps':len(maps),
            'unique_model_references':len(models),
            'unique_material_references':len(materials),
            'model_refs_found':sum(r['exists'] for r in model_rows),
            'model_refs_missing':sum(not r['exists'] for r in model_rows),
            'material_refs_found':sum(r['exists'] for r in material_rows),
            'material_refs_missing':sum(not r['exists'] for r in material_rows),
        },
        'limitations':[
            'Binary DMX v9 object graph and selected transform records are decoded; schema-aware geometry conversion is not complete.',
            'CMapMesh topology and vertex streams are inventoried but not yet reconstructed as VMF convex solids.',
            'No playable VMF is generated from an editable VMAP by the inventory step alone.',
        ]
    }
    output_dir.mkdir(parents=True,exist_ok=True)
    (output_dir/'project_inventory.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    lines=['S2ToCSS project inventory',f'Project: {project_root}','', 'File counts:']
    lines += [f'  {k}: {v}' for k,v in counts.items() if v]
    lines += ['', 'Reference summary:']
    lines += [f'  Editable VMAPs: {len(maps)}',f'  Unique model references: {len(models)} (found {report["summary"]["model_refs_found"]}, missing {report["summary"]["model_refs_missing"]})',f'  Unique material references: {len(materials)} (found {report["summary"]["material_refs_found"]}, missing {report["summary"]["material_refs_missing"]})','', 'VMAPs:']
    for inv in all_maps:
        lines.append(f'  {inv["file"]}: {inv["bytes"]:,} bytes; {len(inv["model_references"])} model refs; {len(inv["material_references"])} material refs; {inv["format_header"] or inv["encoding"]}')
    lines += ['', 'Limitations:'] + [f'  - {x}' for x in report['limitations']]
    (output_dir/'project_inventory.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    # Human-friendly placement inventory for Hammer model/entity transforms.
    csv_path=output_dir/'vmap_transform_inventory.csv'
    with csv_path.open('w', newline='', encoding='utf-8-sig') as f:
        fields=['map_file','index','class','name','origin_x','origin_y','origin_z','pitch','yaw','roll','scale_x','scale_y','scale_z','mesh_face_count','mesh_vertex_count','mesh_materials','entity_properties_class']
        writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader()
        for inv in all_maps:
            for row in inv.get('dmx_transform_records',[]):
                origin=row.get('origin') or [None,None,None]; angles=row.get('angles') or [None,None,None]; scales=row.get('scales') or [None,None,None]
                origin=(list(origin)+[None]*3)[:3]; angles=(list(angles)+[None]*3)[:3]; scales=(list(scales)+[None]*3)[:3]
                writer.writerow({'map_file':inv['file'],'index':row.get('index'),'class':row.get('class'),'name':row.get('name'),
                    'origin_x':origin[0],'origin_y':origin[1],'origin_z':origin[2],'pitch':angles[0],'yaw':angles[1],'roll':angles[2],
                    'scale_x':scales[0],'scale_y':scales[1],'scale_z':scales[2],'mesh_face_count':row.get('mesh_face_count'),
                    'mesh_vertex_count':row.get('mesh_vertex_count'),'mesh_materials':';'.join(row.get('mesh_materials') or []),
                    'entity_properties_class':row.get('entity_properties_class')})
    report['transform_inventory_csv']=str(csv_path)
    report['summary']['parsed_vmaps']=sum(bool(x.get('dmx_parsed')) for x in all_maps)
    report['summary']['transform_records']=sum(x.get('dmx_transform_record_count',0) for x in all_maps)
    return report

def vmf_header(mapname):
    return f"""// Generated by S2ToCSS Converter. Review before compiling.\nversioninfo\n{{\n "editorversion" "400"\n "editorbuild" "0"\n "mapversion" "1"\n "formatversion" "100"\n "prefab" "0"\n}}\nvisgroups\n{{\n}}\nviewsettings\n{{\n "bSnapToGrid" "1"\n "bShowGrid" "1"\n "bShowLogicalGrid" "0"\n "nGridSpacing" "64"\n "bShow3DGrid" "0"\n}}\nworld\n{{\n "id" "1"\n "mapversion" "1"\n "classname" "worldspawn"\n "detailmaterial" "detail/detailsprites"\n "detailvbsp" "detail.vbsp"\n "maxpropscreenwidth" "-1"\n "skyname" "sky_day01_01"\n}}\n"""

def quote(s): return str(s).replace('\\','/').replace('"','\\"')

def write_world_vmf(out: Path, mapname: str, brushes: list, prop_entities: list):
    # brushes entries are list of 3D polygon faces, each face list of 3 vertices.
    parts=[vmf_header(mapname)]
    bid=2
    for brush in brushes:
        parts.append(f' solid\n {{\n  "id" "{bid}"\n'); bid+=1
        for face in brush:
            if len(face)<3: continue
            a,b,c=face[:3]
            # Source 1 VMF plane syntax: three points in world coordinates.
            parts.append('  side\n  {\n')
            parts.append(f'   "id" "{bid}"\n'); bid+=1
            parts.append('   "plane" "(%g %g %g) (%g %g %g) (%g %g %g)"\n' % (*a,*b,*c))
            parts.append('   "material" "TOOLS/TOOLSNODRAW"\n   "uaxis" "[1 0 0 0] 0.25"\n   "vaxis" "[0 -1 0 0] 0.25"\n   "rotation" "0"\n   "lightmapscale" "16"\n   "smoothing_groups" "0"\n  }\n')
        parts.append(' }\n')
    for e in prop_entities:
        parts.append('entity\n{\n')
        for k,v in e.items(): parts.append(f' "{quote(k)}" "{quote(v)}"\n')
        parts.append('}\n')
    out.write_text(''.join(parts),encoding='utf-8')

def mesh_to_vmf(mesh_path: Path, output_dir: Path, report: Report, mode='static_props', max_faces=5000):
    try:
        import trimesh
    except ImportError:
        raise RuntimeError('Mesh import needs trimesh. Run: py -m pip install -r requirements.txt')
    mesh=trimesh.load(mesh_path, force='scene', process=False)
    if isinstance(mesh,trimesh.Scene):
        geoms=list(mesh.geometry.values())
    else: geoms=[mesh]
    if not geoms: raise RuntimeError('No mesh geometry found.')
    out_assets=output_dir/'models'/'s2_import'
    out_assets.mkdir(parents=True,exist_ok=True)
    props=[]; brushes=[]; total_faces=0; model_count=0
    # Export mesh objects as OBJ for manual Blender-to-SMD/DMX conversion. Source 1 cannot load OBJ directly.
    for i,g in enumerate(geoms):
        if not hasattr(g,'faces') or len(g.faces)==0: continue
        total_faces+=len(g.faces)
        safe=f'{mesh_path.stem}_{i:03d}'
        obj_path=out_assets/f'{safe}.obj'
        try: g.export(obj_path)
        except Exception as ex: report.warnings.append(f'OBJ export failed for {safe}: {ex}'); continue
        # Model entity placeholder. Must point to a compiled Source 1 .mdl, not the OBJ.
        props.append({'id':str(10000+i),'classname':'prop_static','origin':'0 0 0','angles':'0 0 0',
                      'model':f'models/s2_import/{safe}.mdl','solid':'6','disableshadows':'0'})
        model_count+=1
    if total_faces>max_faces: report.warnings.append(f'Mesh has {total_faces} faces; consider splitting it into smaller props for performance.')
    if model_count:
        report.warnings.append('Static prop entities are placeholders until each exported OBJ is converted to SMD/DMX and compiled with studiomdl.')
    vmf=output_dir/f'{mesh_path.stem}_converted.vmf'
    write_world_vmf(vmf,mesh_path.stem,brushes,props)
    report.counts.update({'mesh_objects':len(geoms),'triangles_or_faces':total_faces,'static_prop_placeholders':model_count})
    report.status='partial'
    report.warnings.append('Geometry was exported as OBJ and referenced as prop_static; Source 1 models were NOT compiled automatically by this stage.')
    return vmf

def convert_texture_folder(source: Path, output_dir: Path, vtfcmd: str, report: Report):
    """Convert common raster files with VTFCmd if configured, and write simple VMTs."""
    texout=output_dir/'materials'/'s2_import'; texout.mkdir(parents=True,exist_ok=True)
    supported={'.png','.tga','.jpg','.jpeg','.bmp','.tif','.tiff'}
    images=[p for p in source.rglob('*') if p.is_file() and p.suffix.lower() in supported]
    if not images:
        report.warnings.append('No loose raster textures found. Compiled .vtex_c extraction is not implemented; provide loose source images when available.')
        return 0
    if not vtfcmd or not Path(vtfcmd).exists():
        report.warnings.append(f'Found {len(images)} images but VTFCmd is not configured; images copied for later conversion.')
        for p in images:
            dest=texout/p.name; shutil.copy2(p,dest)
            (texout/(p.stem+'.vmt')).write_text(f'"VertexLitGeneric"\n{{\n "$basetexture" "s2_import/{p.stem}"\n}}\n',encoding='utf-8')
        return len(images)
    count=0
    for p in images:
        dest=texout/(p.stem+'.vtf')
        try:
            # VTFCmd versions differ; common CLI supports -file and -output.
            subprocess.run([vtfcmd,'-file',str(p),'-output',str(texout)],check=True,capture_output=True,text=True)
            (texout/(p.stem+'.vmt')).write_text(f'"VertexLitGeneric"\n{{\n "$basetexture" "s2_import/{p.stem}"\n}}\n',encoding='utf-8')
            count+=1
        except Exception as ex: report.errors.append(f'Texture conversion failed for {p}: {ex}')
    return count

def run_conversion(input_path: Path, output_dir: Path, vtfcmd='', report_callback=None, progress_callback=None):
    def progress(message):
        print('[S2ToCSS] '+message, flush=True)
        if progress_callback: progress_callback(message)
    output_dir.mkdir(parents=True,exist_ok=True)
    report=Report(str(input_path),str(output_dir))
    progress(f'Input: {input_path}')
    progress(f'Output: {output_dir}')
    progress('Discovering supported map, mesh, and asset files…')
    found=discover_inputs(input_path)
    progress(f'Discovery complete: {len(found)} supported file(s) found.')
    report.counts['discovered_files']=len(found)
    if input_path.is_dir() and any(input_path.rglob('*.vmap')):
        try:
            project_report = analyze_project(input_path, output_dir, progress_callback=progress)
            report.counts['project_inventory'] = project_report['summary']
        except Exception as analysis_error:
            report.warnings.append(f'Project dependency inventory failed: {analysis_error}')
    if not found:
        report.errors.append('No supported input files found.'); report.status='failed'
    for index, p in enumerate(found, 1):
        kind=detect_kind(p)
        progress(f'Processing file {index}/{len(found)}: {p.name} [{kind}]')
        try:
            if kind=='editable_vmap':
                progress(f'Parsing binary DMX graph and extracting Hammer transforms from {p.name}…')
                inv=scan_vmap_text(p)
                invpath=output_dir/(p.stem+'_inventory.json')
                invpath.write_text(json.dumps(inv,indent=2),encoding='utf-8')
                report.counts.setdefault('vmap_inventory_files', []).append(str(invpath))
                if inv.get('dmx_parsed'):
                    csv_path=output_dir/(p.stem+'_transform_inventory.csv')
                    fields=['index','class','name','origin_x','origin_y','origin_z','pitch','yaw','roll','scale_x','scale_y','scale_z','mesh_face_count','mesh_vertex_count','mesh_materials','entity_properties_class']
                    with csv_path.open('w',newline='',encoding='utf-8-sig') as f:
                        writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader()
                        for row in inv.get('dmx_transform_records',[]):
                            origin=(list(row.get('origin') or [])+[None]*3)[:3]; angles=(list(row.get('angles') or [])+[None]*3)[:3]; scales=(list(row.get('scales') or [])+[None]*3)[:3]
                            writer.writerow({'index':row.get('index'),'class':row.get('class'),'name':row.get('name'),'origin_x':origin[0],'origin_y':origin[1],'origin_z':origin[2],
                                'pitch':angles[0],'yaw':angles[1],'roll':angles[2],'scale_x':scales[0],'scale_y':scales[1],'scale_z':scales[2],
                                'mesh_face_count':row.get('mesh_face_count'),'mesh_vertex_count':row.get('mesh_vertex_count'),'mesh_materials':';'.join(row.get('mesh_materials') or []),
                                'entity_properties_class':row.get('entity_properties_class')})
                    report.counts.setdefault('transform_csv_outputs',[]).append(str(csv_path))
                    progress(f'DMX parse complete: {inv.get("dmx_element_count",0)} elements; {inv.get("dmx_transform_record_count",0)} transform records.')
                report.warnings.append(f'{p.name}: editable VMAP graph and transform inventory generated. VMF brush reconstruction from mesh topology is not complete yet.')
            elif kind=='compiled_vmap':
                report.warnings.append(f'{p.name}: compiled VMAP detected. This converter does not require compiled maps; select the editable .vmap and its associated assets for native parsing.')
            elif kind=='geometry_export':
                vmf=mesh_to_vmf(p,output_dir,report)
                report.counts.setdefault('vmf_outputs',[]).append(str(vmf))
            elif kind=='compiled_asset':
                report.warnings.append(f'{p.name}: compiled Source 2 asset detected. Native extraction for this compiled asset type is not implemented yet; provide editable/source assets when available.')
        except Exception as ex:
            report.errors.append(f'{p}: {ex}')
    # Loose raster textures can be converted when the user selected a directory.
    texture_root = input_path if input_path.is_dir() else input_path.parent
    try:
        progress('Checking loose textures and running configured VTF conversion if available…')
        texture_count = convert_texture_folder(texture_root, output_dir, vtfcmd, report)
        if texture_count:
            report.counts['raster_textures_processed'] = texture_count
    except Exception as ex:
        report.errors.append(f'Texture pipeline error: {ex}')
    # Generate QC templates for SMD files the user has placed in the output model source folder.
    smd_root = output_dir / 'models' / 's2_import'
    if smd_root.exists():
        for smd in smd_root.rglob('*.smd'):
            qc = smd.with_suffix('.qc')
            if not qc.exists():
                qc.write_text(f'$modelname \"s2_import/{smd.stem}.mdl\"\n$body \"body\" \"{smd.name}\"\n$staticprop\n$surfaceprop \"default\"\n$cdmaterials \"models/s2_import\"\n$sequence \"idle\" \"{smd.name}\"\n', encoding='utf-8')
        if any(smd_root.rglob('*.smd')):
            report.warnings.append('QC files generated for SMD sources. Configure/run the Counter-Strike: Source studiomdl compiler separately; automatic compilation is not configured in this build.')
    if report.errors: report.status='failed' if not report.counts.get('vmf_outputs') else 'partial'
    elif report.status=='started': report.status='partial' if report.warnings else 'success'
    progress('Writing conversion_report.json and conversion_report.txt…')
    report_path=output_dir/'conversion_report.json'
    report_path.write_text(json.dumps(asdict(report),indent=2),encoding='utf-8')
    (output_dir/'conversion_report.txt').write_text(format_report(report),encoding='utf-8')
    if report_callback: report_callback(format_report(report))
    progress(f'Run complete: status={report.status}, warnings={len(report.warnings)}, errors={len(report.errors)}.')
    return report

def format_report(r):
    lines=[f'S2ToCSS Converter report','Source: '+r.source,'Output: '+r.output,'Status: '+r.status,'','Counts:']
    lines += [f'  {k}: {v}' for k,v in r.counts.items()]
    lines += ['',f'Warnings ({len(r.warnings)}):'] + [f'  - {x}' for x in r.warnings]
    lines += ['',f'Errors ({len(r.errors)}):'] + [f'  - {x}' for x in r.errors]
    return '\n'.join(lines)+'\n'
