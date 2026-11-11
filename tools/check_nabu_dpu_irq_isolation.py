#!/usr/bin/env python3
"""Run actual diagnostic admission/worker code with separate mapped-scanout and IRQ controls."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

import check_nabu_dpu_flip_gop as base
from check_darwinboot_8796 import host_path
from check_nabu_dpu_display_lifecycle import body
from check_nabu_dpu_diagnostic_result import verify


IRQ = r'''
namespace NabuDpuVBlank {
struct Binding { Sample sample{}; bool active=true, paused=false; };
Binding *start(Callback, void *, int *error) {
    *error=0; auto b=hardware->irqBinding; assert(b);
    b->active=true; b->paused=false; b->sample={};
    hardware->mdss[TopEnable/4]|=Owned; return b;
}
bool snapshot(Binding *b, Sample *out) {
    ++hardware->irqSnapshots; *out=b->sample; return b->active;
}
void stop(Binding *b) { b->active=false; ++hardware->irqStops; }
uint32_t pauseForHandover(Binding *b, Sample *out) {
    assert(b->active && !b->paused); b->paused=true;
    hardware->mdss[TopEnable/4]&=~Owned; *out=b->sample;
    hardware->events.push_back("irq-paused"); return 0;
}
uint32_t resumeAfterHandover(Binding *b, Sample *out) {
    assert(b->active && b->paused); *out=b->sample; ++hardware->irqRearms;
    hardware->events.push_back("irq-rearm");
    if (hardware->irqRearmFails) return RegisterIo;
    b->paused=false; hardware->mdss[TopEnable/4]|=Owned; return 0;
}
}
'''

SETUP = r'''
// Only the SMMU hardware setup is modeled. Actual initializeMapper owns the
// source check -> IRQ pause -> real Scan::quiesce/resume -> optional IRQ rearm.
Binding *prepare(int *error) { *error=0; return hardware->mapper; }
void discardPrepared(Binding *b) {
    if (!b) return;
    assert(!b->active && !b->programAttempted);
    assert(!(hardware->vbif[NabuDpuScanout::HaltRequest/4]&NabuDpuScanout::XinMask));
    ++hardware->auditDiscards;
}
IOReturn auditInactiveAfterQuiesce(Binding *b, const NabuDpuScanout::Io &,
                                 const NabuDpuScanout::State &s, uint32_t *sctlr) {
    assert(!b->active && !b->programAttempted && s.phase==NabuDpuScanout::Quiesced);
    hardware->now+=750; ++hardware->audits; *sctlr=0xe0;
    return hardware->auditFails ? kIOReturnIOError : kIOReturnSuccess;
}
IOReturn preflightSources(Binding *b, const NabuDpuScanout::Io &) {
    assert(!b->active && !b->programAttempted); return 0;
}
IOReturn activateAfterQuiesce(Binding *b, const NabuDpuScanout::Io &, const NabuDpuScanout::State &s) {
    assert(s.phase==NabuDpuScanout::Quiesced);
    assert(!(hardware->mdss[NabuDpuVBlank::TopEnable/4]&NabuDpuVBlank::Owned));
    b->active=true; b->programAttempted=true;
    hardware->now+=75;
    hardware->events.push_back("mapper-activated");
    if (hardware->mapperFault) hardware->app(0x82058)=2;
    return 0;
}
'''

THREADS = r'''
#define OSDynamicCast(type, value) dynamic_cast<type *>(value)
using wait_result_t=int;
using thread_t=int;
constexpr int KERN_SUCCESS=0;
constexpr IOReturn kIOReturnBusy=0xe00002d5;
constexpr const char *kIOClientPrivilegeAdministrator="root";
static int current_task() { return 0; }
static int current_thread() { return 0; }
class IOUserClient {
public: static IOReturn clientHasPrivilege(int, const char *) { return 0; }
};
static void (*queuedWorker)(void *,wait_result_t)=nullptr;
static void *queuedCookie=nullptr;
static int kernel_thread_start(void (*worker)(void *,wait_result_t), void *cookie, thread_t *thread) {
    assert(!queuedWorker); queuedWorker=worker; queuedCookie=cookie; *thread=1; return 0;
}
static void thread_terminate(int) {}
static void thread_set_thread_name(int, const char *) {}
static void thread_deallocate(int) {}
'''

TESTS = r'''
static void resetForAdmission(Fixture &f) {
    f.diagnostic.requestId->release(); f.diagnostic.requestId=nullptr;
    f.diagnostic.mapperActivated=false; f.diagnostic.irqVerified=false;
    f.diagnostic.flipGop=false; f.diagnostic.snapshotPassed=true; f.diagnostic.haltPassed=true;
    f.display.mapper=nullptr; f.display.activeMapper=nullptr; f.display.clock=nullptr;
    f.mapper.active=false; f.mapper.programAttempted=false;
    f.h.irqBinding=&f.clock;
    f.diagnostic.gop=reinterpret_cast<const volatile uint8_t *>(f.h.gopPixels.data());
    f.diagnostic.gopBytes=PT::GopBytes;
}
static IOReturn request(const char *command, bool desktop=true) {
    OSDictionary request;
    auto action=new OSString(command), id=new OSString("isolation-request");
    request.setObject("NabuDpuDiagnostic",action); action->release();
    request.setObject("RequestID",id); id->release();
    return NabuDpuDisplay::diagnosticRequest(&request,desktop);
}
static const OSDictionary &execute(Fixture &f, const char *command, const char *action) {
    assert(request(command)==kIOReturnSuccess && queuedWorker);
    auto worker=queuedWorker; queuedWorker=nullptr;
    worker(queuedCookie,0);
    assert(!f.diagnostic.busy && !f.diagnostic.requestId);
    const auto &out=dictionary(f.owner.properties,"NabuDpuDiagnosticResult");
    std::printf("CONTROL %s %s\n",action,encoded(&out).c_str());
    return out;
}
int main() {
    unsigned groups=0;
    for (unsigned mode=0;mode<3;++mode) {
        Fixture f; resetForAdmission(f);
        f.h.haltAudit=mode!=0; f.h.auditFails=mode==2;
        const auto &out=execute(f,"HaltResume","DpuHaltResume");
        assert(boolean(out,"halt_audit_requested")==bool(mode));
        assert(!boolean(out,"smmu_changed") && !boolean(out,"smmu_programmed"));
        assert(!f.mapper.active && !f.mapper.programAttempted && !f.display.mapper);
        assert(!(f.h.vbif[SC::HaltRequest/4]&SC::XinMask));
        assert(f.h.audits==unsigned(mode!=0) && f.h.auditDiscards==unsigned(mode!=0));
        if (mode) assert(number(out,"halt_audit_us")==750 && number(out,"halt_audit_sctlr")==0xe0);
        assert((number(out,"status")==0)==(mode!=2));
        assert(f.diagnostic.frozen==(mode==2)); ++groups;
    }
    {
        Fixture f; resetForAdmission(f);
        assert(request("ActivateGopPolled",false)==kIOReturnNotReady);
        assert(request("ResumeIrq")==kIOReturnNotReady);
        assert(request("FlipGop")==kIOReturnNotReady);
        f.diagnostic.haltPassed=false;
        assert(request("ActivateGopPolled")==kIOReturnNotReady);
        f.diagnostic.haltPassed=true;
        const auto &polled=execute(f,"ActivateGopPolled","DpuActivateGopPolled");
        assert(number(polled,"status")==0 && !f.diagnostic.frozen && f.clock.paused);
        assert(f.diagnostic.mapperActivated && !f.diagnostic.irqVerified);
        assert(number(polled,"handover_program_us")==75);
        assert(number(polled,"handover_halted_us")>=75);
        assert(number(polled,"handover_halted_us")>=number(polled,"handover_resume_us"));
        assert(!f.h.irqSnapshots && !f.h.irqRearms && !f.h.submissions);
        assert(number(dictionary(polled,"after"),"irq_enable")==0);
        assert(!polled.getObject("irq_count_delta"));
        const auto &pixels=dictionary(polled,"gop_pixels_before");
        assert(number(pixels,"sampled_words")==8000&&number(pixels,"nonzero_rgb_words")==8000);
        assert(number(pixels,"hash")==number(dictionary(polled,"gop_pixels_after"),"hash"));
        assert(event(f.h,"irq-paused")<event(f.h,"mapper-activated"));
        assert(request("ActivateGop")==kIOReturnUnsupported);
        assert(request("HaltResume")==kIOReturnUnsupported);
        assert(request("FlipGop")==kIOReturnNotReady);
        const auto &read=execute(f,"Snapshot","DpuSnapshot");
        assert(number(read,"status")==0 && !f.h.irqSnapshots && f.clock.paused);
        const auto &resumed=execute(f,"ResumeIrq","DpuResumeIrq");
        assert(number(resumed,"status")==0 && !f.diagnostic.frozen && !f.clock.paused);
        assert(f.diagnostic.irqVerified && f.h.irqRearms==1 && f.h.irqSnapshots==2);
        assert(!boolean(resumed,"smmu_changed") && !boolean(resumed,"scanout_address_changed"));
        assert(request("ResumeIrq")==kIOReturnNotReady);
        const auto &flip=execute(f,"FlipGop","DpuFlipGop");
        assert(number(flip,"status")==0 && boolean(flip,"test_surface_released"));
        assert(!f.diagnostic.frozen && !f.h.liveLeases); ++groups;
    }
    {
        Fixture f; resetForAdmission(f);
        const auto &out=execute(f,"ActivateGop","DpuActivateGop");
        assert(number(out,"status")==0 && f.diagnostic.irqVerified);
        assert(f.h.irqRearms==1 && f.h.irqSnapshots==2 && !f.clock.paused); ++groups;
    }
    for (unsigned failed=0;failed<4;++failed) {
        Fixture f; resetForAdmission(f);
        if (failed==0) f.h.running[1]=false;
        if (failed==1) f.h.mapperFault=true;
        if (failed==2) f.h.polledMaskLost=true;
        if (failed==3) f.h.corruptGop=true;
        const auto &out=execute(f,"ActivateGopPolled","DpuActivateGopPolled");
        assert(number(out,"status")!=0 && f.diagnostic.frozen && !f.diagnostic.mapperActivated);
        assert(!f.h.irqSnapshots && !f.h.irqRearms && f.clock.paused);
        assert(!f.h.irqStops && f.mapper.active && !f.h.submissions); ++groups;
    }
    for (unsigned failed=0;failed<2;++failed) {
        Fixture f; resetForAdmission(f);
        const auto &polled=execute(f,"ActivateGopPolled","DpuActivateGopPolled");
        assert(number(polled,"status")==0);
        if (failed==0) f.h.irqRearmFails=true;
        if (failed==1) f.h.irqMask=Hardware::NoIrq;
        const auto &out=execute(f,"ResumeIrq","DpuResumeIrq");
        assert(number(out,"status")!=0 && !f.diagnostic.irqVerified && f.diagnostic.frozen);
        assert(f.diagnostic.mapperActivated && !f.h.irqStops && !f.h.submissions);
        assert(request("FlipGop")==kIOReturnBusy); ++groups;
    }
    std::printf("PASS %u actual diagnostic admission/worker isolation groups\n",groups);
}
'''


def harness():
    source = base.harness().removesuffix(base.TESTS)
    old = base.MAPPER_SUBSTITUTES
    setup = old[:old.index('// One-time hardware handover')] + SETUP
    source = source.replace(old, setup).replace(base.IRQ_SUBSTITUTES, IRQ)
    # The actual handover succeeds with trace disabled and must not call IOLog
    # between its real XIN request/ACK and resume, including inside the mapper.
    source = source.replace('static void IOLog(const char *, ...) {}', '''static void IOLog(const char *, ...) {
        assert(!(hardware->vbif[SC::HaltRequest/4]&SC::XinMask));
    }''')
    source = source.replace('    Hardware();', '''    NabuDpuVBlank::Binding *irqBinding=nullptr;
    bool haltAudit=false, auditFails=false;
    unsigned audits=0, auditDiscards=0;
    unsigned irqSnapshots=0, irqRearms=0;
    bool mapperFault=false, irqRearmFails=false, polledMaskLost=false, corruptGop=false;
    std::vector<uint32_t> gopPixels=std::vector<uint32_t>(PT::GopBytes/4,0xff00aa55);
    Hardware();''')
    source = source.replace('static bool PE_parse_boot_argn(const char *, void *, int) { return false; }', '''static bool PE_parse_boot_argn(const char *name, void *out, int size) {
        assert(std::string(name)=="nabu-dpu-halt-audit" && size==4);
        *static_cast<uint32_t *>(out)=hardware->haltAudit; return true;
    }''')
    source = source.replace('    const char *getCStringNoCopy()', '''    bool isEqualTo(const char *value) const { return text==value; }
    size_t getLength() const { return text.size(); }
    const char *getCStringNoCopy()''')
    source = source.replace('    void removeObject(const char *key)', '''    size_t getCount() const { return values.size(); }
    void removeObject(const char *key)''')
    source = source.replace('class IOService:public OSObject {\npublic:', '''class IOService:public OSObject {
public:
    OSDictionary properties;
    void setProperty(const char *key, OSObject *value) { properties.setObject(key,value); }''')
    source = source.replace('    now+=us;', '''    now+=us;
    if (corruptGop && diagnostic->polledActivate) { gopPixels[0]^=1; corruptGop=false; }
    if (polledMaskLost && diagnostic->polledActivate)
        mdss[NabuDpuVBlank::TopEnable/4]|=NabuDpuVBlank::Owned;''')
    source = source.replace('display->clock->active && edges', 'display->clock->active && !display->clock->paused && edges')
    source = source.replace('(r==SC::Mdss ? h.mdss : h.vbif)[at/4]=value;', '''(r==SC::Mdss ? h.mdss : h.vbif)[at/4]=value;
    if (r==SC::Vbif && at==SC::HaltRequest)
        h.vbif[SC::HaltStatus/4]=value&SC::XinMask;''')
    display = (base.DIR / 'NabuDpuDisplay.cpp').read_text(encoding='utf-8')
    source += THREADS + '\nnamespace NabuDpuDisplay {\n'
    source += 'static Binding *allocateBinding() { assert(false); return nullptr; }\n'
    for signature in ('static Scan::Status diagnosticGopPixels(', 'static Scan::Status runDiagnostic(',
                      'static void diagnosticWorker(', 'IOReturn diagnosticRequest('):
        source += body(display, signature) + '\n'
    source += '}\n'
    fixture = base.TESTS[:base.TESTS.index('static void report(')]
    fixture = fixture.replace('diagnostic.requestId->release();', 'if (diagnostic.requestId) diagnostic.requestId->release();')
    return source + fixture + TESTS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='nabu-irq-isolation-') as folder:
        source, binary = Path(folder) / 'fixture.cpp', Path(folder) / 'fixture'
        source.write_text(harness(), encoding='utf-8')
        compiler = 'clang++' if sys.platform == 'darwin' else 'clang++-18'
        base.run([compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                  '-Wno-unused-parameter', '-Wno-unused-function', '-fsanitize=address,undefined',
                  '-fno-omit-frame-pointer', '-DNABU_DPU_MAPPER_HOST_TEST',
                  '-I'+host_path(base.DIR), '-I'+host_path(base.ORACLE), host_path(source),
                  host_path(base.DIR / 'NabuDpuScanoutCore.cpp'),
                  host_path(base.DIR / 'NabuDpuPageTable.cpp'), '-o', host_path(binary)])
        output = base.run([host_path(binary)])
    counts = {'success': 0, 'failure': 0, 'false_qualification_rejected': 0, 'profile_or_pixels_rejected': 0}
    for line in output.splitlines():
        if not line.startswith('CONTROL '):
            continue
        _, action, payload = line.split(' ', 2)
        result = json.loads(payload)
        good = result['status'] == 0
        data = {'request': {'Action': action, 'ID': result['request_id']}, 'dpu': {
            'request_id': result['request_id'], 'uid': 0, 'available': True, 'submit_status': 0,
            'state': 'diagnostic-complete' if good else 'diagnostic-failed', 'result': result}}
        checked = verify(data)
        assert checked['passed'] == good, checked['issues']
        counts['success' if good else 'failure'] += 1
        if good and action == 'DpuActivateGopPolled':
            assert checked['polled_takeover_verified'] and not checked['cb2_takeover_verified']
            for field in ('irq_qualification_complete', 'activate_gop_polled_requested'):
                changed = json.loads(json.dumps(data))
                changed['dpu']['result'][field] = not result[field]
                assert not verify(changed)['passed']
                counts['false_qualification_rejected'] += 1
            changed = json.loads(json.dumps(data))
            changed['dpu']['result']['after']['irq_enable'] |= 0x3c000000
            assert not verify(changed)['passed']
            counts['false_qualification_rejected'] += 1
            for section, key in (('mapper', 'actlr'), ('mapper', 'tcr'),
                                 ('gop_pixels_after', 'hash'), ('gop_pixels_before', 'sampled_words')):
                changed = json.loads(json.dumps(data))
                changed['dpu']['result'][section][key] ^= 0x400 if key == 'tcr' else 1
                assert not verify(changed)['passed']
                counts['profile_or_pixels_rejected'] += 1
    assert counts == {'success': 9, 'failure': 7, 'false_qualification_rejected': 9,
                      'profile_or_pixels_rejected': 12}, counts
    report = {'passed': True, 'host_result': output.splitlines()[-1], 'consumer': counts,
              'sanitizers': ['address', 'undefined'], 'device_accessed': False,
              'scope': 'Actual Display admission, worker, handover sequencing, counters, mapper readback and finish code; modeled IRQ binding and initial SMMU programming; no physical acceptance'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
