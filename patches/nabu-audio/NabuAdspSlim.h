// SPDX-License-Identifier: BSD-2-Clause-Patent
// ADSP host-2 IPCRTR channel and the original Nabu SLIMbus QMI power lease.
// Shares the APR owner's GLINK queues; it never polls SMEM independently.
// Wire contract: vendor slim-msm.c, SELECT_INSTANCE(0, MASTER=2), POWER(2/1).
#pragma once
#include <stdint.h>

namespace NabuAdspSlim {
enum Error { Ok, Frame, Fragment, Intent, QueueFull, Timeout, QmiRejected, PeerGone };
struct Result {
    bool opened=false, hello=false, lookup=false, server=false;
    bool selected=false, active=false, released=false, close_sent=false, close_ack=false;
    uint32_t rcid=0, peer=0, node=0, port=0, rx=0, tx=0, ignored=0;
    uint32_t transaction=0, message=0, qmi_result=0, qmi_error=0;
    Error error=Ok;
};

template<class Transport> class Channel {
    static constexpr uint32_t LocalCid=1, LocalPort=0x4001, Control=0xfffffffe;
    struct Local { uint8_t data[2048]; uint32_t fill=0,left=0; } local[4]{};
    struct Remote { uint32_t id=0,bytes=0; bool present=false,busy=false; } remote[16]{};
    struct Packet { uint8_t data[64]; uint32_t bytes=0; } outgoing[16]{};
    Transport &io;Result r{};
    uint32_t head=0,tail=0,now=0,started=0,sent_at=0;
    uint16_t next_transaction=1,waiting=0,message=0;
    bool requested=false,ack=false,offered=false,remote_open=false,need_intent=false;
    bool hello_queued=false,lookup_queued=false,closing=false,retired=false;

    static uint16_t u16(const uint8_t *p) {return uint16_t(p[0])|uint16_t(p[1])<<8;}
    static uint32_t u32(const uint8_t *p) {return uint32_t(u16(p))|uint32_t(u16(p+2))<<16;}
    static void p16(uint8_t *p,uint16_t x) {p[0]=uint8_t(x);p[1]=uint8_t(x>>8);}
    static void p32(uint8_t *p,uint32_t x) {p16(p,uint16_t(x));p16(p+2,uint16_t(x>>16));}
    void fail(Error e) {if(r.error==Ok)r.error=e;}
    bool send(uint16_t cmd,uint16_t cid,uint32_t value,const uint8_t *p=nullptr,uint32_t n=0) {
        return io.slim_send(cmd,cid,value,p,n);
    }
    bool packet(uint32_t type,uint32_t from,uint32_t node,uint32_t port,const uint8_t *body,uint32_t size) {
        if(head-tail==16) {fail(QueueFull);return false;}
        Packet &p=outgoing[head%16];p.bytes=32+((size+3)&~3u);
        for(unsigned i=0;i<p.bytes;++i)p.data[i]=0;
        p32(p.data,1);p32(p.data+4,type);p32(p.data+8,1);p32(p.data+12,from);
        p32(p.data+20,size);p32(p.data+24,node);p32(p.data+28,port);
        for(unsigned i=0;i<size;++i)p.data[32+i]=body[i];
        ++head;return true;
    }
    bool control(uint32_t type,uint32_t from,uint32_t node,uint32_t port,uint32_t a=0,uint32_t b=0,uint32_t c=0,uint32_t d=0) {
        uint8_t p[20];p32(p,type);p32(p+4,a);p32(p+8,b);p32(p+12,c);p32(p+16,d);
        return packet(type,from,node,port,p,sizeof(p));
    }
    void flush() {
        if(tail==head||!r.opened)return;
        Packet &p=outgoing[tail%16];int slot=-1;
        for(unsigned i=0;i<16;++i)if(remote[i].present&&!remote[i].busy&&remote[i].bytes>=p.bytes&&
            (slot<0||remote[i].bytes<remote[slot].bytes))slot=int(i);
        if(slot<0) {if(!need_intent)need_intent=send(7,LocalCid,p.bytes);return;}
        uint8_t data[72]{};p32(data,p.bytes);
        for(unsigned i=0;i<p.bytes;++i)data[8+i]=p.data[i];
        if(send(9,LocalCid,remote[slot].id,data,p.bytes+8)) {
            remote[slot].busy=true;++tail;++r.tx;
        }
    }
    void qmi(uint16_t id,bool active=true) {
        uint8_t p[21]{};uint32_t n=id==0x20?14:7;
        uint16_t tid=next_transaction++;if(!tid)tid=next_transaction++;
        p16(p+1,tid);p16(p+3,id);p16(p+5,uint16_t(n));
        p[7]=1;p16(p+8,4);p32(p+10,id==0x20?0:active?2:1);
        if(id==0x20) {p[14]=0x10;p16(p+15,4);p32(p+17,2);}
        if(packet(1,LocalPort,r.node,r.port,p,n+7)) {
            waiting=tid;message=id;sent_at=now;r.transaction=tid;r.message=id;
        }
    }
    void receive(const uint8_t *p,uint32_t bytes) {
        uint32_t at,type,node,port,to,confirm,size;
        if(bytes>=32&&u32(p)==1) {
            at=32;type=u32(p+4);node=u32(p+8);port=u32(p+12);
            confirm=u32(p+16);size=u32(p+20);to=u32(p+28);
        } else if(bytes>=16&&p[0]==3) {
            at=16+p[3];type=p[1];confirm=p[2]&1;size=u32(p+4);
            node=u16(p+8);port=u16(p+10);to=u16(p+14);
            if(port==0xfffe)port=Control;if(to==0xfffe)to=Control;
        } else {fail(Frame);return;}
        if(at>bytes||size>bytes-at) {fail(Frame);return;}
        ++r.rx;if(!r.peer)r.peer=node;
        if(confirm)control(7,to,node,port,1,to);
        const uint8_t *body=p+at;
        if(to==Control||type!=1) {
            if(size<4) {fail(Frame);return;}
            uint32_t command=u32(body);
            if(command==2)r.hello=true;
            else if((command==4||command==5)&&size>=20) {
                if(u32(body+4)==0x301&&u32(body+8)==1) {
                    if(command==4) {r.server=true;r.node=u32(body+12);r.port=u32(body+16);}
                    else {r.server=false;r.active=false;fail(PeerGone);}
                }
            } else if(command==3) {r.server=false;r.active=false;fail(PeerGone);}
            return;
        }
        if(to!=LocalPort||node!=r.node||port!=r.port||size<7||body[0]!=2||
            !waiting||u16(body+1)!=waiting||u16(body+3)!=message||u16(body+5)>size-7) {++r.ignored;return;}
        uint32_t end=7+u16(body+5);
        for(uint32_t pos=7;pos+3<=end;) {
            uint32_t n=u16(body+pos+1);if(n>end-pos-3) {fail(Frame);return;}
            if(body[pos]==2&&n==4) {
                r.qmi_result=u16(body+pos+3);r.qmi_error=u16(body+pos+5);waiting=0;
                if(r.qmi_result)fail(QmiRejected);
                else if(message==0x20)r.selected=true;
                else if(closing&&r.active) {r.active=false;r.released=true;}
                else r.active=true;
                return;
            }
            pos+=3+n;
        }
        fail(Frame);
    }
public:
    constexpr explicit Channel(Transport &owner):io(owner) {}
    // Called only with a complete frame, by the single shared GLINK owner.
    // Returns true when this channel consumed it; APR sees all other frames.
    bool command(uint16_t cmd,uint16_t cid,uint32_t value,uint32_t chunk,uint32_t left,uint32_t features) {
        if(cmd==2) {
            const uint8_t name[]="IPCRTR";uint8_t actual[sizeof(name)];
            if(value!=sizeof(name))return false;
            io.slim_peek(actual,8,sizeof(actual));
            for(unsigned i=0;i<sizeof(name);++i)if(actual[i]!=name[i])return false;
            if(!cid||(remote_open&&r.rcid!=cid)) {fail(Frame);return true;}
            r.rcid=cid;remote_open=true;send(4,cid,0);return true;
        }
        if(cmd==4&&cid==LocalCid) {ack=true;return true;}
        if(cmd==11&&cid==LocalCid) {r.close_ack=true;r.opened=false;return true;}
        if(!remote_open||cid!=r.rcid)return false;
        if(cmd==5) {
            for(unsigned i=0;i<value;++i) {
                uint8_t pair[8];io.slim_peek(pair,8+i*8,8);
                uint32_t n=u32(pair),id=u32(pair+4);int slot=-1;
                if(!n) {fail(Intent);continue;}
                for(unsigned j=0;j<16;++j)if(remote[j].present&&remote[j].id==id) {slot=int(j);break;}
                if(slot>=0&&remote[slot].busy)continue;
                if(slot<0)for(unsigned j=0;j<16;++j)if(!remote[j].present) {slot=int(j);break;}
                if(slot>=0)remote[slot]={id,n,true,false};
                need_intent=false;
            }
        } else if(cmd==6||cmd==14) {
            for(auto &i:remote)if(i.present&&i.id==value) {i.busy=false;i.present=cmd==14;}
        } else if(cmd==7)send(8,LocalCid,0);
        else if(cmd==8) {if(!value&&need_intent)fail(Intent);}
        else if(cmd==9||cmd==12) {
            if(!offered||!value||value>4) {fail(Intent);return true;}
            Local &b=local[value-1];
            if((cmd==9&&b.fill)||(cmd==12&&!b.fill)||chunk>sizeof(b.data)-b.fill||
                left>sizeof(b.data)-b.fill-chunk||(cmd==12&&b.left!=chunk+left)) {fail(Fragment);return true;}
            io.slim_peek(b.data+b.fill,16,chunk);b.fill+=chunk;b.left=left;
            if(!left) {
                receive(b.data,b.fill);b.fill=0;
                send(features&1?14:6,LocalCid,value);
                if(!(features&1)) {uint8_t pair[8];p32(pair,2048);p32(pair+4,value);send(5,LocalCid,1,pair,8);}
            }
        } else if(cmd==3) {send(11,cid,0);r.opened=false;r.active=false;fail(PeerGone);}
        return true;
    }
    void step(uint32_t ms,bool negotiated) {
        now=ms;
        if(closing&&!requested)return;
        if(negotiated&&!requested&&!closing) {
            const uint8_t name[]="IPCRTR";requested=send(2,LocalCid,sizeof(name),name,sizeof(name));started=now;
        }
        if(remote_open&&ack&&!offered&&!closing) {
            uint8_t pairs[32];for(unsigned i=0;i<4;++i) {p32(pairs+i*8,2048);p32(pairs+i*8+4,i+1);}
            offered=send(5,LocalCid,4,pairs,sizeof(pairs));r.opened=offered;
        }
        if(r.opened&&r.peer&&!hello_queued)hello_queued=control(2,Control,r.peer,Control);
        if(r.hello&&!lookup_queued&&!closing) {
            lookup_queued=control(10,LocalPort,r.peer,Control,0x301,1);r.lookup=lookup_queued;
        }
        if(waiting&&now-sent_at>=1000) {fail(Timeout);waiting=0;}
        if(r.error==Ok&&!closing&&r.server&&!waiting) {
            if(!r.selected)qmi(0x20);
            else if(!r.active)qmi(0x21);
        }
        if(requested&&!r.active&&!closing&&r.error==Ok&&now-started>=5000)fail(Timeout);
        if(closing&&!waiting) {
            if(r.active&&!r.released&&r.error==Ok)qmi(0x21,false);
            else if(!retired&&r.server)retired=control(6,LocalPort,r.peer,Control,1,LocalPort);
            else if(tail==head&&!r.close_sent)r.close_sent=send(3,LocalCid,0);
        }
        flush();
    }
    void finish() {closing=true;}
    bool done() const {return !requested||r.close_ack;}
    bool ready() const {return r.active&&r.error==Ok&&!closing;}
    const Result &result() const {return r;}
};
} // namespace NabuAdspSlim
