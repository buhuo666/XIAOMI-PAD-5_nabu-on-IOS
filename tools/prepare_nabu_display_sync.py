#!/usr/bin/env python3
"""Install the opt-in native DPU path into the already patched consuming XNU tree."""
import argparse
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
UNITS = ('NabuDpuDisplay', 'NabuDpuScanoutCore', 'NabuDpuPageTable', 'NabuDpuMapper', 'NabuDpuVBlank')


def replace(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'Expected one source anchor: {old[:110]!r}; got {text.count(old)}')
    return text.replace(old, new, 1)


def install(tree):
    kernel = tree / 'iokit/Kernel'
    folder = kernel / 'nabu_display'
    folder.mkdir(parents=True, exist_ok=True)
    for unit in UNITS:
        for suffix in ('.h', '.cpp'):
            shutil.copyfile(ROOT / 'patches/nabu-display' / (unit + suffix), folder / (unit + suffix))
    for name in ('NabuDpuSwapLedger.h', 'NabuDpuProducer.h', 'NabuDpuSmmuNamespace.h'):
        shutil.copyfile(ROOT / 'patches/nabu-display' / name, folder / name)
    smmu = ROOT / 'src/nabu/gpu/upstream/ArmSmmu4K'
    for path in smmu.glob('*.h'):
        shutil.copyfile(path, folder / path.name)
    for unit in ('ArmSmmu4KContext', 'ArmSmmu4KProgram'):
        shutil.copyfile(smmu / (unit + '.c'), folder / (unit + '.c'))
        (folder / ('NabuDpu' + unit + '.c')).write_text(
            '#include "NabuDpuSmmuNamespace.h"\n#include "' + unit + '.c"\n')
    mapper = folder / 'NabuDpuMapper.cpp'
    mapper.write_text('#include "NabuDpuSmmuNamespace.h"\n' + mapper.read_text())

    path = kernel / 'MiniIOSurface.h'
    text = path.read_text()
    if 'MiniIOSurfaceDisplayUse(' not in text:
        text = replace(text, 'void            MiniIOSurfaceDrop(MiniIOSurface * surface);',
            'void            MiniIOSurfaceDrop(MiniIOSurface * surface);\n'
            '/* Independent kernel use, not charged to any user client; caller holds a Copy. */\n'
            'void            MiniIOSurfaceDisplayUse(MiniIOSurface * surface, int delta);')
        path.write_text(text)
    path = kernel / 'MiniIOSurface.cpp'
    text = path.read_text()
    if 'MiniIOSurfaceDisplayUse(' not in text:
        text = replace(text, 'void\nMiniIOSurfaceDrop(MiniIOSurface * s)', '''void
MiniIOSurfaceDisplayUse(MiniIOSurface * s, int delta)
{
    IOLockLock(gSurfaceLock);
    s->useCount[0] += delta;
    s->shared()->useCount = (uint64_t) s->useCount[1] << 32 | s->useCount[0];
    IOLockUnlock(gSurfaceLock);
}

void
MiniIOSurfaceDrop(MiniIOSurface * s)''')
        path.write_text(text)

    path = kernel / 'MiniIOMobileFramebuffer.cpp'
    text = path.read_text()
    if '#include "nabu_display/NabuDpuDisplay.h"' not in text:
        text = replace(text, '#include "MiniIOSurface.h"', '#include "MiniIOSurface.h"\n#include "nabu_display/NabuDpuDisplay.h"')
        text = replace(text, '\tIOLock *        fLock;', '\tNabuDpuDisplay::Binding *fDpu;\n\tIOLock *        fLock;')
        text = replace(text,
            'IOLog("MiniIOMobileFramebuffer: IOMFBDisplayRefresh: %u Hz (software pacing: %u; no hardware vblank), an interval of %llu (2^-32 s), %llu ticks\\n",\n'
            '\t    told, refreshHz(), interval, ticks);',
            'IOLog("MiniIOMobileFramebuffer: IOMFBDisplayRefresh: %u Hz (%s; configured rate: %u), an interval of %llu (2^-32 s), %llu ticks\\n",\n'
            '\t    told, fDpu ? "hardware vblank selected" : "software pacing; no hardware vblank", refreshHz(), interval, ticks);')
        text = replace(text, '\tfSwapLock = IOLockAlloc();', '''\tfSwapLock = IOLockAlloc();
\tif (NabuDpuDisplay::requested()) {
\t\tfDpu = NabuDpuDisplay::start();
\t\tif (!fDpu) return false;
\t\tsetProperty("NabuDirectScanout", kOSBooleanTrue);
\t}''')
        text = replace(text, '\tthread_call_t           fVSyncCall;', '''\tNabuDpuDisplay::Listener fDpuListener;
\tbool                    fDpuSubscribed;
\tstatic void hardwareVsync(void *, const NabuDpuVBlank::Sample &);
\tthread_call_t           fVSyncCall;''')
        text = replace(text, '\treturn fLock != NULL && fVSyncCall != NULL;', '''\tif (!fLock || !fVSyncCall) return false;
\tif (fOwner->fDpu) {
\t\tfDpuListener = {NULL, this, hardwareVsync};
\t\tNabuDpuDisplay::subscribe(fOwner->fDpu, &fDpuListener);
\t\tfDpuSubscribed = true;
\t}
\treturn true;''')
        unsubscribe = '''\tif (fDpuSubscribed) {
\t\tNabuDpuDisplay::unsubscribe(fOwner->fDpu, &fDpuListener);
\t\tfDpuSubscribed = false;
\t}
'''
        text = replace(text, '\tif (fVSyncCall != NULL) {\n\t\tthread_call_cancel_wait(fVSyncCall);\n\t}',
            unsubscribe + '\tif (fVSyncCall != NULL) {\n\t\tthread_call_cancel_wait(fVSyncCall);\n\t}')
        text = replace(text, 'IOMobileFramebufferUserClient::free(void)\n{',
            'IOMobileFramebufferUserClient::free(void)\n{\n' + unsubscribe)
        text = replace(text, 'IOMobileFramebufferUserClient::armVSync(void)\n{',
            'IOMobileFramebufferUserClient::armVSync(void)\n{\n\tif (fOwner->fDpu) return; // driven exclusively by hardware IRQs\n')
        text = replace(text, '\t\tfVSyncCount++;', '\t\tif (!fOwner->fDpu) fVSyncCount++;')
        text = replace(text, 'void\nIOMobileFramebufferUserClient::vsyncFired', '''void
IOMobileFramebufferUserClient::hardwareVsync(void *cookie, const NabuDpuVBlank::Sample &sample)
{
    auto self = static_cast<IOMobileFramebufferUserClient *>(cookie);
    IOLockLock(self->fLock);
    self->fVSyncTime = sample.masterTimestamp;
    self->fVSyncCount = sample.masterSequence;
    IOLockUnlock(self->fLock);
    self->vsync();
}

void
IOMobileFramebufferUserClient::vsyncFired''')
        text = replace(text, '\t\tfOwner->present((const uint8_t *) args->structureInput);',
            '\t\tif (fOwner->fDpu) return NabuDpuDisplay::present(fOwner->fDpu,\n'
            '\t\t    (const uint8_t *)args->structureInput, args->structureInputSize);\n'
            '\t\tfOwner->present((const uint8_t *) args->structureInput);')
        text = replace(text, '\tcase kFBMethodSwapWait:                         /* a swap is on the screen as soon as it is made */',
            '''\tcase kFBMethodSwapWait:
\t\tif (fOwner->fDpu) {
\t\t\tif (args->scalarInputCount != 3) return kIOReturnBadArgument;
\t\t\treturn NabuDpuDisplay::wait(fOwner->fDpu, uint32_t(in[0]), uint32_t(in[1]), in[2]);
\t\t}''')
        text = replace(text, '\tcase kFBMethodSwapSignal:\n',
            '\tcase kFBMethodSwapSignal:\n\t\treturn fOwner->fDpu ? kIOReturnUnsupported : kIOReturnSuccess;\n')
        text = replace(text, '\tcase kFBMethodSwapCancelAll:\n',
            '\tcase kFBMethodSwapCancelAll:\n\t\treturn fOwner->fDpu ? kIOReturnUnsupported : kIOReturnSuccess;\n')
        path.write_text(text)

    path = folder / 'NabuBacklight.cpp'
    text = path.read_text()
    if 'nabu_dpu_power_changed' not in text:
        text = replace(text, 'extern "C" vm_offset_t ml_io_map',
            'extern "C" void nabu_dpu_power_changed(bool on);\nextern "C" vm_offset_t ml_io_map')
        text = replace(text, '    return ok ? kIOReturnSuccess : kIOReturnIOError;',
            '    if (ok) nabu_dpu_power_changed(on);\n    return ok ? kIOReturnSuccess : kIOReturnIOError;')
        path.write_text(text)
    conf = tree / 'iokit/conf/files.arm64'
    text = conf.read_text()
    for unit in UNITS:
        entry = f'iokit/Kernel/nabu_display/{unit}.cpp optional nos_arm_asm'
        if entry not in text:
            text += '\n' + entry + '\n'
    for unit in ('ArmSmmu4KContext', 'ArmSmmu4KProgram'):
        entry = f'iokit/Kernel/nabu_display/NabuDpu{unit}.c optional nos_arm_asm'
        if entry not in text:
            text += '\n' + entry + '\n'
    conf.write_text(text)
    return {'backend': str(folder), 'boot_arg': 'nabu-dpu=1',
            'units': list(UNITS), 'pixel_copies': 0,
            'qualification': 'Candidate only; requires real device acceptance/retirement and visual validation'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tree', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    result = install(a.tree)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
