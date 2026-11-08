#!/usr/bin/env python3
"""Test Nabu SMMU native fault-IRQ registration against captured FDT and fake IRQ delivery."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command,host_path
ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include <cassert>
#include <cstdio>
#include <map>
#include <set>
#include <vector>
#include <atomic>
#include <thread>
#include "NabuWlanFault.h"
#include "NabuSharedSmmuIrq.h"
struct Peer {
    struct Handler {void (*fn)(void *,uint32_t);void *cookie;};
    std::map<unsigned,uint32_t> memory;
    std::map<unsigned,Handler> handlers;
    std::vector<unsigned> detached,masked;
    unsigned fail_irq=0,writes=0;
    Peer(){memory[0x24]=(5u<<28)|56;}
    ArmSmmu4KIo io() {
        return {this,0xd0000,
            [](void *x,size_t at,uint32_t *v){*v=((Peer *)x)->memory[at];return 0;},
            [](void *x,size_t at,uint64_t *v){auto &m=((Peer *)x)->memory;*v=m[at]|(uint64_t)m[at+4]<<32;return 0;},
            [](void *x,size_t,uint32_t){++((Peer *)x)->writes;return 0;},
            [](void *x,size_t,uint64_t){++((Peer *)x)->writes;return 0;},
            [](void *){return 0;}};
    }
    NabuWlanFault::IrqOps irqs() {
        return {this,
            [](void *x,unsigned id,bool edge,void (*fn)(void *,uint32_t),void *cookie){
                auto &p=*(Peer *)x;assert(!edge);
                if(id==p.fail_irq||p.handlers.count(id))return 1;
                p.handlers[id]={fn,cookie};return 0;},
            [](void *x,unsigned id){((Peer *)x)->masked.push_back(id);},
            [](void *x,unsigned id){auto &p=*(Peer *)x;assert(p.handlers.erase(id)==1);p.detached.push_back(id);}};
    }
    void fire(unsigned id){auto h=handlers.at(id);h.fn(h.cookie,id);}
};
struct Binding {
    Peer &peer; NabuSharedSmmuIrq &hub; NabuWlanFault &fault;
    NabuWlanFault::IrqOps ops() {
        return {this,
            [](void *x,unsigned id,bool edge,void (*fn)(void *,uint32_t),void *cookie) {
                auto &b=*(Binding *)x;
                if(id==97)return b.hub.join(fn,cookie);
                auto ops=b.peer.irqs();return ops.attach(ops.cookie,id,edge,fn,cookie);
            },
            [](void *x,unsigned id){auto &b=*(Binding *)x;auto ops=b.peer.irqs();ops.mask(ops.cookie,id);},
            [](void *x,unsigned id){auto &b=*(Binding *)x;if(id==97)b.hub.leave(&b.fault);
                else {auto ops=b.peer.irqs();ops.detach(ops.cookie,id);}}};
    }
};
static void shared_irq_cases() {
    {Peer p;NabuSharedSmmuIrq hub;hub.irq=p.irqs();hub.pause=[](){std::this_thread::yield();};
        NabuWlanFault wlan,audio;Binding w{p,hub,wlan},a{p,hub,audio};wlan.irq=w.ops();audio.irq=a.ops();
        assert(wlan.install(55,p.io())&&audio.install(54,p.io()));
        assert(hub.users==2&&p.handlers.size()==3);
        unsigned cb=(64+54)*4096;p.memory[cb+0x58]=2;p.memory[cb+0x60]=0x10000000;p.memory[0x1400+54*4]=0x1b21;
        p.fire(NabuWlanFault::context_irqs[54]);NabuWlanFault::Record c{},g{};
        assert(audio.snapshot(c,g)==1&&c.sid==0x1b21&&wlan.snapshot(c,g)==0);
        audio.remove();assert(hub.users==1&&p.handlers.count(97)&&p.handlers.count(368));
        p.memory[0x48]=2;p.fire(97);assert(wlan.snapshot(c,g)==2&&g.status==2);
        wlan.remove();assert(hub.users==0&&p.handlers.empty());
    }
    {Peer p;NabuSharedSmmuIrq hub;hub.irq=p.irqs();hub.pause=[](){std::this_thread::yield();};
        NabuWlanFault wlan,audio;Binding w{p,hub,wlan},a{p,hub,audio};wlan.irq=w.ops();audio.irq=a.ops();
        assert(wlan.install(55,p.io()));p.fail_irq=NabuWlanFault::context_irqs[54];
        assert(!audio.install(54,p.io())&&hub.users==1&&p.handlers.count(97)&&p.detached.empty());
        wlan.remove();assert(p.handlers.empty());
    }
    // Removal must wait for a callback that already acquired this subscriber.
    {Peer p;NabuSharedSmmuIrq hub;hub.irq=p.irqs();hub.pause=[](){std::this_thread::yield();};
        struct State {std::atomic<bool> entered{false},release{false},left{false};} state;
        auto handler=[](void *x,uint32_t){auto &s=*(State *)x;s.entered=true;
            while(!s.release.load())std::this_thread::yield();};
        assert(hub.join(handler,&state)==0);
        std::thread firing([&]{p.fire(97);});while(!state.entered.load())std::this_thread::yield();
        std::thread removing([&]{hub.leave(&state);state.left=true;});
        while(__atomic_load_n(&hub.subscribers[0].handler,__ATOMIC_SEQ_CST))std::this_thread::yield();
        assert(!state.left.load());state.release=true;firing.join();removing.join();
        assert(state.left.load()&&p.handlers.empty());
    }
}
int main() {
    shared_irq_cases();
    assert(NabuWlanFault::global_irq==golden_irqs[0]);
    for(unsigned b=0;b<80;++b)assert(NabuWlanFault::context_irqs[b]==golden_irqs[b+1]);
    for(unsigned n=0;n<6;++n){const auto &a=NabuWlanFault::actlr_table[n];
        assert(a.sid==golden_actlr[n*3]&&a.mask==golden_actlr[n*3+1]&&a.value==golden_actlr[n*3+2]);}
    assert(NabuWlanFault::expected_actlr(0x640)==0&&NabuWlanFault::expected_actlr(0x641)==0);
    assert(NabuWlanFault::expected_actlr(0x800)==0x103&&NabuWlanFault::expected_actlr(0x1481)==0x303);
    {Peer p;NabuWlanFault f;f.irq=p.irqs();p.fail_irq=97;
        assert(!f.install(55,p.io())&&p.detached.empty()&&p.masked.empty()&&p.writes==0);}
    {Peer p;NabuWlanFault f;f.irq=p.irqs();p.fail_irq=368;
        assert(!f.install(55,p.io())&&p.detached==std::vector<unsigned>{97}&&p.masked.empty()&&p.writes==0);}
    {Peer p;NabuWlanFault f;f.irq=p.irqs();p.memory[(64+55)*4096+4]=0x103;
        assert(!f.install(55,p.io())&&p.handlers.empty()&&p.writes==0);}
    {Peer p;NabuWlanFault f;f.irq=p.irqs();assert(f.install(55,p.io()));
        assert(p.handlers.count(97)&&p.handlers.count(368));
        p.fire(368);p.fire(97);assert(p.masked.empty()); // No asserted hardware status.
        unsigned cb=(64+55)*4096;
        p.memory[cb+0x58]=0x40000002;p.memory[cb+0x60]=0xa0008000;p.memory[cb+0x64]=0;
        p.memory[cb+0x68]=16;p.memory[cb+0x6c]=0x123;p.memory[0x1400+55*4]=0x641;
        p.fire(368);NabuWlanFault::Record c{},g{};
        assert(f.snapshot(c,g)==1&&c.status==0x40000002&&c.address==0xa0008000&&c.sid==0x641&&c.syndrome0==16);
        p.memory[cb+0x60]=0xa0009000;p.fire(368);f.snapshot(c,g);assert(c.address==0xa0008000);
        p.memory[0x48]=2;p.memory[0x50]=0x11;p.memory[0x54]=0x300;p.memory[0x58]=0x22;
        p.fire(97);assert(f.snapshot(c,g)==3&&g.status==2&&g.syndrome1==0x300&&g.syndrome2==0x22);
        assert(p.memory[0x48]==2&&p.memory[cb+0x58]==0x40000002&&p.writes==0); // Never clear foreign global evidence.
        f.remove();assert(p.handlers.empty()&&p.detached==std::vector<unsigned>({368,97}));
    }
    puts("Shared global IRQ lifetime, in-flight callback drain, audio context isolation and failed second registration rollback; Nabu FDT IRQ/ACTLR oracle, real fault record layout, first-fault retention and no SMMU/security writes passed");
}
'''
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    fixture=json.loads((ROOT/'tools/fixtures/nabu-wlan-smmu.json').read_text())
    assert fixture['global_count']==1 and all(row[0]==0 and row[2]==4 for row in fixture['gic_interrupts'])
    irqs=','.join(str(row[1]+32) for row in fixture['gic_interrupts'])
    actlr=','.join(str(x) for row in fixture['actlr'] for x in row)
    source=a.output/'fault.cpp';source.write_text('const unsigned golden_irqs[]={'+irqs+'};\nconst unsigned golden_actlr[]={'+actlr+'};\n'+HARNESS)
    binary=a.output/'fault-test'
    subprocess.run(host_command(['clang++-18','-std=c++17','-fsanitize=address,undefined','-fno-omit-frame-pointer',
        '-I'+host_path(ROOT/'patches/nabu-wireless'),host_path(source),'-o',host_path(binary)]),check=True)
    r=subprocess.run(host_command([host_path(binary)]),capture_output=True)
    (a.output/'test.log').write_bytes(r.stdout);(a.output/'test.stderr').write_bytes(r.stderr);r.check_returncode()
    report={'hardware_tested':False,'sanitizers':['address','undefined'],'result':r.stdout.decode().strip()}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
