// Real SSC discovery/attributes/sampling through Android's QRTR transport.
// Shares the transport-independent wire implementation intended for XNU.
#include "../patches/nabu-sensors/NabuSscProtocol.h"
#include <sys/socket.h>
#include <linux/qrtr.h>
#include <unistd.h>
#include <poll.h>
#include <stdio.h>
#include <time.h>

using namespace NabuSsc;
static uint64_t milliseconds() { timespec t{};clock_gettime(CLOCK_BOOTTIME,&t);return uint64_t(t.tv_sec)*1000+t.tv_nsec/1000000; }
static void string(const char *s) {
    putchar('"');for(;*s;++s){unsigned char c=*s;if(c=='"'||c=='\\'){putchar('\\');putchar(c);}else if(c<32)printf("\\u%04x",c);else putchar(c);}putchar('"');
}
static void uid(Suid s) { printf("\"%016llx%016llx\"",(unsigned long long)s.high,(unsigned long long)s.low); }
static void floats(const float *v,unsigned n){putchar('[');for(unsigned i=0;i<n;++i){if(i)putchar(',');printf("%.9g",v[i]);}putchar(']');}
struct Stream { Suid suid;char type[64]{};bool active=false;unsigned samples=0;uint64_t last=0;unsigned reordered=0; };
struct Probe {
    int fd=-1;sockaddr_qrtr peer{};uint16_t transaction=0;
    Discovery discovery[7]{};Stream streams[16]{};unsigned stream_count=0,invalid=0,qmi_failures=0;
    void send(const uint8_t *data,size_t n) {
        if(!n){++invalid;return;}
        ssize_t sent=sendto(fd,data,n,0,reinterpret_cast<sockaddr*>(&peer),sizeof(peer));
        printf("{\"kind\":\"tx\",\"bytes\":%zd,\"hex\":\"",sent);for(size_t i=0;i<n;++i)printf("%02x",data[i]);puts("\"}");
    }
    void attributes(Suid s){uint8_t b[512];size_t n=encode_attributes(b,sizeof b,++transaction,s);send(b,n);}
    void configure(Suid s,const Attributes &a) {
        bool known=(!strcmp(a.type,"accel")||!strcmp(a.type,"gyro")) ? strstr(a.name,"lsm6dso")!=nullptr :
            !strcmp(a.type,"mag") ? strstr(a.name,"ak0991x")!=nullptr :
            (!strcmp(a.type,"ambient_light")||!strcmp(a.type,"ambient_light_back")) ? (strstr(a.name,"tcs3701")||strstr(a.name,"bu27030")) : false;
        if(!known||!a.available||!a.physical||!a.has(16)||stream_count==16)return;
        if(a.stream_type!=0&&a.stream_type!=1)return;
        for(unsigned i=0;i<stream_count;++i)if(equal(streams[i].suid,s))return;
        auto &stream=streams[stream_count++];stream.suid=s;strcpy(stream.type,a.type);stream.active=true;
        uint8_t b[512];size_t n=encode_configure(b,sizeof b,++transaction,s,a.stream_type==1,25.0f);send(b,n);
    }
    static void event(Suid s,uint32_t id,uint64_t ticks,Span payload,void *context) {
        auto &p=*static_cast<Probe*>(context);
        printf("{\"kind\":\"event\",\"suid\":");uid(s);printf(",\"msg_id\":%u,\"ticks\":%llu,\"received_boottime_ms\":%llu,\"payload\":\"",id,(unsigned long long)ticks,(unsigned long long)milliseconds());
        for(size_t i=0;i<payload.size;++i)printf("%02x",payload.data[i]);puts("\"}");
        if(equal(s,lookup_suid()) && id==SuidEvent){
            SuidList list;if(!parse_suids(payload,list)){++p.invalid;return;}
            printf("{\"kind\":\"suids\",\"type\":");string(list.data_type);printf(",\"count\":%u,\"ids\":[",list.count);
            for(unsigned i=0;i<list.count;++i){if(i)putchar(',');uid(list.ids[i]);}puts("]}");
            for(auto &d:p.discovery)if(d.accept_suids(list))for(unsigned i=0;i<list.count;++i)p.attributes(list.ids[i]);
        } else if(id==AttrEvent){
            Attributes a;if(!parse_attributes(payload,a)){++p.invalid;puts("{\"kind\":\"attributes_invalid\"}");return;}
            printf("{\"kind\":\"attributes\",\"suid\":");uid(s);printf(",\"name\":");string(a.name);printf(",\"vendor\":");string(a.vendor);printf(",\"type\":");string(a.type);
            printf(",\"present\":%u,\"available\":%s,\"physical\":%s,\"stream_type\":%lld,\"rates\":",a.present,a.available?"true":"false",a.physical?"true":"false",(long long)a.stream_type);
            floats(a.rates,a.rate_count);printf(",\"resolutions\":");floats(a.resolutions,a.resolution_count);printf(",\"ranges\":");floats(a.ranges,a.range_values);
            printf(",\"selected_range\":");floats(a.selected_range,a.selected_range_count);printf(",\"selected_resolution\":%.9g,\"placement\":",a.selected_resolution);floats(a.placement,a.placement_count);puts("}");
            for(auto &d:p.discovery)if(d.accept_attributes(s,a)){
                for(unsigned i=0;i<d.count;++i)if(equal(d.candidates[i].suid,s)&&d.candidates[i].state==State::Ready)p.configure(s,a);
            }
        } else if(id==SampleEvent){
            Sample sample;if(!parse_sample(payload,sample)){++p.invalid;return;}
            printf("{\"kind\":\"sample\",\"suid\":");uid(s);printf(",\"ticks\":%llu,\"accuracy\":%u,\"data\":",(unsigned long long)ticks,sample.status);floats(sample.values,sample.count);puts("}");
            for(unsigned i=0;i<p.stream_count;++i)if(equal(p.streams[i].suid,s)){
                auto &v=p.streams[i];if(v.samples&&ticks<=v.last)++v.reordered;++v.samples;v.last=ticks;
            }
        } else if(id==PhysicalConfig){
            Configuration c;if(!parse_config(payload,c)){++p.invalid;return;}
            printf("{\"kind\":\"configuration\",\"suid\":");uid(s);printf(",\"has_rate\":%s,\"rate\":%.9g,\"has_resolution\":%s,\"resolution\":%.9g,\"range\":",c.has_rate?"true":"false",c.rate,c.has_resolution?"true":"false",c.resolution);floats(c.range,c.range_count);printf(",\"mode\":");string(c.mode);puts("}");
        }
    }
};

