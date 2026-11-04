#!/usr/bin/env python3
"""Prepare read-only system windows and a separately bounded append-only native log writer."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def replace_once(text,old,new):
    if text.count(old)!=1: raise ValueError('Expected one anchor: '+old[:100])
    return text.replace(old,new,1)


def c_function(text,name):
    at=text.index(name+' (')
    start=text.rfind('\nstatic ',0,at)+1
    body=text.index('{',at);end=body+1;depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]


def contract_header(cfg):
    def array(s):return '{'+','.join('0x'+s[i:i+2] for i in range(0,len(s),2))+'}'
    w=cfg['windows'];assert len(w)==2 and [x['name'] for x in w]==['OS','SystemOS']
    assert cfg['partition_name']=='nabu_system' and cfg['writes_enabled'] is False
    assert cfg['logical_block_bytes']==4096
    end=4096
    for row in w:
        assert row['offset']>=end and row['offset']%4096==row['bytes']%4096==0
        end=row['offset']+row['bytes'];assert end<=cfg['image_bytes']<=cfg['partition_bytes']
        assert len(bytes.fromhex(row['image_sha256']))==len(bytes.fromhex(row['superblock_sha256']))==32
    f=cfg['probe_file'];assert f['path']=='/sbin/launchd' and 0<f['bytes']<16*1024*1024
    return ('// Generated from configs/nabu-storage-probe.json; no firmware bytes.\n#pragma once\n'
        '#include <stdint.h>\n'
        f'#define NABU_PARTITION_BYTES {cfg["partition_bytes"]}ULL\n#define NABU_IMAGE_BYTES {cfg["image_bytes"]}ULL\n'
        f'#define NABU_PROBE_PATH "{f["path"]}"\n#define NABU_PROBE_BYTES {f["bytes"]}ULL\n'
        'static const uint8_t nabu_probe_sha256[32]='+array(f['sha256'])+';\n'
        'struct NabuStorageWindow {const char *name;uint64_t offset,bytes;uint8_t image_sha256[32],superblock_sha256[32];};\n'
        'static const struct NabuStorageWindow nabu_windows[2]={\n'+',\n'.join(
            '{"'+x['name']+'",'+str(x['offset'])+'ULL,'+str(x['bytes'])+'ULL,'+
            array(x['image_sha256'])+','+array(x['superblock_sha256'])+'}' for x in w)+'\n};\n')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tree',type=Path,required=True)
    ap.add_argument('--work',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();assert not a.work.exists(), 'Use a fresh generated directory'
    sources=json.loads((ROOT/'configs/sources.lock.json').read_text())['sources']
    receipts=[]
    for name in ('ShengUfs','nabu'):
        s=next(x for x in sources if x['name']==name);p=ROOT/s['path']
        assert subprocess.check_output(['git','-C',str(p),'rev-parse','HEAD'],text=True).strip()==s['commit']
        assert not subprocess.check_output(['git','-C',str(p),'status','--porcelain'])
        receipts.append({'name':name,'commit':s['commit']})
    shutil.copytree(ROOT/'src/ShengUfs',a.work,ignore=shutil.ignore_patterns('.git'))
    subprocess.run(['git','init','-q',str(a.work)],check=True)
    patch=ROOT/'src/nabu/patches/nabu-nativeufs-board.patch'
    for args in (['--check'],[]):subprocess.run(['git','-C',str(a.work),'apply',*args,str(patch)],check=True)
    route_patch=ROOT/'patches/nabu-storage/smmu-firmware-route.patch'
    for args in (['--check'],[]):subprocess.run(['git','-C',str(a.work),'apply',*args,str(route_patch)],check=True)
    original=(a.work/'NativeUfs.cpp').read_text()
    start=original.index('namespace {\n#include "RootTransportLayout.h"')
    end=original.index('\n}\n\nnamespace {\nstatic uint32_t be32w',start)+2
    transport=original[start:end]
    transport=replace_once(transport,'  bool ready;','  bool ready;\n  uint64_t blocks = 0;')
    transport=replace_once(transport,'      gHost.ready = true;',
        '      uint32_t lastBlock = loadBe32 (gHost.virt + kDataOffset);\n'
        '      if (lastBlock == UINT32_MAX) { *why = "READ CAPACITY(16) required"; return false; }\n'
        '      gHost.blocks = uint64_t(lastBlock) + 1;\n      gHost.ready = true;')
    transport=replace_once(transport,'  gRootDiagnostic.stage = "controller map";',
        '  gRootDiagnostic.stage = "GCC preflight";\n'
        '  OSSharedPtr<IOMemoryMap> clockMap;\n'
        '  uintptr_t gcc = mapPhys(nabu_ufs::kBoard.gccBase+0x77000,0x1000,clockMap);\n'
        '  if (!gcc) { *why="GCC map"; return false; }\n'
        '  if (!nabuUfsClocksReady(read32(gcc,nabu_ufs::kBoard.gdscr-0x77000),\n'
        '       read32(gcc,nabu_ufs::kBoard.axiEnable-0x77000),read32(gcc,nabu_ufs::kBoard.ahbEnable-0x77000))) {\n'
        '    *why="UFS power/bus clocks unavailable"; return false;\n  }\n'
        '  gRootDiagnostic.stage = "controller map";')
    transport=replace_once(transport,
        '  smmuBypassStream (nabu_ufs::kBoard.streamId, gHost.smmuMap, report, gHost.phys, kDmaBytes);',
        '  if (!smmuBypassStream (nabu_ufs::kBoard.streamId, gHost.smmuMap, report, gHost.phys, kDmaBytes, why)) return false;')
    smmu=c_function(original,'smmuBypassStream')
    smmu=replace_once(smmu,'static void smmuBypassStream','static bool smmuBypassStream')
    smmu=replace_once(smmu,'uint64_t dma, uint64_t bytes)','uint64_t dma, uint64_t bytes, const char **why)')
    # This helper is called only after hostStopQueue proved both UFS doorbells
    # idle and the transfer list stopped. Retarget an exact firmware SID, never
    # alter its old context bank or a masked/shared stream-match entry.
    smmu=replace_once(smmu,'static_cast<unsigned> (nabu_ufs::kBoard.smmuBytes));',
        'static_cast<unsigned> (nabu_ufs::kBoard.smmuBytes), true);')
    smmu=replace_once(smmu,'    panic ("NATIVE_UFS smmu: map failed");','    *why="SMMU map"; return false;')
    smmu=replace_once(smmu,'    rootDiagnosticFailure (plan.error);\n    panic ("NATIVE_UFS smmu: %s slot=%u smr=%x s2cr=%x", plan.error, plan.slot, plan.smr, plan.s2cr);',
        '    *why=plan.error; return false;')
    smmu=replace_once(smmu,'    rootDiagnosticFailure (failure);\n    panic ("NATIVE_UFS smmu: %s idx=%u bank=%u cba2r=%x", failure, index, bank,\n           gRootDiagnostic.cba2r);',
        '    *why=failure; return false;')
    smmu=replace_once(smmu,'  report[2] = sctlr;','  report[2] = sctlr;\n  return true;')
    prefix='''// Pinned UFS core: read-only system windows plus one explicitly prepared log slot.
// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <IOKit/IOService.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOBufferMemoryDescriptor.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <libkern/libkern.h>
#include <libkern/crypto/sha2.h>
#include <vm/vm_kern.h>
#include <kern/clock.h>
#include <kern/thread.h>
#include <kern/thread_call.h>
#include <pexpert/pexpert.h>
#include <sys/errno.h>
#include "NabuBoard.h"
#include "NabuUfsResources.h"
#include "NabuStorageApi.h"
#include "NabuStoragePolicy.h"
#include "NabuStorageContract.h"
#include "RootDiagnostics.h"
#include "TransferPoll.h"
#include "SmmuTakeover.h"
extern "C" void loader_log_line(const char *);
extern "C" void loader_return(void);
extern "C" void nabu_log_append_report(void);
static UfsRootDiagnostics gRootDiagnostic;
static bool gRootDiagnosticEnabled;
'''
    generated=prefix+'\n'.join(c_function(original,n) for n in ('read32','write32','mapPhys'))+'\n'+smmu+'\n'+transport+'\n'+(ROOT/'patches/nabu-storage/NabuTransportGlue.cpp').read_text()+'\n'+(ROOT/'patches/nabu-storage/NabuLogRuntime.inc').read_text()
    dest=a.tree/'iokit/Kernel/nabu_ufs';assert not dest.exists();dest.mkdir(parents=True)
    for name in ('NabuBoard.h','RootTransportLayout.h','RootDiagnostics.h','RootQueue.h','TransferPoll.h','SmmuTakeover.h'):
        shutil.copy2(a.work/name,dest/name)
    commands=(a.work/'RootCommands.h').read_text();commands=commands[:commands.index('// ---- Persistent store and log windows')]
    commands='#include "NabuLogWriteCommands.h"\n'+commands
    command_anchor='  if (!hostClearUcd ()) return kIOReturnNotReady;\n  uint8_t *ucd = gHost.virt + kUcdOffset;\n  ucd[0] = 0x01;'
    commands=replace_once(commands,command_anchor,
        '  // NABU_LOG_WRITE_GATE_V1\n'
        '  if ((direction == 1 && !nabuLogWriteCommandAllowed(lun,cdb,cdbLength,dataBytes)) ||\n'
        '      (cdb[0] == 0x2a && direction != 1)) return kIOReturnBadArgument;\n'
        +command_anchor)
    commands=replace_once(commands,'lba > 0xffffffffULL - (blocks - 1))',
        'lba > 0xffffffffULL - (blocks - 1) || lba >= gHost.blocks || blocks > gHost.blocks-lba)')
    assert 'static IOReturn hostWrite4k' not in commands and 'hostStoreOpen' not in commands
    (dest/'RootCommands.h').write_text(commands)
    layout=(a.work/'RootLayout.h').read_text();layout=replace_once(layout,'static const char wanted[] = "userdata";','static const char wanted[] = "nabu_system";')
    (dest/'RootLayout.h').write_text(layout)
    resources=(ROOT/'src/nabu/ufs/NabuUfsResources.h').read_text().replace('static bool ','static inline bool ')
    (dest/'NabuUfsResources.h').write_text(resources)
    for name in ('NabuStorageApi.h','NabuStoragePolicy.h','NabuLogFormat.h','NabuLogWriteCommands.h','NabuLogWriter.h'):
        shutil.copy2(ROOT/'patches/nabu-storage'/name,dest/name)
    shutil.copy2(ROOT/'patches/nabu-storage/NabuLogCapture.h',a.tree/'osfmk/arm64/NabuLogCapture.h')
    cfg=json.loads((ROOT/'configs/nabu-storage-probe.json').read_text());(dest/'NabuStorageContract.h').write_text(contract_header(cfg))
    (dest/'NabuUfsTransport.cpp').write_text(generated)
    shutil.copy2(ROOT/'patches/nabu-storage/NabuRoot.c',a.tree/'bsd/dev/nabu_root.c')
    with (a.tree/'iokit/conf/files.arm64').open('a') as f:
        f.write('\niokit/Kernel/nabu_ufs/NabuUfsTransport.cpp optional nos_arm_asm\n')
    with (a.tree/'bsd/conf/files.arm64').open('a') as f:
        f.write('\nbsd/dev/nabu_root.c optional nos_arm_asm\n')
    rootfile=a.tree/'iokit/bsddev/IOKitBSDInit.cpp';text=rootfile.read_text()
    anchor='kern_return_t\nIOFindBSDRoot( char * rootName, unsigned int rootNameSize,'
    text=replace_once(text,anchor,'#include "../Kernel/nabu_ufs/NabuStorageApi.h"\n\n'+anchor)
    anchor='    dev_t * root, u_int32_t * oflags )\n{'
    text=replace_once(text,anchor,anchor+'\n\tif (nabu_root_device(rootName,rootNameSize,root,oflags)) return kIOReturnSuccess;')
    rootfile.write_text(text)
    bsd=a.tree/'bsd/kern/bsd_init.c';text=bsd.read_text()
    anchor='\tinit_rootvnode = NULLVP;  /* use rootvnode after this point */'
    text=replace_once(text,anchor,anchor+'\n\t/* Explicit read-only mount probe ends before userland or root-auth decisions. */\n\textern void nabu_root_probe_mounted(void);\n\tnabu_root_probe_mounted();')
    bsd.write_text(text)
    loader=a.tree/'osfmk/arm64/loader_return.c';text=loader.read_text()
    text=replace_once(text,'\tloader_jump(0, 0);','\textern void nabu_storage_append_report(void);\n\tnabu_storage_append_report();\n\tloader_jump(0, 0);')
    loader.write_text(text)
    report={'sources':receipts,'board_patch_sha256':hashlib.sha256(patch.read_bytes()).hexdigest(),
            'firmware_route_patch_sha256':hashlib.sha256(route_patch.read_bytes()).hexdigest(),
            'generated':[{'path':str(p.relative_to(a.tree)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(dest.iterdir())],
            'storage_contract_sha256':hashlib.sha256((ROOT/'configs/nabu-storage-probe.json').read_bytes()).hexdigest(),
            'log_capture_header_sha256':hashlib.sha256((ROOT/'patches/nabu-storage/NabuLogCapture.h').read_bytes()).hexdigest(),
            'log_runtime_sha256':hashlib.sha256((ROOT/'patches/nabu-storage/NabuLogRuntime.inc').read_bytes()).hexdigest(),
            'scope':'OS/SystemOS/Data stay read-only; explicit nabu-log-slot admits one newly prepared 64 MiB slot in the existing 1 GiB reserved area'}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
