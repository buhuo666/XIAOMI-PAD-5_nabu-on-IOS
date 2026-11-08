#!/usr/bin/env python3
"""Replay ADSP IPCRTR/SLIM QMI alongside the production APR transport."""
import argparse
import json
from pathlib import Path
from check_nabu_adsp_glink import HARNESS as APR_HARNESS, run
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = APR_HARNESS.replace('int main() {', 'static void apr_regression() {') + r'''
static Bytes qrtr(uint32_t type,uint32_t from,uint32_t to,const Bytes &body,bool compact=false,bool confirm=false) {
    Bytes p(compact?16:32);p.resize(p.size()+((body.size()+3)&~size_t(3)));
    if(compact) {
        p[0]=3;p[1]=type;p[2]=confirm;put32(p,4,body.size());
        put16(p,8,42);put16(p,10,from);put16(p,12,1);put16(p,14,to);
    } else {
        put32(p,0,1);put32(p,4,type);put32(p,8,42);put32(p,12,from);
        put32(p,16,confirm);put32(p,20,body.size());put32(p,24,1);put32(p,28,to);
    }
    std::copy(body.begin(),body.end(),p.begin()+(compact?16:32));return p;
}
static Bytes ctrl(uint32_t type,uint32_t service=0,uint32_t instance=0,uint32_t node=0,uint32_t port=0) {
    Bytes p(20);put32(p,0,type);put32(p,4,service);put32(p,8,instance);put32(p,12,node);put32(p,16,port);return p;
}
static Bytes qmi_response(uint16_t tid,uint16_t id,uint16_t result=0,uint16_t error=0) {
    Bytes p={2,0,0,0,0,7,0,2,4,0,0,0,0,0};put16(p,1,tid);put16(p,3,id);put16(p,10,result);put16(p,12,error);return p;
}
struct SlimFixture {
    FakeIO io;NabuAdspGlink::Link<FakeIO> link{io};uint32_t ms=0;
    std::vector<Bytes> packets;
    SlimFixture() {
        CHECK(link.begin(FakeIO::desc,FakeIO::tx,4096,FakeIO::rx,4096,false,0,0,false,false,false,true));io.take();
        io.inject(frame(0,1,1));io.inject(frame(1,1,1));tick();
        io.inject(open_frame(37));io.inject(open_frame(6,"IPCRTR"));
        io.inject(frame(4,2,0));io.inject(frame(4,1,0));
        io.inject(intent_frame(6,0,64));io.inject(intent_frame(6,42,256));tick();
        CHECK(link.result().opened&&link.slim_result().opened);
    }
    std::vector<Bytes> tick() {
        link.step(ms++);auto frames=io.take();
        for(const auto &f:frames)if(u16(f,0)==9&&u16(f,2)==1) {
            CHECK(u32(f,12)==0);uint32_t n=u32(f,8);CHECK(n<=64);
            packets.emplace_back(f.begin()+16,f.begin()+16+n);
            // Peer releases only the actual remote buffer used by this send.
            io.inject(frame(14,6,u32(f,4)));
        }
        return frames;
    }
    void input(const Bytes &p,bool fragments=false) {
        if(fragments) {
            Bytes a(p.begin(),p.begin()+13),b(p.begin()+13,p.end());
            io.inject(data_frame(6,1,a,b.size()));tick();
            io.inject(data_frame(6,1,b,0,12));
        } else io.inject(data_frame(6,1,p));
        tick();
    }
    Bytes request(uint16_t id) {
        for(unsigned attempt=0;attempt<8;++attempt) {
            for(auto it=packets.begin();it!=packets.end();++it) {
                const auto &p=*it;
                if(u32(p,4)==1&&u16(p,35)==id) {
                    CHECK(u32(p,12)==0x4001&&u32(p,24)==42&&u32(p,28)==0x1234);
                    CHECK(p[32]==0);Bytes result=p;packets.erase(it);return result;
                }
            }
            tick();
        }
        CHECK(false);return {};
    }
    void discover(bool compact=false) {
        input(qrtr(2,0xfffffffe,0xfffffffe,ctrl(2),compact,true),true);
        input(qrtr(4,0xfffffffe,0xfffffffe,ctrl(4,0x45,1,42,0x7777),compact));
        CHECK(!link.slim_result().server);
        input(qrtr(4,0xfffffffe,0xfffffffe,ctrl(4,0x301,1,42,0x1234),compact));
        CHECK(link.slim_result().server&&link.slim_result().lookup);
    }
};
static void slim_lifetime(bool compact) {
    SlimFixture f;f.discover(compact);auto select=f.request(0x20);
    CHECK(u32(select,20)==21&&u16(select,37)==14);
    const Bytes wanted={1,4,0,0,0,0,0,0x10,4,0,2,0,0,0};
    CHECK(std::equal(wanted.begin(),wanted.end(),select.begin()+39));
    uint16_t tid=u16(select,33);
    f.input(qrtr(1,0x1234,0x4001,qmi_response(tid+1,0x20),compact));
    CHECK(!f.link.slim_result().selected&&f.link.slim_result().ignored==1);
    f.input(qrtr(1,0x1234,0x4001,qmi_response(tid,0x20),compact));
    auto active=f.request(0x21);CHECK(u32(active,20)==14&&u16(active,37)==7&&u32(active,42)==2);
    f.input(qrtr(1,0x1234,0x4001,qmi_response(u16(active,33),0x21),compact));
    CHECK(f.link.slim_ready()&&f.link.slim_result().error==NabuAdspSlim::Ok);
    // APR keeps its own channel, IID and transaction ownership concurrently.
    f.io.inject(intent_frame(37,0));f.ms=101;auto outgoing=f.tick();uint32_t apr_token=0;
    for(const auto &x:outgoing)if(u16(x,0)==9&&u16(x,2)==2) {CHECK(u32(x,4)==0);apr_token=u32(x,28);}
    CHECK(apr_token!=0);f.io.inject(data_frame(37,1,reply(apr_token)));f.tick();
    CHECK(f.link.result().apr_ready&&f.link.result().close_sent&&!f.link.done()&&f.io.slim_stops==1);
    auto inactive=f.request(0x21);CHECK(u32(inactive,42)==1);
    f.input(qrtr(1,0x1234,0x4001,qmi_response(u16(inactive,33),0x21),compact));
    CHECK(!f.link.slim_ready()&&f.link.slim_result().released);
    for(unsigned i=0;i<5;++i)f.tick();
    CHECK(f.link.slim_result().close_sent);
    bool retired=false;for(const auto &p:f.packets)if(u32(p,4)==6) {
        CHECK(u32(p,32)==6&&u32(p,36)==1&&u32(p,40)==0x4001);retired=true;
    }
    CHECK(retired);f.io.inject(frame(11,1,0));f.io.inject(frame(11,2,0));f.tick();
    CHECK(f.link.done()&&!f.link.result().broken&&f.link.slim_result().close_ack);
}
static void slim_rejection_and_timeout() {
    SlimFixture rejected;rejected.discover();auto q=rejected.request(0x20);
    rejected.input(qrtr(1,0x1234,0x4001,qmi_response(u16(q,33),0x20,1,0x29)));
    CHECK(rejected.link.slim_result().error==NabuAdspSlim::QmiRejected&&!rejected.link.slim_ready());
    CHECK(!rejected.link.result().broken&&!rejected.link.done());
    SlimFixture timeout;timeout.discover();timeout.request(0x20);timeout.ms=1100;timeout.tick();
    CHECK(timeout.link.slim_result().error==NabuAdspSlim::Timeout&&!timeout.link.result().broken);
}
int main() {
    apr_regression();slim_lifetime(false);slim_lifetime(true);slim_rejection_and_timeout();
    std::printf("PASS: APR and IPCRTR share one FIFO; SLIM SELECT/ACTIVE/INACTIVE, QRTR1/3, fragments, flow-control, stale transaction and independent failures; %u assertions\n",checks);
}
'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = args.output / 'adsp-slim.cpp'
    source.write_text(HARNESS)
    binary = args.output / 'adsp-slim'
    run(host_command(['clang++-18', '-std=c++17', '-O1', '-g', '-fsanitize=address,undefined',
                      '-fno-omit-frame-pointer', '-Wall', '-Wextra', '-Werror',
                      '-I'+host_path(ROOT/'patches/nabu-audio'), host_path(source), '-o', host_path(binary)]))
    result = run(host_command([host_path(binary)]))
    report = {'status': 'passed', 'result': result.strip(), 'device_executed': False,
              'production_sources': ['NabuAdspGlink.h', 'NabuAdspSlim.h'],
              'wire_reference': 'MiCode slim-msm.c SELECT_INSTANCE and POWER, QRTR v1/v3',
              'sanitizers': ['address', 'undefined']}
    (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
