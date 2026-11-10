#!/usr/bin/env python3
"""Run actual DPU listeners, native-client lifecycle and swap-ledger code on host threads.

Extracts real function bodies, not rewritten lifecycle logic. IOKit locks,
ports, thread calls and time are host substitutes; no kernel or device runs.
The optional ARM64 check compiles the whole prepared MiniIOMobileFramebuffer.
"""
import argparse
import ast
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
DISPLAY = ROOT / 'patches/nabu-display/NabuDpuDisplay.cpp'
PREPARE = ROOT / 'tools/prepare_nabu_display_sync.py'


def body(text, signature, tail=''):
    start = text.index(signature)
    opening = text.index('{', start)
    depth = 0
    tokens = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]', re.S)
    for match in tokens.finditer(text, opening):
        token = match[0]
        if token == '{':
            depth += 1
        elif token == '}':
            depth -= 1
            if not depth:
                return text[start:match.end()] + tail
    raise ValueError(f'Unclosed body: {signature}')


def prepared_framebuffer(tree, temp):
    # Execute exactly the installer's framebuffer section on a temporary copy.
    # Mapper/other implementation files need not exist for this independent
    # lifecycle check. Already installed input remains idempotent.
    kernel = temp / 'iokit/Kernel'
    kernel.mkdir(parents=True)
    path = kernel / 'MiniIOMobileFramebuffer.cpp'
    shutil.copyfile(tree / 'iokit/Kernel/MiniIOMobileFramebuffer.cpp', path)
    spec = importlib.util.spec_from_file_location('display_installer_test', PREPARE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parsed = ast.parse(PREPARE.read_text())
    install = next(x for x in parsed.body if isinstance(x, ast.FunctionDef) and x.name == 'install')
    selection, active = [], False
    for node in install.body:
        literals = [x.value for x in ast.walk(node) if isinstance(x, ast.Constant) and isinstance(x.value, str)]
        if isinstance(node, ast.Assign) and 'MiniIOMobileFramebuffer.cpp' in literals:
            active = True
        if active and isinstance(node, ast.Assign) and 'NabuBacklight.cpp' in literals:
            break
        if active:
            selection.append(node)
    assert selection
    code = compile(ast.fix_missing_locations(ast.Module(body=selection, type_ignores=[])), str(PREPARE), 'exec')
    environment = {'kernel': kernel, 'replace': module.replace}
    exec(code, environment)
    folder = kernel / 'nabu_display'
    folder.mkdir()
    for name in ('NabuDpuDisplay.h', 'NabuDpuVBlank.h', 'NabuBacklight.h'):
        shutil.copyfile(ROOT / 'patches/nabu-display' / name, folder / name)
    return path


PRELUDE = r'''
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <future>
#include <mutex>
#include <thread>
#include <vector>
#include "NabuDpuVBlank.h"
#include "NabuDpuSwapLedger.h"
using IOReturn=uint32_t;
using UInt32=uint32_t;
using io_user_reference_t=uint64_t;
using mach_vm_address_t=uint64_t;
using task_t=uintptr_t;
constexpr IOReturn kIOReturnSuccess=0, kIOReturnBusy=0xe00002d5, kIOReturnNotFound=0xe00002f0;
constexpr IOReturn kIOReturnUnsupported=0xe00002c7, kIOReturnBadArgument=0xe00002c2;
constexpr IOReturn kIOReturnIOError=0xe00002ca, kIOReturnTimeout=0xe00002d6;
constexpr int THREAD_UNINT=0, THREAD_TIMED_OUT=1, kMillisecondScale=1000000;
constexpr uint64_t NSEC_PER_SEC=1000000000;
constexpr unsigned kFBNotifyVSync=5, kFBNotifyTypes=8, kIOUserNotifyOptionCanDrop=1;
constexpr unsigned WaitMs=500;
#define OSDeclareDefaultStructors(x)
#define APPLE_KEXT_OVERRIDE
#define OSDynamicCast(t,x) static_cast<t *>(x)
struct IOLock {
    std::mutex mutex;
    std::condition_variable condition;
    std::atomic<unsigned> sleeps{0};
};
IOLock *IOLockAlloc(){return new IOLock;}
void IOLockFree(IOLock *l){delete l;}
void IOLockLock(IOLock *l){l->mutex.lock();}
void IOLockUnlock(IOLock *l){l->mutex.unlock();}
uint64_t mach_absolute_time(){return std::chrono::steady_clock::now().time_since_epoch().count();}
void clock_interval_to_deadline(uint32_t count,int scale,uint64_t *out){*out=mach_absolute_time()+uint64_t(count)*scale;}
int IOLockSleepDeadline(IOLock *l,const void *,uint64_t deadline,int){
    std::unique_lock<std::mutex> held(l->mutex,std::adopt_lock);
    ++l->sleeps;
    const auto status=l->condition.wait_until(held,std::chrono::steady_clock::time_point(std::chrono::nanoseconds(deadline)));
    held.release();return status==std::cv_status::timeout?THREAD_TIMED_OUT:0;
}
void IOLockWakeup(IOLock *l,const void *,bool){l->condition.notify_all();}
void IOLockSleep(IOLock *l,const void *,int){
    std::unique_lock<std::mutex> held(l->mutex,std::adopt_lock);
    ++l->sleeps;l->condition.wait(held);held.release();
}
void IOLog(const char *,...){}
void hakios_tl(const char *,...){}
bool gTouchLat=false;
uint64_t micros(uint64_t x){return x/1000;}
unsigned refreshHz(){return 120;}
void nanoseconds_to_absolutetime(uint64_t in,uint64_t *out){*out=in;}
using thread_call_param_t=void *;
struct HostCall{};
using thread_call_t=HostCall *;
std::atomic<unsigned> timerEnters{0};
thread_call_t thread_call_allocate(void (*)(void *,void *),void *){return new HostCall;}
void thread_call_cancel_wait(thread_call_t){}
void thread_call_free(thread_call_t c){delete c;}
void thread_call_enter_delayed(thread_call_t,uint64_t){++timerEnters;}
struct Port{unsigned released=0;};
// macOS libc already defines its user-space integer mach_port_t. The kernel
// ABI under test uses an ipc_port pointer; keep that substitute local to the
// extracted fixture without redeclaring the host platform's type.
using DpuTestMachPort=Port *;
#define mach_port_t DpuTestMachPort
struct OSAsyncReference64{Port *port;uint64_t function,context;};
void releaseNotificationPort(Port *p){assert(p && !p->released);++p->released;}
void setAsyncReference64(OSAsyncReference64 &r,Port *p,uint64_t f,uint64_t c,task_t){r={p,f,c};}
struct Gate {
    std::mutex mutex;std::condition_variable cv;bool entered=false,open=false;
    void block(){std::unique_lock<std::mutex> l(mutex);entered=true;cv.notify_all();cv.wait(l,[&]{return open;});}
    void wait(){std::unique_lock<std::mutex> l(mutex);assert(cv.wait_for(l,std::chrono::seconds(2),[&]{return entered;}));}
    void release(){std::lock_guard<std::mutex> l(mutex);open=true;cv.notify_all();}
};
Gate *sendGate=nullptr;
struct Message{Port *port;std::array<uint64_t,6> args;};
std::vector<Message> messages;
IOReturn sendAsyncResult64WithOptions(const OSAsyncReference64 &r,IOReturn error,const uint64_t *args,unsigned count,unsigned option){
    assert(!error && count==6 && option==kIOUserNotifyOptionCanDrop);
    if(sendGate)sendGate->block();
    assert(r.port && !r.port->released);
    Message m{};m.port=r.port;std::copy(args,args+6,m.args.begin());messages.push_back(m);return 0;
}
class IOService{};
class OSDictionary{};
class OSObject{};
class OSString{};
struct IOExternalMethodArguments{};
struct IOExternalMethodDispatch{};
class IOUserClient:public IOService {
public:
    unsigned freed=0,terminated=0;
    bool initWithTask(task_t,void *,UInt32,OSDictionary *){return true;}
    bool start(IOService *){return true;}
    void free(){++freed;}
    bool isInactive(){return terminated!=0;}
    void terminate(){++terminated;}
};
namespace NabuDpuDisplay {
namespace Swap=NabuDpuSwap;
namespace Mapper {
struct Binding {IOReturn fault=0;};
IOReturn readFault(Binding *b){return b->fault;}
}
struct Listener {Listener *next;void *cookie;void (*notify)(void *,const NabuDpuVBlank::Sample &);};
// Only the state touched by the extracted functions is substituted. The ledger
// and every tested function body below remain production code.
struct Binding {
    IOLock *stateLock=IOLockAlloc(),*listenerLock=IOLockAlloc();
    NabuDpuVBlank::Binding *clock=nullptr;
    Mapper::Binding *activeMapper=nullptr;
    NabuDpuVBlank::Sample sample{};
    Listener *listeners=nullptr;
    Swap::Ledger ledger{};
    uint64_t eventGeneration=0;
    IOReturn failure=0;
    bool powerOn=true;
    ~Binding(){assert(!listeners);IOLockFree(stateLock);IOLockFree(listenerLock);}
};
}
const void *producer=nullptr;
struct IOMobileFramebuffer:IOService {NabuDpuDisplay::Binding *fDpu;};
'''

TESTS = r'''
Gate *listenerGate=nullptr;
void gatedNotify(void *p,const NabuDpuVBlank::Sample &s){listenerGate->block();IOMobileFramebufferUserClient::hardwareVsync(p,s);}
void connect(IOMobileFramebufferUserClient &c,IOMobileFramebuffer &o,Port &p){
    assert(c.start(&o));assert(c.fDpuSubscribed);
    c.fTask=42;c.fCallbacks[kFBNotifyVSync]=0x1234;c.fRefcons[kFBNotifyVSync]=77;
    assert(c.registerNotificationPort(&p,kFBNotifyVSync,0)==0);
    c.fVSyncRunning=true;
}
void tick(NabuDpuDisplay::Binding &b,uint64_t sequence,uint64_t time=0x123456789abcdef0ull){
    NabuDpuVBlank::Sample s{};s.masterSequence=sequence;s.masterTimestamp=time;
    NabuDpuDisplay::vblank(&b,s);
}
int main(){
    using namespace std::chrono_literals;
    using namespace NabuDpuSwap;
    unsigned groups=0;
    {
        Ledger l{};for(uint32_t id:{700u,3u,400u,UINT32_MAX})assert(l.insert(id));
        assert(l.find(3)->order==2 && !l.find(4) && !l.insert(0) && !l.insert(700));
        assert(l.next==4);++groups;
    }
    {
        Ledger l{};std::array<uint32_t,64> ids{};
        for(unsigned i=0;i<64;++i){ids[i]=900000-i*31;assert(l.insert(ids[i]));}
        l.find(ids[4])->phase=Displayed;
        assert(!l.insert(17) && l.next==64);
        for(uint32_t id:ids)assert(l.find(id));
        l.find(ids[8])->phase=Failed;l.find(ids[6])->phase=Retired;
        assert(l.insert(17)->order==65 && !l.find(ids[6]));
        assert(l.find(ids[8]) && l.find(ids[4])->phase==Displayed);
        assert(l.insert(18)->order==66 && !l.find(ids[8]));
        assert(!l.insert(19));++groups;
    }
    {
        Ledger l{};auto old=l.insert(400);const auto through=l.next;
        auto future=l.insert(2);assert(l.pendingThrough(through));
        old->phase=Displayed;assert(!l.pendingThrough(through) && l.pendingThrough(l.next));
        future->phase=Failed;future->error=kIOReturnIOError;
        assert(!l.failedThrough(through) && l.failedThrough(l.next)==kIOReturnIOError);++groups;
    }
    {
        NabuDpuDisplay::Binding b;
        assert(NabuDpuDisplay::wait(&b,99,0x80000000,0)==kIOReturnNotFound);
        auto r=b.ledger.insert(7);
        assert(NabuDpuDisplay::wait(&b,7,0x80000000,0)==kIOReturnBusy);
        assert(NabuDpuDisplay::wait(&b,7,0x80000001,0)==kIOReturnBusy);
        r->phase=Displayed;
        assert(NabuDpuDisplay::wait(&b,7,0x80000001,0)==0);
        assert(NabuDpuDisplay::wait(&b,7,0x80000000,0)==kIOReturnBusy);
        r->phase=Retired;assert(NabuDpuDisplay::wait(&b,7,0x80000000,0)==0);
        assert(NabuDpuDisplay::wait(&b,0,0x80000002,0)==0);
        assert(NabuDpuDisplay::wait(&b,7,2,0)==kIOReturnUnsupported);++groups;
    }
    {
        NabuDpuDisplay::Binding b;b.ledger.insert(70);
        auto waiter=std::async(std::launch::async,[&]{return NabuDpuDisplay::wait(&b,0,2,1000);});
        const auto limit=std::chrono::steady_clock::now()+1s;
        while(!b.stateLock->sleeps){assert(std::chrono::steady_clock::now()<limit);std::this_thread::yield();}
        IOLockLock(b.stateLock);
        assert(b.ledger.insert(2));b.ledger.find(70)->phase=Displayed;
        IOLockWakeup(b.stateLock,&b,false);IOLockUnlock(b.stateLock);
        assert(waiter.wait_for(1s)==std::future_status::ready && waiter.get()==0);
        assert(b.ledger.find(2)->phase==Queued);++groups;
    }
    {
        messages.clear();NabuDpuDisplay::Binding b;IOMobileFramebuffer owner;owner.fDpu=&b;
        IOMobileFramebufferUserClient c{};Port p;connect(c,owner,p);
        tick(b,1);assert(messages.size()==1 && c.fVSyncCount==1);
        assert(messages[0].args[0]==0x9abcdef0 && messages[0].args[1]==0x12345678);
        assert(messages[0].args[2]==0x9abcdef0 && messages[0].args[3]==0x12345678);
        assert(messages[0].args[4]==1 && messages[0].args[5]==0);
        tick(b,1);assert(messages.size()==1); // slave/duplicate sample cannot double native vblank
        tick(b,3);assert(messages.size()==2 && c.fVSyncCount==3); // no invented missing tick
        b.powerOn=false;tick(b,4);assert(messages.size()==2);
        b.powerOn=true;tick(b,5);assert(messages.size()==3);
        c.clientClose();c.free();assert(p.released==1 && c.freed==1 && !b.listeners);
        tick(b,6);assert(messages.size()==3);++groups;
    }
    {
        messages.clear();NabuDpuDisplay::Binding b;IOMobileFramebuffer owner;owner.fDpu=&b;
        IOMobileFramebufferUserClient c{};Port p;connect(c,owner,p);
        Gate gate;listenerGate=&gate;c.fDpuListener.notify=gatedNotify;
        auto irq=std::async(std::launch::async,[&]{tick(b,1);});gate.wait();
        auto closing=std::async(std::launch::async,[&]{return c.clientClose();});
        assert(closing.wait_for(20ms)==std::future_status::timeout);
        IOLockLock(c.fLock);assert(c.fClosed);IOLockUnlock(c.fLock);
        gate.release();irq.get();assert(closing.get()==0);
        assert(messages.empty() && !c.fDpuSubscribed && !b.listeners);
        c.free();tick(b,2);assert(messages.empty() && c.freed==1);++groups;
    }
    {
        messages.clear();NabuDpuDisplay::Binding b;IOMobileFramebuffer owner;owner.fDpu=&b;
        IOMobileFramebufferUserClient c{};Port p;connect(c,owner,p);
        Gate gate;listenerGate=&gate;c.fDpuListener.notify=gatedNotify;
        auto irq=std::async(std::launch::async,[&]{tick(b,1);});gate.wait();
        auto freeing=std::async(std::launch::async,[&]{c.free();});
        assert(freeing.wait_for(20ms)==std::future_status::timeout);
        gate.release();irq.get();freeing.get();
        assert(messages.size()==1 && p.released==1 && c.fLock==nullptr);
        tick(b,2);assert(messages.size()==1 && !b.listeners);++groups;
    }
    {
        messages.clear();NabuDpuDisplay::Binding b;IOMobileFramebuffer owner;owner.fDpu=&b;
        IOMobileFramebufferUserClient c{};Port old,newPort;connect(c,owner,old);
        Gate gate;sendGate=&gate;
        auto irq=std::async(std::launch::async,[&]{tick(b,1);});gate.wait();
        auto replacing=std::async(std::launch::async,[&]{return c.registerNotificationPort(&newPort,kFBNotifyVSync,0);});
        assert(replacing.wait_for(20ms)==std::future_status::timeout && !old.released);
        gate.release();irq.get();assert(replacing.get()==0);sendGate=nullptr;
        assert(old.released==1 && messages[0].port==&old);
        tick(b,2);assert(messages.size()==2 && messages[1].port==&newPort);
        c.clientClose();c.free();assert(newPort.released==1);++groups;
    }
    {
        messages.clear();NabuDpuDisplay::Binding b;IOMobileFramebuffer owner;owner.fDpu=&b;
        IOMobileFramebufferUserClient c{};Port p;connect(c,owner,p);
        NabuDpuVBlank::Sample s{};s.masterSequence=1;s.masterTimestamp=10;s.fault=NabuDpuVBlank::ForeignTop;
        NabuDpuDisplay::vblank(&b,s);assert(messages.empty() && b.failure==kIOReturnIOError);
        NabuDpuVBlank::Sample out{};assert(!NabuDpuDisplay::snapshot(&b,&out));
        assert(NabuDpuDisplay::wait(&b,0,0x80000003,0)==kIOReturnIOError);
        c.clientClose();c.free();++groups;
    }
    assert(timerEnters==0);
    {
        using namespace NabuDpuDisplay;
        diagnosticDrawBegin();diagnosticDrawEnd(); // Disabled mode changes nothing.
        DiagnosticSession d{};d.lock=IOLockAlloc();diagnostics=&d;
        diagnosticDrawBegin();
        auto freeze=std::async(std::launch::async,[&]{freezeDiagnosticGop(&d);});
        assert(freeze.wait_for(20ms)==std::future_status::timeout); // Existing pixel writer must finish.
        diagnosticDrawEnd();freeze.get();
        assert(d.frozen && !d.drawing);
        assert(d.lock->mutex.try_lock());d.lock->mutex.unlock(); // No lock held during MMIO/checkpoints.
        auto nextWriter=std::async(std::launch::async,[&]{diagnosticDrawBegin();diagnosticDrawEnd();});
        assert(nextWriter.wait_for(20ms)==std::future_status::timeout); // No new writes while halted.
        IOLockWakeup(d.lock,&d.frozen,false);
        assert(nextWriter.wait_for(20ms)==std::future_status::timeout); // Spurious wake cannot unfreeze.
        thawDiagnosticGop(&d);nextWriter.get();
        assert(!d.frozen && !d.drawing);diagnostics=nullptr;IOLockFree(d.lock);++groups;
    }
    std::printf("PASS %u actual-code lifecycle, concurrent notification and ledger/wait groups; no software ticks\n",groups);
}
'''


def harness(framebuffer):
    display = DISPLAY.read_text()
    client = body(framebuffer, 'class IOMobileFramebufferUserClient : public IOUserClient', ';')
    # Access visibility alone changes, allowing the fixture to initialize and
    # observe fields. No method/body or lifecycle expression is rewritten.
    client = client.replace('class IOMobileFramebufferUserClient', 'struct IOMobileFramebufferUserClient', 1)
    result = PRELUDE + '\nnamespace NabuDpuDisplay {\n'
    result += body(display, 'struct DiagnosticSession', ';') + '\nstatic DiagnosticSession *diagnostics;\n'
    for signature in ('void diagnosticDrawBegin(', 'void diagnosticDrawEnd(',
                      'static void freezeDiagnosticGop(', 'static void thawDiagnosticGop('):
        result += body(display, signature) + '\n'
    for signature in ('static void vblank(', 'void subscribe(', 'void unsubscribe(', 'bool snapshot(', 'IOReturn wait('):
        result += body(display, signature) + '\n'
    result += '}\n' + client + '\n'
    for signature in (
        'bool\nIOMobileFramebufferUserClient::initWithTask(',
        'bool\nIOMobileFramebufferUserClient::start(',
        'IOReturn\nIOMobileFramebufferUserClient::clientClose(',
        'void\nIOMobileFramebufferUserClient::free(',
        'IOReturn\nIOMobileFramebufferUserClient::registerNotificationPort(',
        'void\nIOMobileFramebufferUserClient::hardwareVsync(',
        'void\nIOMobileFramebufferUserClient::vsyncFired(',
        'void\nIOMobileFramebufferUserClient::armVSync(',
        'void\nIOMobileFramebufferUserClient::vsync('):
        result += body(framebuffer, signature) + '\n'
    # Unused virtual externalMethod is kept in the class for its real layout;
    # the fixture does not invoke native selector dispatch through this stub.
    result += '''IOReturn IOMobileFramebufferUserClient::externalMethod(uint32_t,IOExternalMethodArguments *,
        IOExternalMethodDispatch *,OSObject *,void *){return kIOReturnUnsupported;}\n'''
    return result + TESTS


def run(command):
    result = subprocess.run(host_command(command), capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=45)
    if result.returncode:
        raise RuntimeError(f'{command[0]} failed:\n{result.stdout}\n{result.stderr}')
    return result.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tree', type=Path, default=ROOT / 'build/nabu-display-sync/tree')
    ap.add_argument('--kernel-command', type=Path,
                    help='Complete compatible MiniFB build command, including private headers/prefix; GPU kext flags are insufficient')
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    result = {'scope': 'Host substitutes around actual listener/client/ledger functions; no device or GPU/scanout execution'}
    with tempfile.TemporaryDirectory(prefix='nabu-display-lifecycle-') as tmp:
        temp = Path(tmp)
        fb = prepared_framebuffer(args.tree, temp)
        source, binary = temp / 'fixture.cpp', temp / 'fixture'
        source.write_text(harness(fb.read_text()))
        compiler = 'clang++' if sys.platform == 'darwin' else 'clang++-18'
        run([compiler, '-std=c++17', '-O1', '-g', '-pthread', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
             '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
             '-I' + host_path(ROOT / 'patches/nabu-display'), host_path(source), '-o', host_path(binary)])
        result['host_result'] = run([host_path(binary)]).strip()
        result['arm64_framebuffer_compiled'] = False
        if args.kernel_command:
            original = json.loads(args.kernel_command.read_text())
            command, index = [], 0
            while index < len(original):
                arg = original[index]
                if arg in ('-c', '-o'):
                    index += 2
                else:
                    command.append(arg)
                    index += 1
            target = temp / 'MiniIOMobileFramebuffer.o'
            command += ['-I' + host_path(args.tree / 'iokit/Kernel'),
                        '-c', host_path(fb), '-o', host_path(target)]
            run(command)
            result['arm64_framebuffer_compiled'] = True
            result['framebuffer_object_bytes'] = target.stat().st_size
    result['passed'] = True
    output = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding='utf-8')
    print(output, end='')


if __name__ == '__main__':
    main()
