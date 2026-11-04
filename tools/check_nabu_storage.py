#!/usr/bin/env python3
"""Exercise the generated read-only command, SMMU, GPT and byte-range policies."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from check_darwinboot_8796 import host_command,host_path
from check_capacity_kernel import symbols

ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tree',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--candidate',type=Path)
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    source=a.tree/'iokit/Kernel/nabu_ufs'
    tests=ROOT/'src/ShengUfs/tests'
    headers=a.output/'headers';headers.mkdir(exist_ok=True)
    for p in source.glob('*.h'):shutil.copy2(p,headers/p.name)
    results=[]
    for name in ('TransferPoll','SmmuTakeover','RootLayout'):
        text=(tests/(name+'.cpp')).read_text().replace('#include "../','#include "headers/')
        if name=='RootLayout':
            text=text.replace('for(unsigned i=0;i<8;++i)entries[56+2*i]="userdata"[i];',
                'for(unsigned i=0;i<11;++i)entries[56+2*i]="nabu_system"[i];')
            if sys.platform=='darwin':
                text=text.replace('#include <openssl/sha.h>','''#include <CommonCrypto/CommonDigest.h>
#define SHA256_CTX CC_SHA256_CTX
#define SHA256_Init CC_SHA256_Init
#define SHA256_Update(c,p,n) CC_SHA256_Update(c,p,(CC_LONG)(n))
#define SHA256_Final CC_SHA256_Final
#define SHA256(p,n,d) CC_SHA256(p,(CC_LONG)(n),d)
''')
        (a.output/(name+'.cpp')).write_text(text)
    bridge=(tests/'RootCommandsBridge.cpp').read_text().replace('#include "../','#include "headers/')
    bridge=bridge.replace('uintptr_t hc; void *lock;','uintptr_t hc; void *lock; uint64_t blocks=0x100000000ULL;')
    bridge=bridge.replace('  gStoreOpen=gLogOpen=false; gStoreFirst=gStoreBlocks=gLogFirst=gLogBlocks=0;\n','')
    bridge=re.sub(r'^uint32_t ufs_test_(store_open|log_open|write|sync)\(.*\n','',bridge,flags=re.M)
    (a.output/'RootCommandsBridge.cpp').write_text(bridge)
    text=(tests/'RootCommands.cpp').read_text()
    extra='''  reset(); uint8_t extra[4096]; uint8_t wr[10]={0x2a}; uint32_t stat=0;
  assert(hostScsiDir(0,wr,10,1,4096,1000,&stat)==kIOReturnBadArgument);
  assert(writes==0 && releases==0);
  gHost.blocks=64;
  assert(ufs_test_read(0,63,1,extra)==0);
  auto beforeBounds=writes;
  assert(ufs_test_read(0,64,1,extra)==kIOReturnBadArgument);
  assert(ufs_test_read(0,63,2,extra)==kIOReturnBadArgument);
  assert(writes==beforeBounds);
'''
    text=text.replace('  puts("PASS: actual command/queue path;',extra+'  puts("PASS: actual command/queue path;')
    (a.output/'RootCommands.cpp').write_text(text)
    policy=r'''
#include <cassert>
#include <cstdio>
#include <cstdint>
#include "headers/NabuStoragePolicy.h"
#include "headers/NabuStorageContract.h"
#include "headers/NabuUfsResources.h"
int main() {
  uint64_t offset=0,take=0;
  for (auto &w:nabu_windows) {
    assert(nabuStorageRange(w.bytes,0,w.bytes));
    assert(nabuStorageRange(w.bytes,w.bytes,0));
    assert(!nabuStorageRange(w.bytes,w.bytes,1));
    assert(!nabuStorageRange(w.bytes,UINT64_MAX,2));
    for (uint32_t unit:{512U,1024U,2048U,4096U}) {
      assert(nabuStorageRequest(w.bytes,w.bytes/unit,unit,4096,&offset,&take)&&take==0);
      assert(nabuStorageRequest(w.bytes,w.bytes/unit-1,unit,8192,&offset,&take)&&take==unit);
      assert(!nabuStorageRequest(w.bytes,UINT64_MAX/unit+1,unit,1,&offset,&take));
    }
    assert(!nabuStorageRequest(w.bytes,0,513,1,&offset,&take));
    assert(w.offset>=4096&&w.bytes%4096==0&&w.offset+w.bytes<=NABU_IMAGE_BYTES);
  }
  NabuUfsResources r={{0x1d84000,0x2500},{0x177000,0x1000},{0x15000000,0x100000},0x300,4096};
  assert(nabuUfsResourcesMatch(r));r.stream=0x60;assert(!nabuUfsResourcesMatch(r));
  assert(nabuUfsClocksReady(0x80000000,1,1));
  assert(!nabuUfsClocksReady(0,1,1));
  assert(!nabuUfsClocksReady(0x80000000,0x80000000,1));
  puts("PASS: actual window bounds, sector conversion, overflow, EOF, nabu resources and clock gates");
}
'''.replace('#include <cstdint>','#include <cstdint>\n#include <initializer_list>')
    (a.output/'Policy.cpp').write_text(policy)
    for name in ('TransferPoll','SmmuTakeover','RootLayout','RootCommands','Policy'):
        src=a.output/(name+'.cpp');exe=a.output/name
        command=['clang++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-g',host_path(src),'-o',host_path(exe)]
        if name=='RootLayout' and sys.platform!='darwin':command+=['-lcrypto']
        subprocess.run(host_command(command),check=True)
        run=subprocess.run(host_command([host_path(exe)]),capture_output=True,text=True,encoding='utf-8',errors='replace',check=True)
        (a.output/(name+'.log')).write_text(run.stdout+run.stderr,encoding='utf-8')
        results.append({'name':name,'passed':True,'output':run.stdout.strip()})
    # Ensure the active generated build never includes the removed write API.
    commands=(source/'RootCommands.h').read_text()
    assert '0x2a' not in commands and 'hostWrite4k (' not in commands
    assert '(direction == 1 || direction > 2)' in commands
    report={'passed':True,'tests':results,'scope':'ASan/UBSan on actual generated policies; simulated MMIO/DMA only; no device claim'}
    if a.candidate:
        data=a.candidate.read_bytes();s,segs=symbols(data)
        names=['_nabu_storage_prepare','_nabu_storage_read','_nabu_root_device','_nabu_root_probe_mounted','_nabu_storage_finish']
        ranges=[]
        for name in names:
            va=s[name];end=min(v for v in s.values() if v>va);n=min(end-va,16384)
            assert n and not n%4
            seg=next(x for x in segs if x[0]<=va and va+n<=x[0]+x[3]);off=seg[2]+va-seg[0]
            ranges.append({'name':name,'status':'code-range','address':hex(va),'bytes':n,'sha256':hashlib.sha256(data[off:off+n]).hexdigest()})
        plan={'scope':'Static native UFS/BSD probe instruction identity; not hardware execution','targets':[{'label':'nabu-storage','path':str(a.candidate.resolve()),'sha256':hashlib.sha256(data).hexdigest(),'symbols':ranges}]}
        p=a.output.resolve()/'native-plan.json';p.write_text(json.dumps(plan,indent=2)+'\n')
        env=dict(os.environ,NABU_NATIVE_ANALYSIS_PLAN=str(p),NABU_NATIVE_ANALYSIS_OUTPUT=str(a.output.resolve()/'native-instructions.json'))
        lldb=subprocess.check_output(['xcrun','--find','lldb'],text=True).strip()
        run=subprocess.run([lldb,'--batch','--no-lldbinit','-o','command script import "'+str(ROOT/'tools/lldb_20f66.py')+'"'],env=env,capture_output=True,text=True)
        (a.output/'lldb.log').write_text(run.stdout+run.stderr);assert not run.returncode
        native=json.loads((a.output/'native-instructions.json').read_text());assert native['all_ranges_decoded']
        report.update(candidate_sha256=plan['targets'][0]['sha256'],native_summary=native['summary'])
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
