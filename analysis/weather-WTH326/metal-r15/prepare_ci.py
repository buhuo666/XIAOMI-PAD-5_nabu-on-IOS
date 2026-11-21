"""Stage only final authored sources, ABI expectations and host test runners."""
from pathlib import Path
import json,shutil
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
out=HERE/'ci';out.mkdir(exist_ok=True)
source=HERE/'metal-source';destination=out/'frontend';destination.mkdir(exist_ok=True)
# Include only frontend source/header includes, not SDKs, firmware or device logs.
files=[]
for p in source.rglob('*'):
    if p.suffix not in ('.h','.inc','.mm') or 'patches' in p.parts:continue
    target=destination/p.relative_to(source);target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(p,target);files.append(str(target.relative_to(ROOT)).replace('\\','/'))
abi=HERE/'workers/encoders/runtime-abi'
for name in ['run_runtime_abi.py','runtime_abi.mm']:
    shutil.copyfile(abi/name,out/name)
shutil.copyfile(HERE/'audit/final/abi/expected-methods.json',out/'expected-methods.json')
shutil.copyfile(HERE/'audit/pipelines/generate_queue_test.py',out/'generate_queue_test.py')
(out/'input-manifest.json').write_text(json.dumps(dict(source=str(source),frontend_files=files,scope='Authored frontend/tests and ABI metadata; no Apple binaries, SDK or device logs'),indent=2)+'\n')
print(json.dumps(dict(files=len(files),destination=str(out))))
