"""Verify/extract the 0.16.0b1 build without importing host site packages at runtime."""
from pathlib import Path
import types,marshal,hashlib,json
from importlib._bootstrap_external import _code_to_timestamp_pyc
from PyInstaller.archive.readers import CArchiveReader
root=Path(__file__).resolve().parents[1]; bundle=(root/'tmp/release-0.16.0b1-bundle').resolve();bundle.mkdir(parents=True,exist_ok=True)
a=CArchiveReader(str(root/'dist/LPA.exe'));z=a.open_embedded_archive('PYZ.pyz')
def norm(c):return c.replace(co_filename='',co_consts=tuple(norm(v) if isinstance(v,types.CodeType) else v for v in c.co_consts))
mods=[]
for name,entry in z.toc.items():
 code=z.extract(name)
 if not isinstance(code,types.CodeType):continue
 relative=Path(*name.split('.'))
 target=bundle/relative/'__init__.pyc' if entry[0]==1 else (bundle/relative).with_suffix('.pyc')
 assert target.resolve().is_relative_to(bundle)
 target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(_code_to_timestamp_pyc(code))
 if name=='lpa' or name.startswith('lpa.'):
  p=root/relative;p=p/'__init__.py' if p.is_dir() else p.with_suffix('.py')
  assert norm(code)==norm(compile(p.read_text(encoding='utf-8-sig'),str(p),'exec',optimize=1)),name
  mods.append(name)
for name,entry in a.toc.items():
 if entry[-1] not in ('b','x','Z'):continue
 target=bundle/Path(name.replace('\\','/'))
 assert target.resolve().is_relative_to(bundle)
 target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(a.extract(name))
assert norm(marshal.loads(a.extract('main')))==norm(compile((root/'main.py').read_text(encoding='utf-8'),str(root/'main.py'),'exec',optimize=1))
for resource in ('logo.ico','rao_contour_reference.png'):
 assert (bundle/'lpa/resources'/resource).read_bytes()==(root/'lpa/resources'/resource).read_bytes()
licenses=[str(p.relative_to(bundle)) for p in bundle.rglob('*') if p.is_file() and 'license' in p.name.casefold() and any(t in str(p).casefold() for t in ('coolprop-','rocketcea-','scipy-','ht-','fluids-'))]
assert len(licenses)>=5
record={'modules_verified':mods,'module_count':len(mods),'main_matches':True,'resource_matches':True,'licenses':licenses,'exe_sha256':hashlib.sha256((root/'dist/LPA.exe').read_bytes()).hexdigest(),'bundle_path':str(bundle)}
(root/'docs/thermal_beta_outputs_0160/archive_check.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
print('Archive/source/native resources PASS',len(mods),'modules; files',len(a.toc))
