#!/usr/bin/env python3
"""Exercise the production cold-boot GLINK handoff and QRTR wire framing."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path
from check_nabu_glink import PREFIX

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = r'''
#define NABU_ATH10K_SERVICE 1
#include "NabuAth10kQrtr.h"
static NabuAth10kQrtr router;
static unsigned arrivals,removals,deliveries;
static std::vector<uint8_t> last_rx;
using Send=bool (*)(void *,uint32_t,uint32_t,uint32_t,uint32_t,const void *,size_t);
static void nabu_ath10k_qrtr_invalidate(){router.invalidate();}
static int nabu_ath10k_qrtr_announce(uint32_t s,uint32_t v,uint32_t i,uint32_t n,uint32_t p){return router.announce({s,v,i,n,p});}
static bool nabu_ath10k_qrtr_receive(uint32_t l,uint32_t n,uint32_t p,const void *d,size_t z){
    bool owned=router.owns_port(l);if(owned)router.receive(l,n,p,d,z);return owned;
}
static int nabu_ath10k_qrtr_poll(Send send,void *cookie){
    NabuAth10kQrtr::Send packet;
    while(router.begin_send(packet)==NabuAth10kQrtr::Ok){
        bool sent=send(cookie,1,packet.local,packet.node,packet.port,packet.data,packet.bytes);
        router.finish_send(packet.ticket,sent);if(!sent)break;
    }
    NabuAth10kQrtr::Callback cb;
    while(router.begin_callback(cb)==NabuAth10kQrtr::Ok){cb.invoke();router.finish_callback(cb.ticket);}
    return 0;
}
'''
TEST = r'''
alignas(16) static uint8_t shared[65536];
static uint32_t bell;
int main(){
    NabuGlink g{};g.memory={shared,sizeof(shared)};g.doorbell=&bell;
    g.descriptor={0,32};g.tx={0x4000,16384};g.rx={0x8000,16384};g.opened=true;
    g.qmi_enabled=g.wlan_runtime=g.ath10k_runtime=true;
    g.wlfw.complete=true;g.wlfw.dynamic_feature_complete=true;
    assert(router.start_instance()==NabuAth10kQrtr::Ok);
    auto server=[&](unsigned cmd,unsigned node,unsigned port){
        QrtrHeader h{1,cmd,0,control_port,0,20,1,control_port};
        QrtrControl c{cmd,{0x45,1,node,port}};uint8_t wire[52];
        memcpy(wire,&h,32);memcpy(wire+32,&c,20);g.qrtr(wire,sizeof(wire));
    };
    server(4,0,35);assert(g.wlfw_node==0&&g.wlfw_port==35);
    uint32_t local=0;
    assert(router.open([](void *,uint32_t n,uint32_t p,const void *d,size_t z){
        assert(n==0&&p==35);++deliveries;last_rx.assign((const uint8_t *)d,(const uint8_t *)d+z);
    },[](void *,bool up,uint32_t s,uint32_t v,uint32_t,uint32_t n,uint32_t p){
        assert(s==0x45&&v==1&&n==0&&p==35);if(up)++arrivals;else ++removals;
    },nullptr,local)==NabuAth10kQrtr::Ok);
    assert(router.lookup(local,0x45,1,0)==NabuAth10kQrtr::Ok);
    g.runtime_tick();assert(arrivals==1&&runtime_starts==0);
    g.wlfw.init_done=true;g.runtime_tick();assert(runtime_starts==0); // FW_READY is mandatory.
    g.wlfw.fw_ready=true;g.tftp_flush();assert(g.word(4)==0&&g.wlan_config.phase==NabuWlanConfig::Idle);
    g.runtime_tick();assert(runtime_starts==0&&g.ath10k_retired_ports==0);
    g.store(0,0);g.store(4,0);g.remote[0]={11,1024,true,false};g.remote[1]={12,1024,true,false};
    g.runtime_tick();g.runtime_tick();assert(runtime_starts==1&&g.ath10k_started&&g.keep_running(60000));
    assert(g.ath10k_retired_ports==2);
    for(unsigned i=0;i<2;++i){
        QrtrHeader retired;memcpy(&retired,shared+g.tx.offset+72*i+16,32);
        assert(retired.type==6&&retired.from_port==0x4003+i&&retired.to_port==control_port);
        assert(NabuRmtfs::u32(shared+g.tx.offset+72*i+56)==0x4003+i);
    }
    // New backend requests are copied by the sole GLINK writer, with 8192 bytes
    // of QMI payload PLUS the actual 32-byte QRTR header, including FIFO wrap.
    std::vector<uint8_t> payload(8192);for(unsigned i=0;i<payload.size();++i)payload[i]=i%251;
    assert(router.send(local,0,35,payload.data(),payload.size())==NabuAth10kQrtr::Ok);
    g.ath10k_poll();assert(!g.broken&&g.intent_requested); // No remote intent: backpressure.
    g.store(0,15000);g.store(4,15000);g.remote[0]={71,8224,true,false};
    g.ath10k_poll();assert(g.remote[0].used);
    std::vector<uint8_t> out(8240);for(unsigned i=0;i<out.size();++i)out[i]=shared[g.tx.offset+(15000+i)%g.tx.size];
    QrtrHeader h;memcpy(&h,out.data()+16,32);
    assert(h.type==1&&h.from_port==local&&h.to_port==35&&h.size==8192);
    assert(!memcmp(out.data()+48,payload.data(),8192));
    // Incoming transport validates the source before handing bytes to QMI.
    std::vector<uint8_t> incoming(8224);h={1,1,0,35,0,8192,1,local};
    memcpy(incoming.data(),&h,32);memcpy(incoming.data()+32,payload.data(),8192);
    g.qrtr(incoming.data(),incoming.size());g.ath10k_poll();assert(deliveries==1&&last_rx==payload);
    h.from_port=36;memcpy(incoming.data(),&h,32);g.qrtr(incoming.data(),incoming.size());
    g.ath10k_poll();assert(deliveries==1);
    server(5,0,36);assert(!g.wlfw.instance_lost);
    server(5,0,35);g.ath10k_poll();assert(g.wlfw.instance_lost&&removals==1&&runtime_losses==1);
    assert(!g.keep_running(60000));
    h.from_port=35;memcpy(incoming.data(),&h,32);g.qrtr(incoming.data(),incoming.size());g.ath10k_poll();
    assert(deliveries==1&&g.wlan_config.phase!=NabuWlanConfig::Enabled);
    server(4,0,41);g.runtime_tick();assert(runtime_starts==1&&!router.instance_live());
    assert(router.begin_close(local)==NabuAth10kQrtr::Ok&&router.finish_close(local)==NabuAth10kQrtr::Ok);
    puts("ath10k GLINK: actual FW_READY-only one-time worker handoff, old KNEL/DMON DEL_CLIENT before new registration, old CFG/MODE suppression, real endpoint replay, 8192-byte payload framing/backpressure/wrap, wrong-source rejection and endpoint-loss retirement passed");
}
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    source=(ROOT/'patches/nabu-wireless/NabuGlink.cpp').read_text()
    source=source[source.index('struct GlinkMessage'):source.index('extern "C" void nabu_glink_trial')]
    source=source.replace('__asm__ volatile("dsb sy" ::: "memory");','(void)0;')
    cpp=args.output/'ath10k-glink.cpp';cpp.write_text(PREFIX+BRIDGE+source+TEST)
    binary=args.output/'ath10k-glink'
    subprocess.run(host_command(['clang++-18','-std=c++17','-fsanitize=address,undefined',
        '-fno-omit-frame-pointer','-I'+host_path(ROOT/'patches/nabu-wireless'),host_path(cpp),'-o',host_path(binary)]),check=True)
    result=subprocess.run(host_command([host_path(binary)]),capture_output=True)
    (args.output/'test.log').write_bytes(result.stdout);(args.output/'test.stderr').write_bytes(result.stderr)
    result.check_returncode()
    report={'hardware_tested':False,'production_glink_tested':True,'sanitizers':['address','undefined'],
            'result':result.stdout.decode().splitlines()[-1]}
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':main()
