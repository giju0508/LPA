"""Verify/extract a release build without host site packages at runtime."""
from pathlib import Path
import argparse,ast,types,marshal,hashlib,json
from importlib._bootstrap_external import _code_to_timestamp_pyc
from PyInstaller.archive.readers import CArchiveReader
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--version',required=True)
parser.add_argument('--output-directory',type=Path)
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
assert args.version and all(c.isalnum() or c in '.-' for c in args.version)
version_tree=ast.parse((root/'lpa/__init__.py').read_text(encoding='utf-8'))
source_version=next(ast.literal_eval(node.value) for node in version_tree.body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='__version__' for target in node.targets))
assert args.version==source_version, f'Requested {args.version}, source is {source_version}'
bundle_candidate=root/f'tmp/release-{args.version}-bundle'
if bundle_candidate.exists() and any(bundle_candidate.iterdir()):
 raise RuntimeError(f'Extraction requires an empty directory: {bundle_candidate}')
bundle=(root/f'tmp/release-{args.version}-bundle').resolve();bundle.mkdir(parents=True,exist_ok=True)
output=(args.output_directory or root/f'docs/release_outputs_{args.version}').resolve();output.mkdir(parents=True,exist_ok=True)
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
for dependency in ('coolprop','rocketcea','scipy','ht','fluids'):
 assert any(f'{dependency}-' in path.casefold() for path in licenses), f'Missing license: {dependency}'
record={'version':args.version,'modules_verified':mods,'module_count':len(mods),'main_matches':True,'resource_matches':True,'licenses':licenses,'exe_sha256':hashlib.sha256((root/'dist/LPA.exe').read_bytes()).hexdigest(),'bundle_path':str(bundle)}
(output/'archive_check.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
print('Archive/source/native resources PASS',len(mods),'modules; files',len(a.toc))
