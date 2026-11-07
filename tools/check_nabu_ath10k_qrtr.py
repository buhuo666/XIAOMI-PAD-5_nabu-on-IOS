#!/usr/bin/env python3
"""Replay the production ath10k QRTR message router; no device or firmware execution."""
import argparse
import json
from pathlib import Path
import subprocess

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <cassert>
#include <cstdio>
#include <memory>
#include <tuple>
#include <vector>
#include "NabuAth10kQrtr.h"
using Router=NabuAth10kQrtr;
static bool locked;
template<class F> static auto under_lock(F f) {
    assert(!locked);locked=true;auto value=f();locked=false;return value;
}
struct Client {
    Router *router;
    Router::PortId id=0;
    bool alive=true,reply=false;
    std::vector<std::tuple<bool,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t>> servers;
    std::vector<std::vector<uint8_t>> packets;
    static void server(void *cookie,bool up,uint32_t service,uint32_t version,uint32_t instance,
                       uint32_t node,uint32_t port) {
        auto &c=*(Client *)cookie;assert(c.alive&&!locked);
        c.servers.emplace_back(up,service,version,instance,node,port);
    }
    static void receive(void *cookie,uint32_t node,uint32_t port,const void *data,size_t size) {
        auto &c=*(Client *)cookie;assert(c.alive&&!locked);
        auto *bytes=(const uint8_t *)data;c.packets.emplace_back(bytes,bytes+size);
        if(c.reply)assert(under_lock([&]{return c.router->send(c.id,node,port,data,size);})==Router::Ok);
    }
    void open() { assert(under_lock([&]{return router->open(receive,server,this,id);})==Router::Ok); }
    void lookup(uint32_t instance=0) {
        assert(under_lock([&]{return router->lookup(id,0x45,1,instance);})==Router::Ok);
    }
    void close() {
        assert(under_lock([&]{return router->begin_close(id);})==Router::Ok);
        assert(under_lock([&]{return router->finish_close(id);})==Router::Ok);alive=false;
    }
};
static const Router::Endpoint endpoint{0x45,1,7,0,0x1234}; // remote node zero is valid.
static void start(Router &r) {assert(under_lock([&]{return r.start_instance();})==Router::Ok);}
static void announce(Router &r) {assert(under_lock([&]{return r.announce(endpoint);})==Router::Ok);}
static unsigned drain(Router &r) {
    unsigned count=0;Router::Callback callback;
    for(;;) {
        auto result=under_lock([&]{return r.begin_callback(callback);});
        if(result==Router::Empty)break;
        assert(result==Router::Ok);callback.invoke();
        assert(under_lock([&]{return r.finish_callback(callback.ticket);})==Router::Ok);++count;
    }
    return count;
}
static const uint8_t cap[]={0,0x34,0x12,0x24,0,0,0};
static const uint8_t cap_reply[]={2,0x34,0x12,0x24,0,7,0,2,4,0,0,0,0,0};
int main() {
    // Actual announcements are required; lookup replays the cached observation.
    {auto r=std::make_unique<Router>();Router::PortId unused=99;
        assert(r->open(nullptr,nullptr,nullptr,unused)==Router::NotConnected&&unused==0);
        start(*r);assert(r->epoch()==1);Client a{r.get()};a.open();a.lookup();
        assert(drain(*r)==0&&a.servers.empty());
        assert(r->send(a.id,0,0x1234,cap,sizeof(cap))==Router::NotConnected);
        auto wrong=endpoint;wrong.service=64;
        assert(r->announce(wrong)==Router::Invalid);assert(drain(*r)==0);
        announce(*r);assert(drain(*r)==1);
        assert(a.servers[0]==std::make_tuple(true,0x45u,1u,7u,0u,0x1234u));
        announce(*r);a.lookup();assert(drain(*r)==0);
        Client b{r.get()},c{r.get()},d{r.get()};b.open();c.open();d.open();
        b.lookup();c.lookup(8);d.lookup(7);
        assert(drain(*r)==2&&b.servers.size()==1&&c.servers.empty()&&d.servers.size()==1);
        assert(r->open(nullptr,nullptr,nullptr,unused)==Router::Full);
        assert(r->lookup(a.id,0x45,1,8)==Router::Busy);
        assert(r->lookup(c.id,0x45,2,0)==Router::Invalid);
        assert(r->receive(b.id,1,endpoint.port,cap_reply,sizeof(cap_reply))==Router::NotConnected);
        assert(r->receive(b.id,0,endpoint.port+1,cap_reply,sizeof(cap_reply))==Router::NotConnected);
        assert(r->receive(b.id,0,endpoint.port,cap_reply,sizeof(cap_reply))==Router::Ok);
        assert(drain(*r)==1&&a.packets.empty()&&b.packets.size()==1);
        assert(b.packets[0]==std::vector<uint8_t>(cap_reply,cap_reply+sizeof(cap_reply)));
        a.close();b.close();c.close();d.close();
    }
    // send copies, preserves FIFO under GLINK backpressure, and supports 8192
    // payload bytes independently of the owner's additional 32-byte QRTR header.
    {auto r=std::make_unique<Router>();start(*r);announce(*r);Client a{r.get()},b{r.get()};a.open();b.open();
        std::vector<uint8_t> payload(8193);
        for(unsigned i=0;i<payload.size();++i)payload[i]=(uint8_t)(i*13);
        auto expected=payload;
        assert(r->send(a.id,0,endpoint.port,payload.data(),8193)==Router::TooLarge);
        assert(r->send(a.id,0,endpoint.port,payload.data(),8192)==Router::Ok);
        payload.assign(payload.size(),0xee);
        for(unsigned i=0;i<3;++i)assert(r->send(b.id,0,endpoint.port,cap,sizeof(cap))==Router::Ok);
        assert(r->send(a.id,0,endpoint.port,cap,sizeof(cap))==Router::Full);
        Router::Send first,again;
        assert(r->begin_send(first)==Router::Ok&&first.bytes==8192&&first.local==a.id&&first.epoch==1);
        assert(!memcmp(first.data,expected.data(),8192));
        assert(r->begin_send(again)==Router::Busy);
        assert(r->finish_send(first.ticket+1,true)==Router::Invalid);
        assert(r->finish_send(first.ticket,false)==Router::Ok);
        assert(r->begin_send(again)==Router::Ok&&again.local==a.id&&again.ticket!=first.ticket);
        assert(!memcmp(again.data,expected.data(),8192));
        assert(r->finish_send(first.ticket,true)==Router::Invalid);
        assert(r->finish_send(again.ticket,true)==Router::Ok);
        for(unsigned i=0;i<3;++i) {
            assert(r->begin_send(again)==Router::Ok&&again.local==b.id&&again.bytes==sizeof(cap));
            assert(!memcmp(again.data,cap,sizeof(cap)));assert(r->finish_send(again.ticket,true)==Router::Ok);
        }
        assert(r->begin_send(again)==Router::Empty);a.close();b.close();
    }
    // Callbacks run without the local lock and may enqueue a response. Receive
    // buffers remain owned until finish_callback, even when other slots fill.
    {auto r=std::make_unique<Router>();start(*r);announce(*r);Client a{r.get()};a.open();a.reply=true;
        std::vector<uint8_t> packet(8192,0x5a);
        assert(r->receive(a.id,0,endpoint.port,packet.data(),packet.size())==Router::Ok);
        packet.assign(packet.size(),0);
        Router::Callback held,other;assert(r->begin_callback(held)==Router::Ok&&held.bytes==8192);
        for(unsigned i=0;i<3;++i)assert(r->receive(a.id,0,endpoint.port,cap_reply,sizeof(cap_reply))==Router::Ok);
        assert(r->receive(a.id,0,endpoint.port,cap_reply,sizeof(cap_reply))==Router::Full);
        assert(r->begin_callback(other)==Router::Busy);held.invoke();
        assert(a.packets[0]==std::vector<uint8_t>(8192,0x5a));
        assert(r->finish_callback(held.ticket+1)==Router::Invalid);
        assert(r->finish_callback(held.ticket)==Router::Ok);assert(drain(*r)==3);
        Router::Send sent;assert(r->begin_send(sent)==Router::Ok&&sent.bytes==8192&&sent.data[8191]==0x5a);
        assert(r->finish_send(sent.ticket,true)==Router::Ok);a.close();
    }
    // A native close must wait for leased callback/send use. Merely requesting
    // close is not permission to free the callback context or its message data.
    {auto r=std::make_unique<Router>();start(*r);announce(*r);Client a{r.get()};a.open();a.lookup();drain(*r);
        assert(r->receive(a.id,0,endpoint.port,cap_reply,sizeof(cap_reply))==Router::Ok);
        assert(r->send(a.id,0,endpoint.port,cap,sizeof(cap))==Router::Ok);
        Router::Callback held;Router::Send sent;
        assert(r->begin_callback(held)==Router::Ok&&r->begin_send(sent)==Router::Ok);
        auto retired=a.id;
        assert(r->begin_close(retired)==Router::Busy&&r->finish_close(retired)==Router::Busy);
        assert(r->send(retired,0,endpoint.port,cap,sizeof(cap))==Router::Closed);
        assert(r->receive(retired,0,endpoint.port,cap_reply,sizeof(cap_reply))==Router::Closed);
        held.invoke();assert(r->finish_callback(held.ticket)==Router::Ok);
        assert(r->finish_close(retired)==Router::Busy);
        assert(!memcmp(sent.data,cap,sizeof(cap)));
        assert(r->finish_send(sent.ticket,false)==Router::Ok);
        assert(r->finish_close(retired)==Router::Ok);a.alive=false;
        assert(drain(*r)==0&&r->begin_send(sent)==Router::Empty);
        Client b{r.get()};b.open();assert(b.id!=retired);
        assert(r->receive(retired,0,endpoint.port,cap_reply,sizeof(cap_reply))==Router::Closed);
        b.close();
    }
    // A callback can request cancellation but cannot finish its own synchronous
    // close: the native worker must defer qmi_handle_release until it returns.
    {auto r=std::make_unique<Router>();start(*r);announce(*r);Client a{r.get()};a.open();a.lookup();
        Router::Callback held;assert(r->begin_callback(held)==Router::Ok);
        assert(r->begin_close(a.id)==Router::Busy);held.invoke();
        assert(r->finish_close(a.id)==Router::Busy);
        assert(r->finish_callback(held.ticket)==Router::Ok&&r->finish_close(a.id)==Router::Ok);
        a.alive=false;assert(drain(*r)==0);
    }
    // Endpoint replacement/PFR retires this epoch; no old queue or later actual
    // NEW_SERVER revives it. The next epoch requires all old handles closed.
    {auto r=std::make_unique<Router>();start(*r);Client a{r.get()},b{r.get()};a.open();b.open();a.lookup();b.lookup();
        announce(*r);assert(drain(*r)==2);
        assert(r->send(a.id,0,endpoint.port,cap,sizeof(cap))==Router::Ok);
        assert(r->receive(b.id,0,endpoint.port,cap_reply,sizeof(cap_reply))==Router::Ok);
        auto replacement=endpoint;replacement.port++;
        assert(r->withdraw(replacement)==Router::NotConnected&&r->instance_live());
        assert(r->announce(replacement)==Router::InstanceLost&&!r->instance_live());
        Router::Send sent;assert(r->begin_send(sent)==Router::Empty);
        assert(r->receive(a.id,0,endpoint.port,cap_reply,sizeof(cap_reply))==Router::NotConnected);
        assert(r->send(a.id,0,replacement.port,cap,sizeof(cap))==Router::NotConnected);
        assert(r->announce(replacement)==Router::NotConnected&&r->start_instance()==Router::Busy);
        assert(drain(*r)==2&&a.packets.empty()&&b.packets.empty());
        assert(!std::get<0>(a.servers.back())&&!std::get<0>(b.servers.back()));
        assert(std::get<5>(a.servers.back())==endpoint.port);
        r->invalidate();assert(drain(*r)==0);auto old=a.id;a.close();b.close();
        start(*r);assert(r->epoch()==2);Client c{r.get()};c.open();c.lookup();
        assert(c.id!=old&&r->announce(replacement)==Router::Ok&&drain(*r)==1);
        assert(r->receive(c.id,0,endpoint.port,cap_reply,sizeof(cap_reply))==Router::NotConnected);
        assert(r->receive(old,0,replacement.port,cap_reply,sizeof(cap_reply))==Router::Closed);
        assert(r->withdraw(replacement)==Router::Ok&&drain(*r)==1);c.close();
    }
    // Withdrawing before an arrival is delivered emits neither a stale arrival
    // nor a removal of a service this observer was never told about.
    {auto r=std::make_unique<Router>();start(*r);Client a{r.get()};a.open();a.lookup();announce(*r);
        assert(r->withdraw(endpoint)==Router::Ok&&drain(*r)==0&&a.servers.empty());a.close();}
    // Invalidation preserves data leased to an in-flight callback and a send,
    // and drops their pending successors. No firmware bytes are synthesized.
    {auto r=std::make_unique<Router>();start(*r);announce(*r);Client a{r.get()};a.open();a.lookup();drain(*r);
        assert(r->receive(a.id,0,endpoint.port,cap_reply,sizeof(cap_reply))==Router::Ok);
        assert(r->send(a.id,0,endpoint.port,cap,sizeof(cap))==Router::Ok);
        Router::Callback cb;Router::Send sent;
        assert(r->begin_callback(cb)==Router::Ok&&r->begin_send(sent)==Router::Ok);
        r->invalidate();assert(!memcmp(cb.data,cap_reply,sizeof(cap_reply))&&!memcmp(sent.data,cap,sizeof(cap)));
        cb.invoke();assert(r->finish_callback(cb.ticket)==Router::Ok&&r->finish_send(sent.ticket,false)==Router::Ok);
        assert(drain(*r)==1&&r->begin_send(sent)==Router::Empty);a.close();
    }
    puts("ath10k QRTR router: four ports, owned 8192-byte datagrams, GLINK backpressure, real server lookup/removal, endpoint/epoch isolation, unlocked callback leases and close/loss retention passed");
}
'''

NATIVE_PREFIX = r'''
#include <atomic>
#include <cassert>
#include <cerrno>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <thread>
#include <vector>
using thread_t=void *;
static thread_t current_thread(){static thread_local int identity;return &identity;}
static thread_local bool holding_lock;
static std::atomic<unsigned> waits{0};
struct IOLock {std::mutex mutex;std::condition_variable event;};
static IOLock *IOLockAlloc(){return new IOLock;}
static void IOLockFree(IOLock *p){delete p;}
static void IOLockLock(IOLock *p){assert(!holding_lock);p->mutex.lock();holding_lock=true;}
static void IOLockUnlock(IOLock *p){assert(holding_lock);holding_lock=false;p->mutex.unlock();}
static void IOLockSleep(IOLock *p,void *,int){assert(holding_lock);std::unique_lock<std::mutex> lock(p->mutex,std::adopt_lock);++waits;p->event.wait(lock);lock.release();}
static void IOLockWakeup(IOLock *p,void *,bool){assert(holding_lock);p->event.notify_all();}
#define THREAD_UNINT 0
static void *IOMalloc(size_t bytes){return malloc(bytes);}
[[noreturn]] static void panic(const char *message){fprintf(stderr,"%s\n",message);abort();}
static std::atomic<const void *> installed_transport{nullptr};
extern "C" void hakios_qmi_set_transport(const struct hakios_qrtr_ops *p){installed_transport=p;}
'''

NATIVE_SUFFIX = r'''
struct NativeClient {
    bool alive=true;
    unsigned arrivals=0,removals=0,packets=0;
    std::atomic<bool> enter{false},allow{false};
    bool block=false;
    static void server(void *x,bool up,uint32_t service,uint32_t version,uint32_t instance,uint32_t node,uint32_t port) {
        auto &c=*(NativeClient *)x;assert(c.alive&&!holding_lock&&service==0x45&&version==1&&instance==7&&node==0&&port==0x1234);
        if(up)++c.arrivals;else ++c.removals;
    }
    static void receive(void *x,uint32_t node,uint32_t port,const void *data,size_t bytes) {
        auto &c=*(NativeClient *)x;assert(c.alive&&!holding_lock&&node==0&&port==0x1234);
        assert(bytes==7&&((const uint8_t *)data)[3]==0x24);++c.packets;
        if(c.block){c.enter=true;while(!c.allow.load())std::this_thread::yield();}
    }
};
struct SentPacket {uint32_t type,from,node,to;std::vector<uint8_t> bytes;};
struct Output {
    std::vector<SentPacket> sent;
    bool backpressure=false,block_control=false;
    std::atomic<bool> enter{false},allow{false};
    static bool send(void *x,uint32_t type,uint32_t from,uint32_t node,uint32_t to,const void *data,size_t bytes) {
        auto &o=*(Output *)x;assert(!holding_lock);
        if(o.backpressure)return false;
        if(type==6&&o.block_control){o.enter=true;while(!o.allow.load())std::this_thread::yield();}
        auto *p=(const uint8_t *)data;o.sent.push_back({type,from,node,to,{p,p+bytes}});return true;
    }
};
int main() {
    assert(nabu_ath10k_qrtr_prepare()&&nabu_ath10k_qrtr_start_instance());
    auto *ops=nabu_ath10k_qrtr_transport();assert(installed_transport.load()==ops);
    NativeClient client;Output output;
    auto *port=ops->open(NativeClient::receive,NativeClient::server,&client);assert(port);
    assert(!ops->lookup(port,0x45,1,0));
    assert(!nabu_ath10k_qrtr_announce(0x45,1,7,0,0x1234));
    assert(!nabu_ath10k_qrtr_poll(Output::send,&output)&&client.arrivals==1);
    const uint8_t cap[]={0,1,0,0x24,0,0,0};
    output.backpressure=true;
    assert(!ops->send(port,0,0x1234,cap,sizeof(cap)));
    assert(!nabu_ath10k_qrtr_poll(Output::send,&output)&&output.sent.empty());
    output.backpressure=false;assert(!nabu_ath10k_qrtr_poll(Output::send,&output));
    assert(output.sent.size()==1&&output.sent[0].type==1&&output.sent[0].bytes==std::vector<uint8_t>(cap,cap+7));
    auto id=output.sent[0].from;
    std::thread wrong_owner([&]{assert(nabu_ath10k_qrtr_poll(Output::send,&output)==EPERM);});wrong_owner.join();
    assert(!nabu_ath10k_qrtr_receive(0x4001,0,0x1234,cap,sizeof(cap)));
    assert(nabu_ath10k_qrtr_receive(id,1,0x1234,cap,sizeof(cap)));
    assert(!nabu_ath10k_qrtr_poll(Output::send,&output)&&client.packets==0);
    assert(nabu_ath10k_qrtr_receive(id,0,0x1234,cap,sizeof(cap)));
    client.block=true;unsigned before=waits;
    std::atomic<bool> closed{false};
    std::thread closer([&]{while(!client.enter.load())std::this_thread::yield();ops->close(port);closed=true;});
    std::thread release([&]{while(waits.load()==before)std::this_thread::yield();assert(!closed.load());client.allow=true;});
    assert(!nabu_ath10k_qrtr_poll(Output::send,&output));closer.join();release.join();
    assert(closed&&client.packets==1);client.alive=false;
    assert(nabu_ath10k_qrtr_receive(id,0,0x1234,cap,sizeof(cap)));
    // shutdown waits for a DEL_CLIENT send that has already left the lock too.
    output.block_control=true;before=waits;std::atomic<bool> stopped{false};
    std::thread stopper([&]{while(!output.enter.load())std::this_thread::yield();nabu_ath10k_qrtr_shutdown();stopped=true;});
    std::thread release_control([&]{while(waits.load()==before)std::this_thread::yield();assert(!stopped.load());output.allow=true;});
    assert(!nabu_ath10k_qrtr_poll(Output::send,&output));stopper.join();release_control.join();
    assert(stopped&&installed_transport.load()==nullptr&&output.sent.back().type==6);
    assert(output.sent.back().from==id&&output.sent.back().to==0xfffffffe&&output.sent.back().bytes.size()==20);
    assert(nabu_ath10k_qrtr_poll(Output::send,&output)==ENETDOWN);
    // A shutdown with a live QMI handle prevents callbacks/restart until that
    // handle is released. It never frees the QMI context on the caller's behalf.
    assert(nabu_ath10k_qrtr_start_instance());NativeClient second;
    auto *next=ops->open(NativeClient::receive,NativeClient::server,&second);assert(next);
    assert(!ops->lookup(next,0x45,1,0)&&!nabu_ath10k_qrtr_announce(0x45,1,7,0,0x1234));
    assert(!nabu_ath10k_qrtr_poll(Output::send,&output)&&second.arrivals==1);
    nabu_ath10k_qrtr_invalidate();assert(!nabu_ath10k_qrtr_poll(Output::send,&output)&&second.removals==1);
    nabu_ath10k_qrtr_shutdown();assert(!nabu_ath10k_qrtr_start_instance());
    assert(ops->send(next,0,0x1234,cap,sizeof(cap))==ENXIO);ops->close(next);second.alive=false;
    assert(nabu_ath10k_qrtr_start_instance());nabu_ath10k_qrtr_shutdown();
    printf("native QRTR wrapper: owner-only unlocked dispatch, concurrent close waits, DEL_CLIENT backpressure/shutdown lease, invalidation and old-handle retirement passed; heap state %zu bytes\n",sizeof(NabuQrtrNative));
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = args.output / 'qrtr.cpp'
    source.write_text(HARNESS)
    binary = args.output / 'qrtr-test'
    subprocess.run(host_command([
        'clang++-18', '-std=c++17', '-Wall', '-Wextra', '-Werror',
        '-Wno-missing-field-initializers', '-fsanitize=address,undefined',
        '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', '-g',
        '-I' + host_path(ROOT / 'patches/nabu-wireless'), host_path(source),
        '-o', host_path(binary)]), check=True)
    result = subprocess.run(host_command([host_path(binary)]), capture_output=True)
    (args.output / 'test.log').write_bytes(result.stdout)
    (args.output / 'test.stderr').write_bytes(result.stderr)
    result.check_returncode()
    native = (ROOT / 'patches/nabu-wireless/NabuAth10kQrtr.cpp').read_text()
    for include in ('#include <IOKit/IOLib.h>', '#include <IOKit/IOLocks.h>',
                    '#include <kern/thread.h>', '#include <sys/errno.h>'):
        native = native.replace(include, '')
    native = native.replace('../../src/hakios-8796/xnu/files/bsd/sys/hakios.qrtr.h', 'hakios.qrtr.h')
    native_source = args.output / 'native.cpp'
    native_source.write_text(NATIVE_PREFIX + native + NATIVE_SUFFIX)
    native_binary = args.output / 'native-test'
    subprocess.run(host_command([
        'clang++-18', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-pthread',
        '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', '-g',
        '-I' + host_path(ROOT / 'patches/nabu-wireless'),
        '-I' + host_path(ROOT / 'src/hakios-8796/xnu/files/bsd/sys'),
        host_path(native_source), '-o', host_path(native_binary)]), check=True)
    native_result = subprocess.run(host_command([host_path(native_binary)]), capture_output=True, timeout=30)
    (args.output / 'native.log').write_bytes(native_result.stdout)
    (args.output / 'native.stderr').write_bytes(native_result.stderr)
    native_result.check_returncode()
    report = {'hardware_tested': False, 'native_thread_synchronization_tested': 'host mutex/condition-variable peers; actual wrapper source',
              'sanitizers': ['address', 'undefined'],
              'result': result.stdout.decode().strip(), 'native_result': native_result.stdout.decode().strip()}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
