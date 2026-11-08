#!/usr/bin/env python3
"""Exercise production CS35L41 protected native playback and core lifecycle."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <map>
#include <vector>
#include "NabuCs35l41Run.h"
using namespace NabuCs35l41Run;
struct Op {char kind;uint32_t reg,value;};
struct Bus {
    std::map<uint32_t,uint32_t> reg;
    std::vector<Op> ops;
    unsigned fail_at=0,ack_at=2,ack_wait=0,pending=0,heartbeat_at=1,observations=0;
    bool persistent=false,drop_resume=false,drop_pause=false,bad_resume=false,bad_pause=false;
    bool heartbeat_stuck=false,core_stuck=false,core_drop=false;
    bool dsploaded=true,clocks=true,enabled=false;
    bool allow_output=false,pcm_running=false,pdn_pending=false;
    unsigned pdn_wait=0;
    uint32_t start_state=0,cspl_state=0,cspl_error=0,fault=0,mpu_fault=0;
    unsigned test_key=0,mpu_key=0,rx_delays=0,tx_delays=0;
    unsigned resume_commands=0,pause_commands=0,mpu_writes=0;
    Bus() {
        reg[0x2014]=0;reg[0x2018]=0x3320;reg[0x201c]=0x00100000;
        reg[0x4800]=0;reg[0x4808]=0x1000017;reg[0x4830]=0x80;reg[0x4840]=0x80;
        reg[0x4820]=0x80000000;reg[0x2c0c]=0x123;reg[0x480c]=0x40;
        reg[0x2c04]=0x10010;reg[0x0280000c]=0x400a4;reg[0x02800010]=0x2100;
        reg[0x02800780]=2;reg[0x02800784]=7;reg[0x02bc1000]=0;
        reg[0x10914]=0xa5b12345;reg[0x10814]=0x100044;reg[0x10014]=0x200008;
        reg[0x10010]=0x40000000;reg[0x1001c]=2;reg[0x10098]=0x100;
        reg[0x2020]=0x204;reg[0x02bc7000]=0x101;
        for(unsigned i=0;i<8;++i) {reg[0x02b80080+i*8]=0x3400;reg[0x02b80280+i*8]=0x5600;}
    }
    bool operation(char kind,uint32_t address,uint32_t value=0) {
        ops.push_back({kind,address,value});
        return !fail_at||(persistent?ops.size()<fail_at:ops.size()!=fail_at);
    }
    bool read(uint32_t address,uint32_t &value) {
        if(!operation('r',address))return false;
        value=reg[address];
        if(address==0x0280000c&&!dsploaded)value=0;
        if(address==0x02800258)value=cspl_state;
        if(address==0x0280025c)value=cspl_error;
        if(address==0x10010&&enabled)value|=fault;
        if(address==0x02bc3104&&enabled)value=mpu_fault;
        return true;
    }
    void prerequisites() {
        assert(clocks&&!(reg[0x2014]&1)&&!(reg[0x2018]&1));
        assert((reg[0x2c04]&0xff7)==0x670);
        assert((reg[0x4808]&0xffff0777)==0x20200000);
        assert((reg[0x4830]&0x3f)==24&&(reg[0x4840]&0x3f)==24);
        assert((reg[0x4820]&0x3f3f)==0x504&&(reg[0x4800]&0x3000f)==0x30000);
        assert((reg[0x2018]&0x3700)==0x3700&&(reg[0x201c]&0x10));
        assert((reg[0x4c00]&0x7f)==0);
        const uint32_t sources[]={8,9,0x18,0x19,0x28,0x21,0x3a,0x3b};
        for(unsigned i=0;i<8;++i)assert(reg[0x4c40+i*4]==sources[i]);
        assert(test_key==0&&reg[0x2d10]==0x24010&&mpu_key==0&&mpu_writes==20);
        assert(rx_delays==1&&tx_delays==1);
        for(unsigned i=0;i<8;++i) {assert(reg[0x02b80080+i*8]==0x3401);assert(reg[0x02b80280+i*8]==0x5601);}
    }
    bool write(uint32_t address,uint32_t value) {
        assert(clocks); // caller cannot withdraw BCLK before returning core_off
        if((address==0x2014||address==0x2018)&&(value&1))assert(allow_output&&pcm_running);
        if(address==0x4800)assert(!(value&15));
        if(address==0x2084)assert(allow_output&&test_key==2);
        if(!operation('w',address,value))return false;
        if(address==0x40) {
            if(value==0x55)test_key=1;
            else if(value==0xaa){assert(test_key==1);test_key=2;}
            else if(value==0xcc)test_key=3;
            else if(value==0x33){assert(test_key==3);test_key=0;}
            else assert(false);
        }
        if(address==0x2d10)assert(test_key==2);
        if(address==0x02bc3140) {
            if(value==0x5555)mpu_key=1;
            else if(value==0xaaaa){assert(mpu_key==1);mpu_key=2;}
            else {assert(value==0);mpu_key=0;}
        }
        if(address>=0x02bc3000&&address<=0x02bc305c) {
            assert(mpu_key==2&&value==0xffffffff);
            uint32_t field=(address-0x02bc3000)%24;
            assert(field==0||field==4||field==8||field==12||field==20);++mpu_writes;
        }
        if(address==0x02bc1000) {
            if(value&1) {
                prerequisites();enabled=true;reg[0x13004]=start_state;
                if(core_drop)return true;
            } else if(core_stuck&&enabled)return true;
        }
        if(address==0x02b80010)assert(!(reg[0x02bc1000]&1));
        if(address==0x2c04&&enabled)assert(!(reg[0x02bc1000]&1));
        if(address==0x10814||address==0x10014||address==0x10010) {reg[address]&=~value;return true;}
        if(address==0x2014&&(value&1)) {
            assert(reg[0x2018]&1);assert(reg[0x2084]==0x002f1aa0);
            assert((reg[0x6000]&0x3fff)==4&&(reg[0x6c04]&0x3e0)==(18<<5));
            assert((reg[0x4c00]&0x7f)==0x32);
            assert((reg[0x201c]&0x100010)==0x100010);
            assert((reg[0x3804]&1)&&!(reg[0x3800]&0xff)&&(reg[0x2018]&0x30)==0x20);
            assert(reg[0x6404]==0x02005308&&reg[0x6808]==0x3f75);
        }
        if(address==0x2014&&!(value&1)&&(reg[address]&1)) {
            assert(!(reg[0x2018]&1));assert((reg[0x6000]&0x3ff8)==0x2678);
            assert(pause_commands);pdn_pending=true;pdn_wait=0;
        }
        if(address==0x13020) {
            assert(!(reg[0x10914]&(1<<20)));
            assert(!(reg[0x10814]&(1<<20))&&!(reg[0x10014]&(1<<21)));
            assert(value==1||value==2||value==3);
            pending=value;ack_wait=0;
            if(value==1)++pause_commands;else ++resume_commands;
        }
        reg[address]=value;return true;
    }
    void delay_us(uint32_t us) {
        assert(clocks);ops.push_back({'d',0,us});
        if(us==300) {
            if(!rx_delays)++rx_delays;else ++tx_delays;
        } else if(us==1000) {
            if(pdn_pending&&++pdn_wait>=2){reg[0x10010]|=0x00800000;pdn_pending=false;}
            if(pending&&(reg[0x02bc1000]&1)) {
                ++ack_wait;
                if(ack_wait>=ack_at&&!((pending==1&&drop_pause)||(pending!=1&&drop_resume))) {
                    reg[0x10014]|=1<<21;
                    reg[0x13004]=pending==1?(bad_pause?0:1):(bad_resume?1:0);pending=0;
                }
            }
        } else if(us==4000) {
            assert(allow_output&&(reg[0x6000]&0x3ff8)==0x2678);
        } else {
            assert(us==100000);++observations;
            if((reg[0x02bc1000]&1)&&!heartbeat_stuck&&observations>=heartbeat_at)++reg[0x02800784];
        }
    }
};
void off(const Bus &b,const Result &r) {
    assert(r.core_off&&r.clocks_may_stop&&r.output_off);
    assert(!(b.reg.at(0x02bc1000)&1)&&!(b.reg.at(0x2014)&1)&&!(b.reg.at(0x2018)&1));
}
size_t find(const Bus &b,char kind,uint32_t reg,uint32_t value,size_t start=0) {
    for(size_t i=start;i<b.ops.size();++i)if(b.ops[i].kind==kind&&b.ops[i].reg==reg&&b.ops[i].value==value)return i;
    return b.ops.size();
}
void order(const Bus &b) {
    size_t i=0;
    for(uint32_t value:{0x10810u,0x10e70u,0x10e60u,0x10e60u,0x10660u,0x10670u}) {
        i=find(b,'w',0x2c04,value,i);assert(i<b.ops.size());++i;
    }
    size_t start=find(b,'w',0x02bc1000,1),resume=find(b,'w',0x13020,2);
    size_t pause=find(b,'w',0x13020,1),watchdog=find(b,'w',0x02bc7000,0x100);
    size_t stop=find(b,'w',0x02bc1000,0),reset=find(b,'w',0x02b80010,1);
    size_t restore=find(b,'w',0x2c04,0x10010,start);
    assert(i<start&&start<resume&&resume<pause&&pause<watchdog&&watchdog<stop&&stop<reset&&reset<restore);
    for(size_t command:{resume,pause}) {
        size_t clearDsp=find(b,'w',0x10814,1<<20,command-5);
        size_t clearAp=find(b,'w',0x10014,1<<21,command-4);
        assert(clearDsp<clearAp&&clearAp<command);
        size_t ackClear=find(b,'w',0x10014,1<<21,command+1);
        assert(ackClear>command&&ackClear<b.ops.size());
        assert(b.ops[command+1].kind=='d'&&b.ops[command+1].value==1000);
    }
}
int main() {
    Bus baseline;Trial<Bus> trial(baseline);Result good=trial.run();
    assert(good.complete&&good.error==Ok&&good.phase==Complete&&good.cleanup);
    assert(good.configured&&good.core_started&&good.heartbeat_changed&&good.diagnostics);
    assert(good.resume.command==2&&good.resume.sent&&good.resume.ack&&good.resume.matched&&good.resume.polls==2);
    assert(good.pause.command==1&&good.pause.sent&&good.pause.ack&&good.pause.matched&&good.pause.polls==2);
    assert(good.heartbeat_first==7&&good.heartbeat_last==12&&good.heartbeat_polls==5);
    assert(good.pll_before==0x10010&&good.pll_after==good.pll_before&&good.pll_raw3==0x100);
    assert(good.halo_state==2&&!good.cspl_state&&!good.cspl_error);
    assert(baseline.reg[0x10814]==0x44&&baseline.reg[0x10014]==8);
    assert(baseline.reg[0x10914]==0xa5b12345&&baseline.reg[0x2018]==0x3320);
    assert(baseline.reg[0x201c]==0x100000&&baseline.reg[0x4800]==0&&baseline.reg[0x2020]==0x200);
    off(baseline,good);order(baseline);
    {Bus b;b.start_state=2;Trial<Bus> p(b);auto r=p.run();assert(r.complete&&r.resume.command==3);off(b,r);}
    {Bus b;b.start_state=1;Trial<Bus> p(b);auto r=p.run();assert(r.complete&&r.resume.command==2);off(b,r);}
    {Bus b;b.start_state=3;Trial<Bus> p(b);auto r=p.run();assert(r.error==MailboxState&&r.pause.ack);off(b,r);}
    {Bus b;b.heartbeat_at=5;Trial<Bus> p(b);auto r=p.run();assert(r.complete&&r.heartbeat_polls==5);off(b,r);}
    {Bus b;b.heartbeat_stuck=true;Trial<Bus> p(b);auto r=p.run();assert(r.complete&&r.error==Ok&&!r.heartbeat_changed&&r.heartbeat_polls==5&&r.pause.ack);off(b,r);}
    {Bus b;b.drop_resume=true;Trial<Bus> p(b);auto r=p.run();assert(r.error==MailboxTimeout&&!r.resume.ack&&r.resume.polls==5&&r.pause.ack);off(b,r);}
    {Bus b;b.drop_pause=true;Trial<Bus> p(b);auto r=p.run();assert(r.error==MailboxTimeout&&!r.pause.ack&&r.pause.polls==5);off(b,r);}
    {Bus b;b.bad_resume=true;Trial<Bus> p(b);auto r=p.run();assert(r.error==MailboxState&&r.resume.ack&&!r.resume.matched&&r.pause.ack);off(b,r);}
    {Bus b;b.bad_pause=true;Trial<Bus> p(b);auto r=p.run();assert(r.error==MailboxState&&r.pause.ack&&!r.pause.matched);off(b,r);}
    {Bus b;b.cspl_error=0x26;Trial<Bus> p(b);auto r=p.run();assert(r.error==ProtectionError&&r.cspl_error==0x26);off(b,r);}
    {Bus b;b.cspl_state=1;Trial<Bus> p(b);auto r=p.run();assert(r.error==ProtectionError&&r.cspl_state==1);off(b,r);}
    {Bus b;b.fault=0x100;Trial<Bus> p(b);auto r=p.run();assert(r.error==HardwareFault&&r.fault_running[0]==0x40000100);off(b,r);}
    {Bus b;b.mpu_fault=0x20000;Trial<Bus> p(b);auto r=p.run();assert(r.error==HardwareFault&&r.mpu_fault[0]==0x20000);off(b,r);}
    {Bus b;b.reg[0x02800780]=1;Trial<Bus> p(b);auto r=p.run();assert(r.error==HaloState&&!r.started);off(b,r);}
    {Bus b;b.dsploaded=false;Trial<Bus> p(b);auto r=p.run();assert(r.error==NotPreloaded&&!r.core_started);off(b,r);}
    {Bus b;b.reg[0x2018]|=1;Trial<Bus> p(b);auto r=p.run();assert(r.error==NotQuiescent&&!r.core_started);off(b,r);}
    {Bus b;b.core_drop=true;Trial<Bus> p(b);auto r=p.run();assert(r.error==ReadbackMismatch&&!r.core_started);off(b,r);}
    {Bus b;b.core_stuck=true;Trial<Bus> p(b);auto r=p.run();assert(r.error==ReadbackMismatch&&!r.core_off&&!r.clocks_may_stop&&!r.cleanup);
        assert(b.reg[0x2c04]==r.pll_running&&r.pll_after==0);}
    unsigned injected=0,withheld=0;
    for(unsigned i=0;i<baseline.ops.size();++i) {
        if(baseline.ops[i].kind=='d')continue;
        Bus b;b.fail_at=i+1;Trial<Bus> p(b);auto r=p.run();
        assert(!r.complete&&r.error==Io&&r.failed_reg==baseline.ops[i].reg);
        assert(!(b.reg[0x2014]&1)&&!(b.reg[0x2018]&1));
        if(!r.core_off) {
            assert(!r.clocks_may_stop);++withheld;
            // Local PLL is retained when a stopped core cannot be confirmed.
            if(b.enabled)assert(b.reg[0x2c04]==r.pll_running);
        } else assert(r.clocks_may_stop);
        ++injected;
    }
    {Bus b;b.fail_at=25;b.persistent=true;Trial<Bus> p(b);auto r=p.run();
        assert(r.error==Io&&!r.cleanup&&!r.clocks_may_stop);}
    // Four independent instances retain each preloaded speaker calibration and
    // channel balance. The actual physical PCM stream is owned by the caller.
    const uint32_t calibration[]={9301,9342,9630,9717};
    for(unsigned speaker=0;speaker<4;++speaker) {
        Bus b;b.allow_output=true;b.heartbeat_stuck=true;
        b.reg[0x02800268]=calibration[speaker];b.reg[0x02800270]=1;
        b.reg[0x02800274]=calibration[speaker]+1;b.reg[0x02800374]=speaker%2?0x400000:0;
        b.reg[0x6000]=0x8000;Trial<Bus> p(b);
        assert(p.start()&&p.result().started&&!p.result().output_enabled);
        assert(!p.result().heartbeat_changed&&!b.pause_commands&&(b.reg[0x02bc1000]&1));
        b.pcm_running=true;assert(p.enable_output());
        assert(p.result().output_enabled&&p.result().volume_code==0&&p.result().volume_reg==0x8004);
        assert(p.observe());assert(p.stop_output());
        assert(!(b.reg[0x2014]&1)&&!(b.reg[0x2018]&1)&&(b.reg[0x02bc1000]&1));
        auto r=p.finish();assert(r.complete&&r.muted&&r.output_stopped&&r.pdn_done&&r.pdn_polls==3);
        assert(p.finish().complete&&b.pause_commands==1);off(b,r);
        assert(b.reg[0x02800268]==calibration[speaker]&&b.reg[0x02800270]==1);
        assert(b.reg[0x02800274]==calibration[speaker]+1&&b.reg[0x02800374]==(speaker%2?0x400000u:0));
        assert((b.reg[0x6000]&0xbfff)==0xa67c&&(b.reg[0x4c00]&0x7f)==0);
        size_t ampOn=find(b,'w',0x2018,0x3721),pup=find(b,'w',0x2084,0x2f1aa0);
        size_t globalOn=find(b,'w',0x2014,1),mute=find(b,'w',0x6000,0xa67c);
        size_t ampOff=find(b,'w',0x2018,0x3720,mute),pause=find(b,'w',0x13020,1);
        size_t globalOff=find(b,'w',0x2014,0,globalOn+1),pdnClear=find(b,'w',0x10010,0x800000);
        size_t pdn=find(b,'w',0x2084,0x2f1aa3),coreOff=find(b,'w',0x02bc1000,0);
        size_t pllRestore=find(b,'w',0x2c04,0x10010,globalOff);
        assert(ampOn<pup&&pup<globalOn&&globalOn<mute&&mute<ampOff&&ampOff<pause&&
            pause<globalOff&&globalOff<pdnClear&&pdnClear<pdn&&pdn<coreOff&&coreOff<pllRestore);
    }
    printf("production CS35L41: four protected original 0dB playback lifecycles, calibration/channel preservation, AMP/PUP/GLOBAL startup and mute/AMP/Pause/GLOBAL/PDN/core stop order, HALO2/mailbox validation, nonfatal static heartbeat, no ASPTX output; %u existing I/O exits and %u withheld clock removals passed\n",injected,withheld);
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = args.output / 'cs35l41-run.cpp'
    source.write_text(HARNESS)
    binary = args.output / 'cs35l41-run-test'
    subprocess.run(host_command([
        'clang++-18', '-std=c++17', '-O1', '-g', '-fsanitize=address,undefined',
        '-fno-omit-frame-pointer', '-Wall', '-Wextra', '-Werror',
        '-I' + host_path(ROOT / 'patches/nabu-audio'), host_path(source),
        '-o', host_path(binary)]), check=True)
    result = subprocess.run(host_command([host_path(binary)]), capture_output=True)
    (args.output / 'stdout.txt').write_bytes(result.stdout)
    (args.output / 'stderr.txt').write_bytes(result.stderr)
    result.check_returncode()
    report = {'hardware_tested': False,
              'production_header': 'patches/nabu-audio/NabuCs35l41Run.h',
              'sanitizers': ['address', 'undefined'],
              'result': result.stdout.decode().strip()}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
