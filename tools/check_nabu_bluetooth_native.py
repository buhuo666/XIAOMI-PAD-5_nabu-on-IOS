#!/usr/bin/env python3
"""Test production H4/IBS framing, queued TX and native socket callbacks on host."""
import argparse
import json
import re
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    match = re.search(r'^static[^\n]*\b'+re.escape(name)+r'\(', source, re.M)
    start = match.start()
    # Each selected function ends with an unindented brace; nested blocks do not.
    end = source.index('\n}\n', match.end()) + 3
    return '\n'+source[start:end]


PRELUDE = r'''
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdarg>
#include <ctime>
#include <string>
#include <vector>
#include "NabuBluetoothTransport.h"
#include "NabuBluetoothControl.h"
using vm_offset_t=uintptr_t; using lck_grp_t=int; using lck_mtx_t=int;
using thread_call_t=void*; using thread_call_param_t=void*; using kern_ctl_ref=void*;
using errno_t=int; using u_long=unsigned long; using caddr_t=char*;
using IOLock=int;
struct IOService {};
struct sockaddr_ctl { uint32_t sc_unit; };
struct user_termios { uint64_t c_iflag,c_oflag,c_cflag,c_lflag; uint8_t c_cc[20]; alignas(8) uint64_t c_ispeed,c_ospeed; };
static_assert(sizeof(user_termios)==72);
#define VMIN 16
#define VTIME 17
#define TIOCGETA_64 0x40487413UL
#define TIOCSETA_64 0x80487414UL
#define TIOCEXCL 0x2000740dUL
#define TIOCNXCL 0x2000740eUL
#define TIOCOUTQ 0x40047473UL
#define IOCPARM_LEN(x) (((x)>>16)&0x1fff)
#define MSG_OOB 1
#define MSG_DONTWAIT 0x80
#define PZERO 0
#define PCATCH 1
struct TestMbuf { std::vector<uint8_t> bytes; TestMbuf *next=nullptr; };
using mbuf_t=TestMbuf*;
static unsigned freed,scheduled,sleeps;
static int lock_depth;
static uint64_t now;
static std::vector<std::vector<uint8_t>> wire;
static bool acknowledge_wake=true;
static int enqueue_result;
static bool flush_during_enqueue;
static std::vector<uint8_t> socket_bytes;
static u_long last_ioctl;
static bool deny_try_lock, sleep_tx_fails, peer_sleep_on_send, peer_sleep_on_wait, drain_on_wait;
static std::vector<std::string> logs;
static std::vector<uint8_t> uart_input;
static unsigned uart_position;
static constexpr int kMillisecondScale=1;
static void lck_mtx_lock(lck_mtx_t*) { ++lock_depth; }
static void lck_mtx_unlock(lck_mtx_t*) { assert(lock_depth>0); --lock_depth; }
static bool IOLockTryLock(IOLock*) { if(deny_try_lock)return false;++lock_depth;return true; }
static void wakeup(void*) {}
static uint64_t mach_absolute_time() { return now; }
static void clock_interval_to_deadline(unsigned n,int,uint64_t *deadline) { *deadline=now+n; }
static void absolutetime_to_nanoseconds(uint64_t time,uint64_t *ns) { *ns=time*1000000; }
static void IOSleep(unsigned ms) { now+=ms; }
static void thread_call_enter(thread_call_t) { ++scheduled; }
static void wr(vm_offset_t,uint32_t) {}
static bool wait_bit(vm_offset_t,uint32_t,bool,unsigned) { return true; }
static void nabu_wireless_log(const char *format,...) { char line[256];va_list args;va_start(args,format);vsnprintf(line,sizeof(line),format,args);va_end(args);logs.emplace_back(line); }
static void IOLog(const char *,...) {} // Console-only late trace is outside the inventory buffer.
static mbuf_t mbuf_next(mbuf_t m) { return m->next; }
static size_t mbuf_len(mbuf_t m) { return m->bytes.size(); }
static void *mbuf_data(mbuf_t m) { return m->bytes.data(); }
static void mbuf_freem(mbuf_t m) { ++freed; while(m){auto next=m->next;delete m;m=next;} }
'''

