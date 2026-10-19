"""Package a checked Beta EXE, user documentation and original license notices."""
from pathlib import Path
import argparse
import hashlib
from importlib.metadata import distribution
import json
import sys
from zipfile import ZipFile, ZIP_DEFLATED

from packaging.requirements import Requirement

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from lpa import __version__

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-directory',type=Path,required=True)
args=parser.parse_args()
assert 'b' in __version__, 'This packager publishes Beta assets only'
exe=ROOT/'dist/LPA.exe'
source=ROOT/'dist/rocketcea-1.2.3.tar.gz'
assert hashlib.sha256(source.read_bytes()).hexdigest()=='66f306407f11ba36186342dc2716417d3a5c9d94c95b0c5663380091bb11caa9'
archive=ROOT/f'dist/LPA-{__version__}-Windows-x64-Beta.zip'
members={name:ROOT/name for name in ('README.md','THIRD_PARTY_NOTICES.md','CHANGELOG.md')}
members['LPA.exe']=exe
for document in (ROOT/'docs').glob('*.md'):
    members['docs/'+document.name]=document
for screenshot in (ROOT/'docs/ui_layout_outputs_0180').glob('*.png'):
    members['docs/ui_layout_outputs_0180/'+screenshot.name]=screenshot
for screenshot in (ROOT/'docs/thermal_review_outputs_0181').glob('*.png'):
    members['docs/thermal_review_outputs_0181/'+screenshot.name]=screenshot
pending=['numpy','scipy','matplotlib','CoolProp','rocketcea','ht','fluids']
seen=set()
while pending:
    name=pending.pop()
    normalized=name.casefold().replace('_','-')
    if normalized in seen:
        continue
    seen.add(normalized)
    package=distribution(name)
    found=[]
    for item in package.files or ():
        filename=Path(str(item)).name.casefold()
        if not filename.startswith(('license','copying','authors','copyright','notice')):
            continue
        path=Path(package.locate_file(item))
        if path.is_file():
            relative=Path(*[part for part in Path(str(item)).parts if part not in ('..','.')])
            arcname=f'third_party_licenses/{name}/{relative.as_posix()}'
            members[arcname]=path
            found.append(arcname)
    for requirement in package.requires or ():
        dependency=Requirement(requirement)
        if dependency.marker is None or dependency.marker.evaluate({'extra':''}):
            pending.append(dependency.name)
    assert found or normalized not in {'numpy','scipy','matplotlib','coolprop','rocketcea','ht','fluids'}, name
with ZipFile(archive,'w',ZIP_DEFLATED,compresslevel=9) as stream:
    for name,path in sorted(members.items()):
        stream.write(path,arcname=name)
with ZipFile(archive) as stream:
    assert stream.testzip() is None
    for name,path in members.items():
        assert stream.read(name)==path.read_bytes(),name
records=[{'file':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
         for p in (exe,archive,source)]
(ROOT/'dist/SHA256SUMS.txt').write_text(''.join(f"{r['sha256']}  {r['file']}\n" for r in records),encoding='utf-8')
args.output_directory.mkdir(parents=True,exist_ok=True)
record={'version':__version__,'artifacts':records,'zip_members':sorted(members),
        'license_distributions_checked':sorted(seen),'zip_integrity':True,'all_members_match':True}
(args.output_directory/'release_manifest.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
print(json.dumps({'version':__version__,'artifacts':records,'zip_member_count':len(members)},indent=2))
