#!/usr/bin/env python3
"""Extract only local 20F66 launch metadata; keep Apple files out of version control/CI."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--seven-zip',default='C:/Program Files/7-Zip/7z.exe')
    a=ap.parse_args();assert not a.output.exists(), 'Use a new local input directory'
    base=ROOT/'OS/ipados/16.5-20F66-iPad7_11'
    receipt=json.loads((base/'manifests/os-image.json').read_text())
    image=ROOT/receipt['path']
    with image.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
    assert actual==receipt['sha256']
    a.output.mkdir(parents=True)
    listing=subprocess.run([a.seven_zip,'l','-slt','-sccUTF-8',str(image)],capture_output=True,check=True).stdout.decode('utf-8-sig')
    records=[];row={};normalized=[]
    for line in listing.splitlines()+['']:
        if ' = ' in line:
            key,value=line.split(' = ',1)
            if key in ('Path','Symbolic Link'):value=value.replace('\\','/')
            row[key]=value;normalized.append(key+' = '+value)
        else:
            normalized.append(line)
            if not line.strip() and row:records.append(row);row={}
    (a.output/'rootfs.slt').write_text('\n'.join(normalized),encoding='utf-8')
    patterns=['System/Library/LaunchDaemons/*','System/Library/LaunchAngels/*',
              'System/Library/xpc/extensions.plist','System/Library/xpc/extensions.plist.sig']
    dest=a.output/'rootfs'
    with (a.output/'extract.log').open('wb') as log:
        subprocess.run([a.seven_zip,'x','-y','-bsp0','-sccUTF-8','-o'+str(dest),str(image),*patterns],
                       stdout=log,stderr=subprocess.STDOUT,check=True)
    picked=[]
    for r in records:
        p=r.get('Path','')
        if r.get('Alternate Stream')!='-' or not (p.startswith(('System/Library/LaunchDaemons/','System/Library/LaunchAngels/')) or p in patterns[2:]):continue
        assert not r.get('Symbolic Link') and r.get('Mode','').startswith('-'),p
        target=dest/p;data=target.read_bytes();assert len(data)==int(r['Size']),p
        if p.endswith('.plist'):assert isinstance(plistlib.loads(data),dict),p
        picked.append({'path':p,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    assert len(picked)>100
    report={'build':'20F66','product':'iPad7,11','image_sha256':actual,'files':picked,
            'scope':'Local launch metadata only; no boot or service compatibility claim'}
    (a.output/'inputs.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'files':len(picked),'bytes':sum(x['bytes'] for x in picked),'output':str(a.output)}))


if __name__=='__main__':main()