MOCKS = r'''
static void stream_tx_work(thread_call_param_t,thread_call_param_t);
static int msleep(void *event,lck_mtx_t*,int,const char*,void *timeout) {
    ++sleeps;
    if(event==&stream_socket_enqueuing){stream_socket_enqueuing=false;return 0;}
    assert(event==&stream_idle_requested);
    if(drain_on_wait&&stream_tx->count){drain_on_wait=false;lck_mtx_unlock(stream_rx_lock);stream_tx_work(nullptr,nullptr);lck_mtx_lock(stream_rx_lock);++now;return 0;}
    if(peer_sleep_on_wait){peer_sleep_on_wait=false;stream_ibs_rx_awake=false;++stream_ibs_sleeps;now+=10;return 0;}
    auto t=(timespec*)timeout;assert(t);now+=t->tv_sec*1000+(t->tv_nsec+999999)/1000000;return EWOULDBLOCK;
}
static bool transmit(vm_offset_t,const uint8_t *bytes,unsigned size,bool) {
    wire.emplace_back(bytes,bytes+size);
    if(size==1&&bytes[0]==0xfd&&acknowledge_wake)stream_ibs_tx=StreamTxAwake;
    if(size==1&&bytes[0]==0xfe){if(sleep_tx_fails)return false;if(peer_sleep_on_send){stream_ibs_rx_awake=false;++stream_ibs_sleeps;}}
    return true;
}
static uint32_t rd(vm_offset_t address) {
    unsigned offset=(unsigned)(address-stream_uart),remaining=uart_input.size()-uart_position;
    if(offset==0x640)return 0;
    if(offset==0x804)return (remaining+3)/4+(remaining%4?(0x80000000u|((remaining%4)<<28)):0);
    assert(offset==0x780);uint32_t value=0;for(unsigned i=0;i<4&&uart_position<uart_input.size();++i)value|=(uint32_t)uart_input[uart_position++]<<(8*i);return value;
}
static int ctl_enqueuedata(kern_ctl_ref,uint32_t unit,void *data,size_t size,uint32_t flags) {
    assert(lock_depth==0&&unit==stream_socket_unit&&flags==0);
    if(enqueue_result)return enqueue_result;
    auto p=(const uint8_t*)data;socket_bytes.insert(socket_bytes.end(),p,p+size);
    if(flush_during_enqueue){stream_rx->clear();assert(stream_rx->push_word(0x04030201,4));}
    return 0;
}
static int stream_ioctl(int,u_long command,caddr_t data,int,void*) {
    last_ioctl=command;
    if(command==TIOCGETA_64)memcpy(data,&stream_termios,sizeof(stream_termios));
    else if(command==TIOCSETA_64)memcpy(&stream_termios,data,sizeof(stream_termios));
    else if(command==TIOCOUTQ)*(int*)data=stream_tx->count;
    return 0;
}
static void reset() {
    static NabuBluetoothRx rx{};static StreamTxQueue tx{};
    stream_rx=&rx;stream_tx=&tx;rx.clear();tx.clear();stream_rx_frame={};
    stream_opened=false;stream_socket_unit=0;stream_socket_closing=stream_socket_enqueuing=false;
    stream_rx_error=stream_tx_error=0;stream_ibs_tx=StreamTxAsleep;stream_ibs_pending_acks=stream_ibs_attempts=0;
    stream_received=stream_written=stream_overruns=stream_ibs_deadline=0;
    stream_idle_requested=stream_idle_confirmed=stream_suspending=stream_rx_wake_waiting=false;
    stream_host_sleep_count=stream_ibs_sleeps=stream_ibs_wakes=stream_ibs_acks=0;
    stream_command_logs=stream_event_logs=stream_event_payload_seen=0;
    deny_try_lock=sleep_tx_fails=peer_sleep_on_send=peer_sleep_on_wait=drain_on_wait=false;
    logs.clear();uart_input.clear();uart_position=0;
    wire.clear();socket_bytes.clear();now=0;acknowledge_wake=true;enqueue_result=0;flush_during_enqueue=false;
    assert(lock_depth==0);
}
'''

