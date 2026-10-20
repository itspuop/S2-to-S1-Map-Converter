"""Minimal defensive reader for Source 2 binary DMX v9 files (including editable VMAP).

Reads the generic DMX graph without relying on compiled map data. This is an inventory/
extraction reader, not yet a complete schema-aware Hammer geometry serializer.
"""
from __future__ import annotations
import re, struct, uuid
from pathlib import Path

class DMXError(ValueError):
    pass

class Reader:
    def __init__(self, data: bytes):
        self.data=data; self.pos=0
    def take(self,n):
        if n < 0 or self.pos+n > len(self.data):
            raise DMXError(f"Unexpected end of DMX at offset {self.pos}, wanted {n} bytes")
        b=self.data[self.pos:self.pos+n]; self.pos+=n; return b
    def i32(self): return struct.unpack('<i',self.take(4))[0]
    def u8(self): return self.take(1)[0]
    def u64(self): return struct.unpack('<Q',self.take(8))[0]
    def f32(self): return struct.unpack('<f',self.take(4))[0]
    def cstr(self, maxlen=16*1024*1024):
        end=self.data.find(b'\0',self.pos,min(len(self.data),self.pos+maxlen))
        if end<0: raise DMXError(f"Unterminated string at offset {self.pos}")
        b=self.data[self.pos:end]; self.pos=end+1
        return b.decode('utf-8',errors='replace')

TYPE_NAMES={1:'element',2:'int',3:'float',4:'bool',5:'string',6:'binary',7:'time',8:'color',9:'vector2',10:'vector3',11:'vector4',12:'qangle',13:'quaternion',14:'matrix',15:'uint64',16:'uint8'}

def parse_binary_v9(path: Path | str, include_binary=False):
    data=Path(path).read_bytes() if isinstance(path,(str,Path)) else path
    nul=data.find(b'\0')
    if nul<0: raise DMXError('Missing binary DMX header terminator')
    header=data[:nul].decode('ascii',errors='replace')
    m=re.match(r'<!--\s*dmx encoding (binary|binary_seqids) 9 format ([^ ]+) (\d+) -->',header)
    if not m: raise DMXError(f'Unsupported DMX header: {header[:120]}')
    encoding,fmt,format_version=m.group(1),m.group(2),int(m.group(3))
    r=Reader(data); r.pos=nul+1
    # Prefix elements are present only in binary v9.
    prefix_count=r.i32();
    if prefix_count<0 or prefix_count>10000: raise DMXError(f'Invalid prefix element count: {prefix_count}')
    prefixes=[]
    for _ in range(prefix_count):
        ac=r.i32()
        if ac<0 or ac>100000: raise DMXError(f'Invalid prefix attribute count: {ac}')
        attrs={}
        for _ in range(ac):
            name=r.cstr(); typ=r.u8(); attrs[name]=_read_value(r,typ,[],version=9,prefix=True,include_binary=include_binary)
        prefixes.append(attrs)
    sc=r.i32()
    if sc<0 or sc>2_000_000: raise DMXError(f'Invalid string table count: {sc}')
    strings=[r.cstr() for _ in range(sc)]
    def string_ref():
        i=r.i32()
        if i<0 or i>=len(strings): raise DMXError(f'Invalid string table reference {i} at {r.pos}')
        return strings[i]
    ec=r.i32()
    if ec<0 or ec>5_000_000: raise DMXError(f'Invalid element count: {ec}')
    headers=[]
    for i in range(ec):
        typ=string_ref(); name=string_ref(); guid_bytes=r.take(16)
        headers.append({'type':typ,'name':name,'guid':str(uuid.UUID(bytes_le=guid_bytes))})
    elements=[]
    for i in range(ec):
        ac=r.i32()
        if ac<0 or ac>1_000_000: raise DMXError(f'Invalid attribute count {ac} on element {i}')
        attrs={}
        for _ in range(ac):
            name=string_ref(); typ=r.u8(); attrs[name]=_read_value(r,typ,strings,version=9,prefix=False,include_binary=include_binary)
        e=headers[i]; e['attributes']=attrs; elements.append(e)
    return {'header':header,'encoding':encoding,'format':fmt,'format_version':format_version,'prefix':prefixes,'elements':elements,'bytes_read':r.pos,'file_bytes':len(data),'trailing_bytes':len(data)-r.pos}

def _read_value(r, typ, strings, version=9, prefix=False, include_binary=False):
    is_array=typ>=33 and typ<=48
    base=typ-32 if is_array else typ
    if base not in TYPE_NAMES: raise DMXError(f'Unknown DMX type id {typ} at offset {r.pos}')
    if is_array:
        count=r.i32()
        if count<0 or count>20_000_000: raise DMXError(f'Invalid array count {count} at offset {r.pos}')
        return [_read_scalar(r,base,strings,version,prefix,include_binary,inside_array=True) for _ in range(count)]
    return _read_scalar(r,base,strings,version,prefix,include_binary,inside_array=False)

def _read_scalar(r, typ, strings, version, prefix, include_binary, inside_array=False):
    if typ==1:
        idx=r.i32()
        if idx>=0: return {'element_index':idx}
        if idx==-1: return None
        if idx==-2: return {'external_guid':r.cstr()}
        raise DMXError(f'Invalid element reference {idx}')
    if typ==2: return r.i32()
    if typ==3: return r.f32()
    if typ==4: return bool(r.u8())
    if typ==5:
        if not prefix and version>=4 and not inside_array:
            idx=r.i32()
            if idx<0 or idx>=len(strings): raise DMXError(f'Invalid string ref {idx}')
            return strings[idx]
        return r.cstr()
    if typ==6:
        n=r.i32()
        if n<0 or n>len(r.data)-r.pos: raise DMXError(f'Invalid binary length {n}')
        b=r.take(n)
        return {'binary_bytes':n,'hex':b.hex() if include_binary else None}
    if typ==7: return r.i32()/10000.0
    if typ==8: return list(r.take(4))
    if typ in (9,10,11,12,13,14):
        n={9:2,10:3,11:4,12:3,13:4,14:16}[typ]
        return list(struct.unpack('<'+'f'*n,r.take(4*n)))
    if typ==15: return r.u64()
    if typ==16: return r.u8()
    raise DMXError(f'Unsupported DMX type {typ}')

