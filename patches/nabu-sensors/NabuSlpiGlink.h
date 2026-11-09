// SPDX-License-Identifier: BSD-2-Clause-Patent
// Host-3 SMEM GLINK/IPCRTR census. Derived from the project's ADSP transport;
// no APR, audio, fake sensor, or hard-coded SSC destination node/port.
#pragma once
#include "NabuSlpiProtocol.h"

namespace NabuSlpiGlink {
enum Error : uint32_t {Ok,Queues,Pointer,Frame,Version,TxFull,Fragment,Command,PeerGone};
struct Result {
    bool negotiated,opened,remote_open,local_ack,close_sent,close_ack,broken,timeout,ssc_found;
    uint32_t error,features,lcid,rcid,tx,rx,qrtr_packets,servers,ssc_node,ssc_port,ssc_instance;
    uint32_t ignored_channels,uncached_intents;
};

template<class IO> class Link {
    enum Phase {Idle,Opening,Discovering,Sampling,Closing,Finished};
    struct Remote {uint32_t id,size;bool present,used;};
    struct Local {uint32_t offset,size,fill,left;};
    IO &io;
    Phase phase=Idle;
    Result r{};
    Remote remote[64]{};
    Local local[10]{};
    uint8_t receive_storage[69632]{}; // Original DT: 5*2048 + 3*8192 + 2*17408.
    uint32_t descriptor=0,tx=0,rx=0,tx_bytes=0,rx_bytes=0,now=0,phase_start=0;
    bool requested=false,offered=false,hello_sent=false,hello_reply=false,lookup_sent=false,intent_requested=false;
    bool sample_mode=false;
    using Receiver=void (*)(void *,uint32_t,uint32_t,uint32_t,const uint8_t *,uint32_t);
    Receiver receiver=nullptr;
    void *receiver_context=nullptr;
    uint32_t peer_node=0;
    struct Pending {uint32_t command,node,port,from_port,bytes;uint8_t payload[512];};
    Pending pending[16]{};
    unsigned pending_head=0,pending_count=0;
    static uint32_t aligned(uint32_t n){return (n+7)&~7u;}
    static uint16_t u16(const uint8_t *p){return NabuSlpi::le16(p);}
    static uint32_t u32(const uint8_t *p){return NabuSlpi::le32(p);}
    static void p16(uint8_t *p,uint16_t n){p[0]=n;p[1]=n>>8;}
    static void p32(uint8_t *p,uint32_t n){p16(p,uint16_t(n));p16(p+2,uint16_t(n>>16));}
    void fail(Error e){r.error=e;r.broken=true;phase=Finished;}
    uint32_t available(){
        uint32_t head=io.read32(descriptor+12),tail=io.read32(descriptor+8);
        if(head>=rx_bytes||tail>=rx_bytes||((head|tail)&7)){fail(Pointer);return 0;}
        return (head+rx_bytes-tail)%rx_bytes;
    }
    void peek(uint8_t *out,uint32_t offset,uint32_t n){
        uint32_t tail=io.read32(descriptor+8);
        for(uint32_t i=0;i<n;++i)out[i]=io.read8(rx+(tail+offset+i)%rx_bytes);
    }
    void advance(uint32_t n){io.write32(descriptor+8,(io.read32(descriptor+8)+n)%rx_bytes);}
    bool send(uint16_t cmd,uint16_t cid,uint32_t value,const uint8_t *extra=nullptr,uint32_t n=0){
        uint32_t head=io.read32(descriptor+4),tail=io.read32(descriptor),bytes=aligned(8+n);
        if(head>=tx_bytes||tail>=tx_bytes||((head|tail)&7)){fail(Pointer);return false;}
        uint32_t room=(tail+tx_bytes-head)%tx_bytes;if(!room)room=tx_bytes;
        if(bytes+16>room){fail(TxFull);return false;}
        uint8_t h[8];p16(h,cmd);p16(h+2,cid);p32(h+4,value);
        for(uint32_t i=0;i<bytes;++i)io.write8(tx+(head+i)%tx_bytes,i<8?h[i]:i-8<n?extra[i-8]:0);
        io.write32(descriptor+4,(head+bytes)%tx_bytes);io.ring();++r.tx;return true;
    }
    bool offer_all(){
        uint8_t pairs[80];uint32_t at=0;
        for(unsigned i=0;i<10;++i){
            uint32_t size=i<5?2048:i<8?8192:17408;local[i]={at,size,0,0};at+=size;
            p32(pairs+i*8,size);p32(pairs+i*8+4,i+1);
        }
        return send(5,uint16_t(r.lcid),10,pairs,sizeof pairs);
    }
    void queue(uint32_t cmd,uint32_t node,uint32_t port,const uint32_t *words=nullptr,uint32_t from=0xfffffffeu){
        if(pending_count==16){fail(Frame);return;}
        Pending &p=pending[(pending_head+pending_count)%16];
        p.command=cmd;p.node=node;p.port=port;p.from_port=from;
        p.bytes=20;p32(p.payload,cmd);
        for(unsigned i=0;i<4;++i)p32(p.payload+4+i*4,words?words[i]:0);
        ++pending_count;
    }
    void flush(){
        while(pending_count&&!r.broken){
            const Pending &p=pending[pending_head];
            uint32_t packet_bytes=32+((p.bytes+3)&~3u);
            int slot=-1;
            for(unsigned i=0;i<64;++i)if(remote[i].present&&!remote[i].used&&remote[i].size>=packet_bytes){slot=int(i);break;}
            if(slot<0){if(!intent_requested)intent_requested=send(7,uint16_t(r.lcid),packet_bytes);return;}
            uint8_t out[552]{};
            p32(out,packet_bytes);p32(out+8,1);p32(out+12,p.command);p32(out+16,1);p32(out+20,p.from_port);
            p32(out+28,p.bytes);p32(out+32,p.node);p32(out+36,p.port);
            for(unsigned i=0;i<p.bytes;++i)out[40+i]=p.payload[i];
            if(!send(9,uint16_t(r.lcid),remote[slot].id,out,8+packet_bytes))return;
            remote[slot].used=true;pending_head=(pending_head+1)%16;--pending_count;
        }
    }
    void qrtr(const uint8_t *p,uint32_t n){
        uint32_t type,from_node,from_port,to_node,to_port,size,at,confirm;
        if(n>=32&&u32(p)==1){
            type=u32(p+4);from_node=u32(p+8);from_port=u32(p+12);confirm=u32(p+16);
            size=u32(p+20);to_node=u32(p+24);to_port=u32(p+28);at=32;
        }else if(n>=16&&p[0]==3){
            type=p[1];confirm=p[2]&1;size=u32(p+4);from_node=u16(p+8);from_port=u16(p+10);
            to_node=u16(p+12);to_port=u16(p+14);at=16+p[3];
            if(from_port==0xfffe)from_port=0xfffffffeu;if(to_port==0xfffe)to_port=0xfffffffeu;
        }else{fail(Frame);return;}
        if(at>n||size>n-at){fail(Frame);return;}
        ++r.qrtr_packets;
        if(confirm){uint32_t words[4]={to_node,to_port,0,0};queue(7,from_node,from_port,words,to_port);}
        if(type==3){fail(PeerGone);return;}
        if(type==1&&receiver&&to_node==1&&to_port!=0xfffffffeu)
            receiver(receiver_context,from_node,from_port,to_port,p+at,size);
        if(size<4||to_port!=0xfffffffeu)return;
        uint32_t cmd=u32(p+at);
        if(cmd==2){
            peer_node=from_node;
            if(!hello_reply){queue(2,from_node,0xfffffffeu);hello_reply=true;}
            if(!lookup_sent){uint32_t words[4]={NabuSlpi::SscService,0,0,0};queue(10,from_node,0xfffffffeu,words);lookup_sent=true;}
        }else if((cmd==4||cmd==5)&&size>=20){
            uint32_t service=u32(p+at+4),instance=u32(p+at+8),node=u32(p+at+12),port=u32(p+at+16);
            if(cmd==4&&service)++r.servers;
            io.server(cmd,service,instance,node,port);
            if(service==NabuSlpi::SscService&&cmd==4&&node&&port){
                r.ssc_found=true;r.ssc_node=node;r.ssc_port=port;r.ssc_instance=instance;
            }else if(service==NabuSlpi::SscService&&cmd==5&&node==r.ssc_node&&port==r.ssc_port)r.ssc_found=false;
        }
    }
    void finish_rx(unsigned id){
        Local &l=local[id-1];l.fill=l.left=0;
        send(r.features&1?14:6,uint16_t(r.lcid),id);
        if(!(r.features&1)){uint8_t p[8];p32(p,l.size);p32(p+4,id);send(5,uint16_t(r.lcid),1,p,8);}
    }
    void close(){
        if(phase==Closing||phase==Finished)return;
        phase=Closing;phase_start=now;pending_count=0;
        if(requested)r.close_sent=send(3,uint16_t(r.lcid),0);else phase=Finished;
    }
    void pump(){
        for(unsigned rounds=0;rounds<64&&!r.broken;++rounds){
            uint32_t avail=available();if(r.broken||avail<8)return;
            uint8_t h[16]{};peek(h,0,8);uint16_t cmd=u16(h),cid=u16(h+2);uint32_t value=u32(h+4),bytes=8,chunk=0,left=0;
            if(cmd==2){uint32_t namesz=value&0xffff;if(!namesz||namesz>rx_bytes-16){fail(Frame);return;}bytes+=namesz;}
            else if(cmd==5){if(value>(rx_bytes-16)/8){fail(Frame);return;}bytes+=value*8;}
            else if(cmd==9||cmd==12){if(avail<16)return;peek(h+8,8,8);chunk=u32(h+8);left=u32(h+12);if(chunk>rx_bytes-24){fail(Frame);return;}bytes=16+chunk;}
            bytes=aligned(bytes);if(avail<bytes)return;++r.rx;
            switch(cmd){
            case 0:advance(bytes);if(!cid){fail(Version);return;}r.features&=value;send(1,1,r.features);break;
            case 1:advance(bytes);if(!cid){fail(Version);return;}if(cid==1&&value==r.features)r.negotiated=true;else{r.features&=value;send(0,1,r.features);}break;
            case 2:{
                const uint8_t name[]="IPCRTR";uint8_t actual[7]{};bool match=(value&0xffff)==sizeof name;
                if(match)peek(actual,8,sizeof actual);for(unsigned i=0;i<sizeof name&&match;++i)match=actual[i]==name[i];
                advance(bytes);if(!match){++r.ignored_channels;break;}
                if(!cid||(r.remote_open&&r.rcid!=cid)){fail(Frame);return;}r.rcid=cid;r.remote_open=true;send(4,cid,0);break;
            }
            case 4:advance(bytes);if(cid==r.lcid)r.local_ack=true;break;
            case 5:
                if(cid==r.rcid&&r.remote_open)for(unsigned i=0;i<value;++i){
                    uint8_t pair[8];peek(pair,8+i*8,8);uint32_t size=u32(pair),id=u32(pair+4);int slot=-1;
                    if(!size){fail(Frame);return;}
                    for(unsigned j=0;j<64;++j)if(remote[j].present&&remote[j].id==id){slot=int(j);break;}
                    if(slot>=0&&remote[slot].used)continue;
                    if(slot<0)for(unsigned j=0;j<64;++j)if(!remote[j].present){slot=int(j);break;}
                    if(slot<0){++r.uncached_intents;continue;}remote[slot]={id,size,true,false};intent_requested=false;
                }
                advance(bytes);break;
            case 6:case 14:advance(bytes);if(cid==r.rcid)for(auto &p:remote)if(p.present&&p.id==value){p.used=false;p.present=cmd==14;}break;
            case 7:advance(bytes);if(cid==r.rcid)send(8,uint16_t(r.lcid),0);break;
            case 8:advance(bytes);if(cid==r.rcid&&intent_requested&&!value)close();break;
            case 9:case 12:{
                if(cid!=r.rcid||!r.remote_open){advance(bytes);break;}
                if(!offered||!value||value>10){fail(Frame);return;}Local &l=local[value-1];
                if((cmd==9&&l.fill)||(cmd==12&&!l.fill)||chunk>l.size-l.fill||left>l.size-l.fill-chunk||(cmd==12&&l.left!=chunk+left)){fail(Fragment);return;}
                peek(receive_storage+l.offset+l.fill,16,chunk);l.fill+=chunk;l.left=left;advance(bytes);
                if(!left){qrtr(receive_storage+l.offset,l.fill);finish_rx(value);}break;
            }
            case 13:advance(bytes);io.ring();break;
            case 3:advance(bytes);send(11,cid,0);if(cid==r.rcid)close();break;
            case 11:advance(bytes);if(cid==r.lcid&&r.close_sent)r.close_ack=true;break;
            case 15:advance(bytes);break;
            default:fail(Command);return;
            }
            if(r.broken)return;
            if(phase==Opening&&r.negotiated&&!requested){const uint8_t name[]="IPCRTR";requested=send(2,uint16_t(r.lcid),sizeof name,name,sizeof name);}
            if(phase==Opening&&r.negotiated&&r.remote_open&&r.local_ack&&!offered){
                offered=offer_all();if(!offered)return;r.opened=true;phase=Discovering;phase_start=now;
                if(!hello_sent){queue(2,0xffffffffu,0xfffffffeu);hello_sent=true;}
            }
            if(phase==Discovering||phase==Sampling)flush();
        }
    }
public:
    constexpr explicit Link(IO &provider):io(provider){}
    bool begin(uint32_t desc,uint32_t tx_at,uint32_t tx_size,uint32_t rx_at,uint32_t rx_size,
               bool samples=false,Receiver receive=nullptr,void *context=nullptr){
        if(phase!=Idle||tx_size<256||rx_size<256||((tx_size|rx_size)&7)){fail(Queues);return false;}
        descriptor=desc;tx=tx_at;tx_bytes=tx_size;rx=rx_at;rx_bytes=rx_size;r.features=1;r.lcid=1;phase=Opening;
        sample_mode=samples;receiver=receive;receiver_context=context;
        return send(0,1,1);
    }
    void step(uint32_t elapsed_ms){
        if(phase==Idle||phase==Finished)return;now=elapsed_ms;pump();if(r.broken)return;
        if(phase==Discovering||phase==Sampling)flush();
        if((phase==Opening&&now-phase_start>=5000)||(phase==Discovering&&now-phase_start>=10000)||
           (phase==Sampling&&now-phase_start>=9000)){r.timeout=true;close();}
        if(phase==Discovering&&r.ssc_found){
            if(sample_mode){phase=Sampling;phase_start=now;}else close();
        }
        if(phase==Closing&&(r.close_ack||now-phase_start>=1000)){if(!r.close_ack)r.timeout=true;phase=Finished;}
    }
    void abort(){fail(PeerGone);}
    bool send_data(uint32_t node,uint32_t port,uint32_t from_port,const uint8_t *data,uint32_t bytes){
        if(phase!=Sampling||r.broken||pending_count==16||bytes>512)return false;
        Pending &p=pending[(pending_head+pending_count)%16];
        p.command=1;p.node=node;p.port=port;p.from_port=from_port;p.bytes=bytes;
        for(unsigned i=0;i<bytes;++i)p.payload[i]=data[i];
        ++pending_count;return true;
    }
    void finish(){close();}
    bool done()const{return phase==Finished;}
    const Result &result()const{return r;}
};
} // namespace NabuSlpiGlink
