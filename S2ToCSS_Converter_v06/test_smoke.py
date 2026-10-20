from pathlib import Path
from tempfile import TemporaryDirectory
from s2css.core import detect_kind, write_world_vmf, scan_vmap_text, run_conversion

def test_detect():
    assert detect_kind(Path('x.vmap')) == 'editable_vmap'
    assert detect_kind(Path('x.vmap_c')) == 'compiled_vmap'
    assert detect_kind(Path('x.glb')) == 'geometry_export'

def test_vmf():
    with TemporaryDirectory() as d:
        p=Path(d)/'test.vmf'
        write_world_vmf(p,'test',[],[])
        s=p.read_text()
        assert '"classname" "worldspawn"' in s
        assert s.startswith('// Generated')

def test_no_viewer_dependency():
    import inspect
    from s2css import core, gui
    assert 'viewer_cli' not in inspect.signature(core.run_conversion).parameters
    assert 'viewercli' not in inspect.getsource(gui.App)
    assert not hasattr(core, 'run_source2viewer_export')

def test_binary_vmap_inventory():
    with TemporaryDirectory() as d:
        p=Path(d)/'fixture.vmap'
        p.write_bytes(b'<!-- dmx encoding binary 9 format vmap 40 -->\x00models/custom/prop.vmdl\x00materials/custom/wall.vmat\x00')
        inv=scan_vmap_text(p)
        assert inv['encoding']=='binary DMX'
        assert 'models/custom/prop.vmdl' in inv['model_references']
        assert 'materials/custom/wall.vmat' in inv['material_references']
        assert 'not decoded' in inv['note']

if __name__=='__main__':
    test_detect(); test_vmf(); test_binary_vmap_inventory(); test_no_viewer_dependency(); print('Smoke tests passed')