TESTS = r'''
int main() {
    reset();
    StreamH4Rx parser{};std::vector<uint8_t> payload,controls;
    std::vector<uint8_t> input{0xfd,4,0xff,3,0xfd,0xfc,0xfe,0xfe,0xfd,
        2,1,0x20,3,0,0xfd,0xfc,0xfe,3,1,0,3,0xfd,0xfc,0xfe,
        5,1,0,3,0x80,0xfd,0xfc,0xfe,0xfc};
    for(auto byte:input){int result=parser.take(byte);assert(result>0);if(result==1)payload.push_back(byte);else controls.push_back(byte);}
    assert(parser.boundary());assert((controls==std::vector<uint8_t>{0xfd,0xfe,0xfd,0xfc}));
    assert((payload==std::vector<uint8_t>{4,0xff,3,0xfd,0xfc,0xfe,2,1,0x20,3,0,0xfd,0xfc,0xfe,
        3,1,0,3,0xfd,0xfc,0xfe,5,1,0,3,0x80,0xfd,0xfc,0xfe}));
    assert(parser.take(0x7f)==-1);

    uint8_t command[]{1,1,0x10,0};
    stream_tx->head=StreamTxQueue::capacity-2;stream_tx->append(command,2);assert(stream_tx->packet_size()==0);
    stream_tx->append(command+2,2);assert(stream_tx->packet_size()==4);
    stream_ibs_pending_acks=1;stream_tx_work(nullptr,nullptr);
    assert((wire==std::vector<std::vector<uint8_t>>{{0xfc},{0xfd},{1,1,0x10,0}}));
    assert(!stream_tx->count&&stream_written==4&&!stream_ibs_pending_acks);

    reset();stream_tx->append(command,4);acknowledge_wake=false;
    stream_tx_work(nullptr,nullptr);
    for(unsigned i=0;i<10;++i){now+=100;stream_tx_work(nullptr,nullptr);}
    assert(stream_tx_error==ETIMEDOUT&&stream_tx->count==4&&stream_written==0&&wire.size()==10);
    for(auto &p:wire)assert((p==std::vector<uint8_t>{0xfd}));

    reset();stream_ibs_tx=StreamTxAwake;
    uint8_t with_tokens[]{1,1,0xfc,3,0xfd,0xfc,0xfe};stream_tx->append(with_tokens,sizeof(with_tokens));
    stream_tx_work(nullptr,nullptr);assert(wire.size()==1&&wire[0]==std::vector<uint8_t>(with_tokens,with_tokens+sizeof(with_tokens)));

    reset();sockaddr_ctl first{1},second{2};void *a=nullptr,*b=nullptr;
    assert(stream_ctl_connect(nullptr,&first,&a)==0&&a==stream_rx);
    assert(stream_acquire(0)==EBUSY);assert(stream_ctl_connect(nullptr,&second,&b)==EBUSY&&b==nullptr);
    assert(stream_ctl_disconnect(nullptr,2,b)==0&&stream_socket_unit==1);
    auto m=new TestMbuf{{1,1},new TestMbuf{{0x10,0}}};auto before=freed;
    assert(stream_ctl_send(nullptr,1,a,m,0)==0&&freed==before+1&&stream_tx->packet_size()==4);
    m=new TestMbuf{{0xfd}};assert(stream_ctl_send(nullptr,1,a,m,MSG_OOB)==EOPNOTSUPP&&freed==before+2&&stream_tx->count==4);
    unsigned queued=stream_tx->count;stream_tx->count=StreamTxQueue::capacity;
    m=new TestMbuf{{1,1,0x10,0}};
    assert(stream_ctl_send(nullptr,1,a,m,0)==ENOBUFS&&freed==before+3&&stream_tx->count==StreamTxQueue::capacity);
    stream_tx->count=queued;

    user_termios settings{};settings.c_cc[VMIN]=1;settings.c_ospeed=settings.c_ispeed=115200;
    assert(stream_ctl_setopt(nullptr,1,a,(int)0x80487414,&settings,72)==0&&last_ioctl==0x80487414UL);
    assert(stream_ctl_setopt(nullptr,1,a,(int)0x80487414,&settings,71)==EINVAL);
    size_t size=7;uint8_t small[7];assert(stream_ctl_getopt(nullptr,1,a,0x40487413,small,&size)==EMSGSIZE&&size==7);
    size=0;assert(stream_ctl_getopt(nullptr,1,a,0x40487413,nullptr,&size)==0&&size==72);
    user_termios result{};size=72;assert(stream_ctl_getopt(nullptr,1,a,0x40487413,&result,&size)==0&&result.c_ospeed==115200);

    assert(stream_rx->push_word(0x04030201,4));enqueue_result=ENOBUFS;
    stream_socket_deliver(nullptr,nullptr);assert(stream_rx->count==4&&!stream_socket_enqueuing&&socket_bytes.empty());
    enqueue_result=0;stream_ibs_pending_acks=1;stream_socket_deliver(nullptr,nullptr);assert(socket_bytes.empty());
    stream_ibs_pending_acks=0;stream_socket_deliver(nullptr,nullptr);assert(!stream_rx->count&&(socket_bytes==std::vector<uint8_t>{1,2,3,4}));
    assert(stream_rx->push_word(0x08070605,4));flush_during_enqueue=true;
    stream_socket_deliver(nullptr,nullptr);assert(stream_rx->count==4&&!stream_socket_enqueuing);
    flush_during_enqueue=false;stream_socket_enqueuing=true;before=sleeps;
    assert(stream_ctl_disconnect(nullptr,1,a)==0&&sleeps==before+1&&!stream_opened&&!stream_socket_unit);
    assert(stream_acquire(0)==0);assert(stream_ctl_connect(nullptr,&first,&b)==EBUSY);stream_release(0);
    assert(stream_ctl_connect(nullptr,&first,&b)==0&&!stream_rx->count&&!stream_tx->count);
    // An idle operation is not successful without an actual FE transmission and
    // a controller-side sleep observation; no fixed-success lifecycle callback.
    uint32_t version=NABU_BT_CONTROL_VERSION;
    reset();assert(stream_ctl_connect(nullptr,&first,&a)==0);stream_ibs_tx=StreamTxAwake;stream_ibs_rx_awake=true;
    peer_sleep_on_wait=true;
    assert(stream_ctl_setopt(nullptr,1,a,NABU_BT_OPT_IBS_IDLE,&version,sizeof(version))==0);
    assert(stream_idle_confirmed&&stream_suspending&&stream_ibs_tx==StreamTxAsleep&&stream_host_sleep_count==1);
    assert((wire==std::vector<std::vector<uint8_t>>{{0xfe}}));
    assert(stream_wait_space(1,true)==EBUSY);
    NabuBluetoothIbsState state{};size=sizeof(state);
    assert(stream_ctl_getopt(nullptr,1,a,NABU_BT_OPT_IBS_STATE,&state,&size)==0);
    assert(size==32&&state.version==1&&(state.flags&NABU_BT_IDLE_CONFIRMED)&&state.host_sleep_count==1&&state.controller_sleep_count==1);
    stream_release(1);assert(stream_suspending);stream_rx_wake_waiting=true;
    assert(stream_ctl_connect(nullptr,&first,&a)==0&&!stream_suspending&&stream_ibs_pending_acks==1);
    stream_tx->append(command,4);wire.clear();stream_tx_work(nullptr,nullptr);
    assert((wire==std::vector<std::vector<uint8_t>>{{0xfc},{0xfd},{1,1,0x10,0}}));

    reset();assert(stream_ctl_connect(nullptr,&first,&a)==0);stream_ibs_tx=StreamTxAwake;stream_ibs_rx_awake=true;
    assert(stream_ctl_setopt(nullptr,1,a,NABU_BT_OPT_IBS_IDLE,&version,3)==EINVAL&&wire.empty());
    deny_try_lock=true;assert(stream_enter_idle()==EBUSY&&wire.empty()&&!stream_idle_requested);deny_try_lock=false;
    assert(stream_enter_idle()==ETIMEDOUT&&!stream_idle_confirmed&&!stream_suspending);
    assert(now==NABU_BT_IDLE_DEADLINE_MS&&stream_host_sleep_count==1);

    reset();assert(stream_ctl_connect(nullptr,&first,&a)==0);stream_ibs_tx=StreamTxAwake;sleep_tx_fails=true;
    assert(stream_enter_idle()==EIO&&!stream_idle_confirmed&&stream_host_sleep_count==0);
    reset();assert(stream_ctl_connect(nullptr,&first,&a)==0);stream_ibs_tx=StreamTxAwake;stream_ibs_rx_awake=true;
    stream_tx->append(command,4);drain_on_wait=true;peer_sleep_on_send=true;
    assert(stream_enter_idle()==0&&stream_written==4&&wire.size()==2&&wire[0]==std::vector<uint8_t>(command,command+4)&&wire[1][0]==0xfe);

    // Real production FIFO/parser code retains payloads and logs only opcode/status.
    reset();uart_input={4,0x0e,4,1,0x27,0xfc,1,4,0x0f,4,12,1,0x0c,0x20};
    stream_drain_rx(false);assert(stream_event_logs==2&&stream_rx->count==uart_input.size());
    assert(logs[0].find("event=0xe opcode=0xfc27 status=1")!=std::string::npos);
    assert(logs[1].find("event=0xf opcode=0x200c status=12")!=std::string::npos);
    for(unsigned i=0;i<120;++i){uart_input={4,0x0e,4,1,0xe2,0xfc,1};uart_position=0;stream_drain_rx(false);}
    assert(stream_event_logs==96&&logs.size()==96);
    puts("Bluetooth native: H4 token boundaries, complete-frame TX, IBS ACK/wake/retry, exclusive owners, mbuf release, signed ioctl/short getopt and socket backpressure passed");
    puts("Bluetooth lifecycle: drain before FE, actual peer sleep, fixed deadline/error propagation, suspended-write refusal, reopen/wake and bounded opcode/status trace passed");
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    source = (ROOT/'patches/nabu-wireless/NabuBluetooth.cpp').read_text()
    framing = source.split('// BEGIN TESTABLE H4 FRAMING\n')[1].split('// END TESTABLE H4 FRAMING')[0]
    globals_source = source[source.index('static vm_offset_t stream_uart;'):source.index('static void stream_clear_rx()')]
    functions = ''.join(function(source, name) for name in ['stream_clear_rx','stream_drain_rx','stream_tx_work','stream_socket_deliver',
        'stream_acquire','stream_release','stream_wait_space','stream_ctl_owner','stream_ctl_connect',
        'stream_ctl_disconnect','stream_ctl_send','stream_idle_wait','stream_idle_drained','stream_enter_idle','stream_ctl_setopt','stream_ctl_getopt'])
    cpp=args.output/'bluetooth-native.cpp';cpp.write_text(PRELUDE+framing+globals_source+MOCKS+functions+TESTS)
    binary=args.output/'bluetooth-native-test'
    subprocess.run(host_command(['clang++-18','-std=c++17','-fsanitize=address,undefined','-fno-omit-frame-pointer',
        '-I'+host_path(ROOT/'patches/nabu-wireless'),host_path(cpp),'-o',host_path(binary)]),check=True)
    result=subprocess.run(host_command([host_path(binary)]),capture_output=True)
    (args.output/'test.log').write_bytes(result.stdout);(args.output/'test.stderr').write_bytes(result.stderr);result.check_returncode()
    report={'production_functions_tested':True,'kernel_apis_mocked':True,'hardware_tested':False,
            'sanitizers':['address','undefined'],'result':result.stdout.decode().strip()}
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