def resolve_value(value, elements):
    if isinstance(value,dict) and 'element_index' in value:
        i=value['element_index']
        if 0 <= i < len(elements):
            e=elements[i]
            return {'element_index':i,'type':e['type'],'name':e['name'],'guid':e['guid']}
        return value
    if isinstance(value,list): return [resolve_value(v,elements) for v in value]
    return value

def summarize_graph(graph):
    elements=graph['elements']; by_type={}; model_instances=[]; entities=[]; mesh_types={};
    material_refs=set(); model_refs=set(); asset_refs=[]
    for p in graph.get('prefix',[]):
        ar=p.get('map_asset_references')
        if isinstance(ar,list): asset_refs.extend(str(x) for x in ar)
    for idx,e in enumerate(elements):
        by_type[e['type']]=by_type.get(e['type'],0)+1
        a=e['attributes']; typ=e['type'].lower()
        for k,v in a.items():
            if isinstance(v,str):
                vl=v.replace('\\','/')
                if vl.lower().endswith('.vmdl'): model_refs.add(vl)
                elif vl.lower().endswith('.vmat'): material_refs.add(vl)
                elif vl.lower().endswith('.vtex'): asset_refs.append(vl)
        if 'entity' in typ or typ in ('cmapentity','cmapinstancedentity'):
            entities.append({'index':idx,'type':e['type'],'name':e['name'],'guid':e['guid'],'attributes':_json_safe_attrs(a,elements)})
        # Record nodes likely to contain model path + transforms; intentionally schema-neutral.
        if any(k.lower() in a for k in ('model','modelname','modelpath','modeldoc','targetname')) or any(k.lower() in a for k in ('origin','angles','rotation','scaling','scale','transform')):
            row={'index':idx,'type':e['type'],'name':e['name'],'guid':e['guid'],'attributes':_json_safe_attrs(a,elements)}
            model_instances.append(row)
        if 'mesh' in typ:
            mesh_types[e['type']]=mesh_types.get(e['type'],0)+1
    return {'element_count':len(elements),'element_type_counts':dict(sorted(by_type.items(),key=lambda kv:(-kv[1],kv[0]))),'mesh_type_counts':mesh_types,'entity_like_elements':entities,'transform_or_model_candidates':model_instances,'model_references':sorted(model_refs),'material_references':sorted(material_refs),'prefix_asset_references':sorted(set(asset_refs))}

def _json_safe_attrs(attrs,elements):
    out={}
    for k,v in attrs.items():
        if isinstance(v,dict) and 'binary_bytes' in v: out[k]=f"<binary {v['binary_bytes']} bytes>"
        else: out[k]=resolve_value(v,elements)
    return out

def extract_transform_records(graph):
    """Extract actual map-node transform records from the generic DMX graph."""
    elements=graph['elements']; rows=[]
    for idx,e in enumerate(elements):
        if e['type'] not in ('CMapMesh','CMapEntity','CMapGroup','CMapPathNode','CMapStaticOverlay'):
            continue
        a=e['attributes']
        origin=a.get('origin'); angles=a.get('angles'); scales=a.get('scales') or a.get('scale')
        if origin is None and angles is None and scales is None and e['type'] not in ('CMapMesh','CMapEntity'):
            continue
        row={'index':idx,'class':e['type'],'name':e.get('name',''),'guid':e.get('guid'),
             'origin':origin,'angles':angles,'scales':scales,
             'nodeID':a.get('nodeID'),'referenceID':a.get('referenceID'),
             'editorOnly':a.get('editorOnly'),'force_hidden':a.get('force_hidden')}
        md=a.get('meshData')
        if isinstance(md,dict) and 'element_index' in md:
            mi=md['element_index']
            if 0<=mi<len(elements):
                mesh=elements[mi]
                ma=mesh['attributes']
                row['meshData_index']=mi
                row['meshData_class']=mesh['type']
                row['mesh_materials']=ma.get('materials',[])
                row['mesh_vertex_count']=_stream_size(elements,ma.get('vertexData'))
                row['mesh_face_vertex_count']=_stream_size(elements,ma.get('faceVertexData'))
                row['mesh_face_count']=len(ma.get('faceEdgeIndices',[]))
        # Resolve entity_properties to capture Source 2 entity class/model path where present.
        ep=a.get('entity_properties')
        if isinstance(ep,dict) and 'element_index' in ep and 0<=ep['element_index']<len(elements):
            ee=elements[ep['element_index']]
            row['entity_properties_class']=ee['type']
            row['entity_properties']=_json_safe_attrs(ee['attributes'],elements)
        rows.append(row)
    return rows

def _stream_size(elements, ref):
    if not isinstance(ref,dict) or 'element_index' not in ref: return None
    i=ref['element_index']
    if not 0<=i<len(elements): return None
    attrs=elements[i]['attributes']; n=attrs.get('size')
    if isinstance(n,int): return n
    streams=attrs.get('streams',[])
    sizes=[]
    for s in streams:
        if isinstance(s,dict) and 'element_index' in s:
            si=s['element_index']
            if 0<=si<len(elements):
                data=elements[si]['attributes'].get('data')
                if isinstance(data,list): sizes.append(len(data))
    return max(sizes) if sizes else None