int main(){
    setvbuf(stdout,nullptr,_IOLBF,0);static Probe p;
    p.fd=socket(AF_QIPCRTR,SOCK_DGRAM|SOCK_CLOEXEC,0);if(p.fd<0){perror("socket");return 1;}
    sockaddr_qrtr local{};socklen_t length=sizeof(local);
    if(getsockname(p.fd,reinterpret_cast<sockaddr*>(&local),&length)){perror("getsockname");return 2;}
    sockaddr_qrtr ns=local;ns.sq_port=QRTR_PORT_CTRL;qrtr_ctrl_pkt lookup{};
    lookup.cmd=QRTR_TYPE_NEW_LOOKUP;lookup.server.service=Service;
    if(sendto(p.fd,&lookup,sizeof lookup,0,reinterpret_cast<sockaddr*>(&ns),sizeof ns)<0){perror("lookup");return 3;}
    uint64_t service_end=milliseconds()+3000,end=service_end;bool started=false;
    static uint8_t bytes[65536];
    while(milliseconds()<end){
        pollfd poller{p.fd,POLLIN,0};if(poll(&poller,1,50)<=0){for(auto &d:p.discovery)d.expire(milliseconds());continue;}
        sockaddr_qrtr from{};length=sizeof from;ssize_t n=recvfrom(p.fd,bytes,sizeof bytes,0,reinterpret_cast<sockaddr*>(&from),&length);
        if(n<0){perror("recvfrom");break;}
        printf("{\"kind\":\"rx\",\"node\":%u,\"port\":%u,\"hex\":\"",from.sq_node,from.sq_port);for(ssize_t i=0;i<n;++i)printf("%02x",bytes[i]);puts("\"}");
        if(from.sq_port==QRTR_PORT_CTRL && n>=ssize_t(sizeof(qrtr_ctrl_pkt))){
            qrtr_ctrl_pkt msg;memcpy(&msg,bytes,sizeof msg);
            if(!started&&msg.cmd==QRTR_TYPE_NEW_SERVER&&msg.server.service==Service){
                p.peer={AF_QIPCRTR,msg.server.node,msg.server.port};started=true;end=milliseconds()+10000;
                printf("{\"kind\":\"ssc_service\",\"node\":%u,\"port\":%u}\n",p.peer.sq_node,p.peer.sq_port);
                const char *types[]={"accel","gyro","mag","ambient_light","pressure","proximity","ambient_light_back"};
                for(unsigned i=0;i<7;++i){uint8_t b[512];p.discovery[i].start(types[i],milliseconds(),3000);size_t size=encode_lookup(b,sizeof b,++p.transaction,types[i]);p.send(b,size);}
            }
            continue;
        }
        if(!started||from.sq_node!=p.peer.sq_node||from.sq_port!=p.peer.sq_port)continue;
        QmiPacket packet;if(!decode_qmi(bytes,size_t(n),packet)){++p.invalid;puts("{\"kind\":\"qmi_invalid\"}");continue;}
        if(packet.kind==2){
            printf("{\"kind\":\"response\",\"transaction\":%u,\"result\":%u,\"error\":%u,\"ssc_response\":%u}\n",packet.transaction,packet.result,packet.error,packet.response);
            if(packet.result||packet.error||(packet.has_response&&packet.response))++p.qmi_failures;
        }else if(!for_each_event(packet,Probe::event,&p))++p.invalid;
        for(auto &d:p.discovery)d.expire(milliseconds());
    }
    for(auto &d:p.discovery){d.expire(milliseconds());printf("{\"kind\":\"discovery_result\",\"type\":");string(d.data_type);printf(",\"state\":%u,\"candidates\":%u}\n",unsigned(d.state),d.count);}
    for(unsigned i=0;i<p.stream_count;++i){auto &s=p.streams[i];uint8_t b[512];size_t n=encode_disable(b,sizeof b,++p.transaction,s.suid);p.send(b,n);printf("{\"kind\":\"stream_result\",\"type\":");string(s.type);printf(",\"suid\":");uid(s.suid);printf(",\"samples\":%u,\"nonmonotonic\":%u}\n",s.samples,s.reordered);}
    close(p.fd);printf("{\"kind\":\"complete\",\"service_found\":%s,\"streams\":%u,\"invalid_packets\":%u,\"qmi_failures\":%u}\n",started?"true":"false",p.stream_count,p.invalid,p.qmi_failures);
    return started&&p.invalid==0&&p.qmi_failures==0?0:4;
}
