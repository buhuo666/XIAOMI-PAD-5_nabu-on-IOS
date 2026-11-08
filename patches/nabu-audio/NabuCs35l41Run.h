// SPDX-License-Identifier: GPL-2.0-only
// Nabu Protection HALO run/stop trial, after NabuCs35l41 preload and external
// 12.288MHz BCLK + 48kHz frame sync. GLOBAL_EN and AMP_EN remain zero throughout.
// Source: MiCode audio-kernel d41f8e1a6827294af6a61adbe18544518e750166,
// cs35l41_v2/cs35l41.c:195,706,1963,2116,2335,2408 and wm_adsp.c:3339,3372,3689.
#pragma once
#include <stdint.h>

namespace NabuCs35l41Run {
enum Error { Ok, Io, NotPreloaded, NotQuiescent, ReadbackMismatch,
    MailboxState, MailboxTimeout, HeartbeatUnchanged, ProtectionError, HardwareFault };
enum Phase { Idle, Entry, Configure, Pll, Mpu, Rates, Core, Resume, Observe, Pause,
    Stop, Restore, Complete };
struct Mailbox {
    uint32_t command=0,state=0,polls=0;
    bool sent=false,ack=false,matched=false;
};
struct Result {
    Error error=Ok;Phase phase=Idle;
    uint32_t failed_reg=0,detail=0;
    uint32_t pll_before=0,pll_running=0,pll_after=0,pll_raw3=0;
    uint32_t core_running=0,core_after=0,pwr1_after=0,pwr2_after=0;
    uint32_t heartbeat_first=0,heartbeat_last=0,heartbeat_polls=0;
    uint32_t halo_state=0,cspl_state=0,cspl_error=0;
    uint32_t fault_before[4]{},fault_running[4]{},mpu_fault[3]{};
    Mailbox resume{},pause{};
    bool configured=false,core_started=false,heartbeat_changed=false;
    bool diagnostics=false,core_off=false,output_off=false,cleanup=false;
    bool clocks_may_stop=false,complete=false;
};

// Backend selects one already preloaded chip:
// bool read(uint32_t reg,uint32_t &host_value), write(reg,host_value);
// void delay_us(uint32_t). It must keep external BCLK/frame sync present until
// clocks_may_stop=true or until the caller has reset the chip with core_off=false.
// No callback here enables/disables external clocks or resets the shared GPIO.
template<class Backend> class Trial {
    Backend &io;Result r{};
    uint32_t old_asp=0,old_pwr2=0,old_pwr3=0;
    bool saved=false,pll_saved=false,core_attempted=false,pause_attempted=false;
    bool test_unlocked=false,mpu_unlocked=false;
    void phase(Phase value) {if(r.error==Ok)r.phase=value;}
    bool fail(Error e,uint32_t reg=0,uint32_t detail=0) {
        if(r.error==Ok) {r.error=e;r.failed_reg=reg;r.detail=detail;}
        return false;
    }
    bool read(uint32_t reg,uint32_t &value) {return io.read(reg,value)||fail(Io,reg);}
    bool write(uint32_t reg,uint32_t value) {return io.write(reg,value)||fail(Io,reg);}
    bool update(uint32_t reg,uint32_t mask,uint32_t value) {
        uint32_t old;return read(reg,old)&&write(reg,(old&~mask)|(value&mask));
    }
    bool verify(uint32_t reg,uint32_t mask,uint32_t expected,uint32_t &value) {
        return read(reg,value)&&((value&mask)==expected||fail(ReadbackMismatch,reg,value));
    }
    bool faults(uint32_t *out) {
        bool ok=true;
        for(unsigned i=0;i<4;++i)ok=read(0x10010+i*4,out[i])&&ok;
        return ok;
    }
    bool diagnostics() {
        bool ok=read(0x02800780,r.halo_state);
        ok=read(0x02800258,r.cspl_state)&&ok;
        ok=read(0x0280025c,r.cspl_error)&&ok;
        ok=read(0x10098,r.pll_raw3)&&ok;
        ok=faults(r.fault_running)&&ok;
        for(unsigned i=0;i<3;++i)ok=read(0x02bc3104+i*8,r.mpu_fault[i])&&ok;
        r.diagnostics=ok;return ok;
    }
    bool mailbox(uint32_t command,Mailbox &out) {
        out.command=command;bool ok=true;uint32_t status=0;
        // W1C clears only the relevant sticky bits; unrelated interrupts stay.
        ok=write(0x10814,1u<<20)&&write(0x10014,1u<<21)&&update(0x10914,1u<<20,0);
        if(ok) {out.sent=write(0x13020,command);ok=out.sent;}
        if(ok)for(unsigned i=0;i<5;++i) {
            io.delay_us(1000);++out.polls;
            if(!read(0x10014,status)) {ok=false;break;}
            if(status&(1u<<21)) {
                out.ack=true;ok=write(0x10014,1u<<21);break;
            }
        }
        if(ok&&!out.ack)ok=fail(MailboxTimeout,0x10014,status);
        // Always remask, including a failed command or ACK read.
        bool masked=update(0x10914,1u<<20,1u<<20);
        bool state_read=read(0x13004,out.state);
        out.matched=state_read&&out.state==(command==1?1u:0u);
        if(ok&&state_read&&!out.matched)ok=fail(MailboxState,0x13004,out.state);
        return ok&&masked&&state_read&&out.ack&&out.matched;
    }
    bool configure() {
        // RX only: no ASPTX lane is driven by this trial.
        if(!update(0x4808,0xffff0777,0x20200000)||!update(0x4830,0x3f,24)||
            !update(0x4840,0x3f,24)||!update(0x4820,0x3f3f,0x0504)||
            !update(0x2c0c,0x1f,3)||!update(0x480c,3,3))return false;
        const uint32_t sources[]={8,9,0x18,0x19,0x28,0x21,0x3a,0x3b};
        for(unsigned i=0;i<8;++i)if(!write(0x4c40+i*4,sources[i]))return false;
        // PCM Source=None. Monitors feed Protection without a DAC/output route.
        if(!update(0x4c00,0x7f,0)||!update(0x4800,0x3000f,0x30000)||
            !update(0x2018,0x3701,0x3700)||!update(0x201c,0x10,0x10))return false;
        r.configured=true;return true;
    }
    bool pll() {
        // The source enters open loop, changes reference, closes loop, enables.
        if(!update(0x2c04,0x800,0x800)||!update(0x2c04,0x7e0,0x33<<5)||
            !update(0x2c04,0x10,0)||!update(0x2c04,7,0)||
            !update(0x2c04,0x800,0)||!update(0x2c04,0x10,0x10))return false;
        test_unlocked=true;
        if(!write(0x40,0x55)||!write(0x40,0xaa)||!write(0x2d10,0x24010)||
            !write(0x40,0xcc)||!write(0x40,0x33))return false;
        test_unlocked=false;
        // This verifies programming, not a fabricated PLL-lock interpretation.
        return verify(0x2c04,0xff7,0x670,r.pll_running);
    }
    bool mpu() {
        mpu_unlocked=true;
        if(!write(0x02bc3140,0x5555)||!write(0x02bc3140,0xaaaa))return false;
        const uint32_t offsets[]={0,4,8,12,20};
        for(unsigned bank=0;bank<4;++bank)
            for(uint32_t off:offsets)if(!write(0x02bc3000+bank*24+off,0xffffffff))return false;
        if(!write(0x02bc3140,0))return false;
        mpu_unlocked=false;return true;
    }
    bool rates() {
        for(unsigned dir=0;dir<2;++dir) {
            for(unsigned i=0;i<8;++i)
                if(!update(0x02b80080+dir*0x200+i*8,0x1f,1))return false;
            io.delay_us(300);
        }
        return true;
    }
    bool work() {
        phase(Entry);uint32_t value,pwr1,core;
        if(!read(0x2014,pwr1)||!read(0x2018,old_pwr2)||!read(0x02bc1000,core))return false;
        if((pwr1|old_pwr2|core)&1)return fail(NotQuiescent);
        if(!read(0x0280000c,value))return false;
        if(value!=0x400a4)return fail(NotPreloaded,0x0280000c,value);
        if(!read(0x02800010,value))return false;
        if(value!=0x2100)return fail(NotPreloaded,0x02800010,value);
        if(!read(0x4800,old_asp)||!read(0x201c,old_pwr3))return false;
        saved=true;
        if(!read(0x2c04,r.pll_before))return false;
        pll_saved=true;
        if(!faults(r.fault_before))return false;
        phase(Configure);if(!configure())return false;
        phase(Pll);if(!pll())return false;
        phase(Mpu);if(!mpu())return false;
        phase(Rates);if(!rates())return false;
        phase(Core);core_attempted=true;
        if(!update(0x02bc1000,1,1)||!verify(0x02bc1000,1,1,r.core_running))return false;
        r.core_started=true;
        phase(Resume);uint32_t initial;
        if(!read(0x13004,initial))return false;
        if(initial>2)return fail(MailboxState,0x13004,initial);
        if(!mailbox(initial==2?3:2,r.resume))return false;
        phase(Observe);
        if(!read(0x02800784,r.heartbeat_first))return false;
        r.heartbeat_last=r.heartbeat_first;
        // A bounded observation, not an asserted firmware heartbeat period.
        for(unsigned i=0;i<5;++i) {
            io.delay_us(100000);++r.heartbeat_polls;
            if(!read(0x02800784,r.heartbeat_last))return false;
            if(r.heartbeat_last!=r.heartbeat_first) {r.heartbeat_changed=true;break;}
        }
        if(!diagnostics())return false;
        if(r.cspl_state||r.cspl_error)return fail(ProtectionError,0x02800258,r.cspl_error?r.cspl_error:r.cspl_state);
        const uint32_t amp_faults=0x800281c0;
        if((r.fault_running[0]&amp_faults)||r.mpu_fault[0]||r.mpu_fault[1]||r.mpu_fault[2])
            return fail(HardwareFault,0x10010,r.fault_running[0]);
        if(!r.heartbeat_changed)return fail(HeartbeatUnchanged,0x02800784,r.heartbeat_last);
        phase(Pause);pause_attempted=true;
        return mailbox(1,r.pause);
    }
    void cleanup() {
        bool ok=true;uint32_t core=0;
        // Capture diagnostic state while the core/clocks still exist on errors.
        if(core_attempted&&!r.diagnostics)ok=diagnostics()&&ok;
        if(core_attempted&&!pause_attempted) {
            phase(Pause);pause_attempted=true;ok=mailbox(1,r.pause)&&ok;
        }
        phase(Stop);
        if(core_attempted)ok=update(0x02bc7000,1,0)&&ok;
        // Try both read/modify and readback even when another cleanup step failed.
        bool stop_write=update(0x02bc1000,1,0);
        bool stop_read=read(0x02bc1000,core);
        r.core_after=core;r.core_off=stop_read&&!(core&1);
        if(stop_read&&!r.core_off)fail(ReadbackMismatch,0x02bc1000,core);
        ok=stop_write&&r.core_off&&ok;
        if(r.core_off&&core_attempted)ok=update(0x02b80010,1,1)&&ok;
        if(test_unlocked) {
            bool a=write(0x40,0xcc),b=write(0x40,0x33);ok=a&&b&&ok;test_unlocked=false;
        }
        if(mpu_unlocked) {ok=write(0x02bc3140,0)&&ok;mpu_unlocked=false;}
        ok=update(0x10914,1u<<20,1u<<20)&&ok;
        // GLOBAL/AMP may only be cleared, including an invalid entry state.
        bool off1=update(0x2014,1,0),off2=update(0x2018,1,0);
        bool read1=read(0x2014,r.pwr1_after),read2=read(0x2018,r.pwr2_after);
        r.output_off=read1&&read2&&!(r.pwr1_after&1)&&!(r.pwr2_after&1);
        if(read1&&read2&&!r.output_off)fail(ReadbackMismatch,0x2014,r.pwr1_after);
        ok=off1&&off2&&r.output_off&&ok;
        if(r.core_off) {
            phase(Restore);
            ok=update(0x2020,4,0)&&ok; // vendor FILT_GLOBAL_OVR workaround
            if(saved) {
                // Never restore an ASPTX output or either amplifier enable bit.
                ok=write(0x4800,old_asp&~0x3000fu)&&ok;
                ok=write(0x2018,old_pwr2&~1u)&&ok;
                ok=write(0x201c,old_pwr3)&&ok;
                ok=read(0x2018,r.pwr2_after)&&ok;
            }
            if(pll_saved)ok=write(0x2c04,r.pll_before)&&ok;
            ok=read(0x2c04,r.pll_after)&&ok;
        }
        // Caller must reset the hardware before withdrawing BCLK if false.
        r.clocks_may_stop=r.core_off;r.cleanup=ok;
    }
public:
    explicit Trial(Backend &owner):io(owner) {}
    Result run() {
        r=Result{};saved=pll_saved=core_attempted=pause_attempted=false;
        test_unlocked=mpu_unlocked=false;
        bool passed=work();cleanup();
        r.complete=passed&&r.error==Ok&&r.cleanup;
        if(r.complete)r.phase=Complete;
        return r;
    }
};
} // namespace NabuCs35l41Run
