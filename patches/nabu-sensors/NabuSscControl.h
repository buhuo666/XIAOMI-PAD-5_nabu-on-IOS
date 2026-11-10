// SPDX-License-Identifier: BSD-2-Clause-Patent
// Reconfigure an existing SSC client/SUID on the SSC owner's serial worker.
// No waits, locks, new client ports, request list, or floating point arithmetic.
#pragma once
#include "NabuSscProtocol.h"
#include "NabuSensorHid.h"

namespace NabuSsc {
// One binary long-division step, including denominators above 2^63.
inline unsigned interval_fraction_bit(uint64_t &remainder,uint64_t denominator){
    if(remainder>=denominator-remainder){remainder-=denominator-remainder;return 1;}
    remainder+=remainder;return 0;
}
// Exact rational 1,000,000/us rounded to binary32, ties to even. All positive
// uint64 intervals produce normal finite values, so no subnormal/FP path exists.
inline uint32_t interval_rate_bits(uint64_t microseconds){
    if(!microseconds)return 0;
    uint32_t significand=uint32_t(1000000/microseconds);
    uint64_t remainder=1000000%microseconds;
    int exponent=0;
    if(significand){
        for(uint32_t n=significand;n>1;n>>=1)++exponent;
        for(int n=exponent;n<23;++n)
            significand=(significand<<1)|interval_fraction_bit(remainder,microseconds);
    }else{
        do{--exponent;significand=interval_fraction_bit(remainder,microseconds);}while(!significand);
        for(unsigned n=0;n<23;++n)
            significand=(significand<<1)|interval_fraction_bit(remainder,microseconds);
    }
    if(interval_fraction_bit(remainder,microseconds)&&(remainder||(significand&1))){
        if(++significand==0x1000000){significand>>=1;++exponent;}
    }
    return uint32_t(exponent+127)<<23|(significand&0x7fffff);
}

inline size_t encode_control_configure(uint8_t *out,size_t capacity,uint16_t transaction,
        Suid suid,bool on_change,uint64_t report_interval_us,uint32_t batch_interval_us){
    uint8_t uid[18],suspend[4],payload[5],batch[6],request[17],body[64];
    Writer u(uid,sizeof uid),s(suspend,sizeof suspend),p(payload,sizeof payload),
        batcher(batch,sizeof batch),r(request,sizeof request),b(body,sizeof body);
    u.fixed(1,suid.low,8);u.fixed(2,suid.high,8);
    s.integer(1,1);s.integer(2,0); // APSS, wakeup delivery, as in the original client.
    if(!on_change){
        uint32_t rate=interval_rate_bits(report_interval_us);if(!rate)return 0;
        p.fixed(1,rate,4); // sns_std_sensor_config.sample_rate (Hz).
    }
    // sns_std_request.batching=1; batch_spec.batch_period=1, in microseconds.
    // Send zero explicitly to clear prior batching. Unspecified flush_period
    // follows the original proto default; flush_only/max_batch remain absent.
    batcher.integer(1,batch_interval_us);r.message(1,batch,batcher.size);
    if(p.size)r.message(2,payload,p.size);
    b.message(1,uid,u.size);b.fixed(2,on_change?ChangeConfig:StreamConfig,4);
    b.message(3,suspend,s.size);b.message(4,request,r.size);
    if(!u.ok||!s.ok||!p.ok||!batcher.ok||!r.ok||!b.ok||b.size+16>capacity)return 0;
    out[0]=0;put16(out+1,transaction);put16(out+3,Control);put16(out+5,uint16_t(b.size+9));
    out[7]=1;put16(out+8,uint16_t(b.size+2));put16(out+10,uint16_t(b.size));
    memcpy(out+12,body,b.size);
    out[12+b.size]=0x10;put16(out+13+b.size,1);out[15+b.size]=1;
    return b.size+16;
}

enum class ControlStatus : uint8_t {
    Idle,Queued,Waiting,Accepted,Rejected,InvalidResponse,TimedOut,Cancelled,
    Busy,NotReady,Unsupported,BadArgument
};
struct ControlSettings {
    Suid suid{};
    uint64_t report_interval_us=0;
    uint32_t batch_interval_us=0;
    bool on_change=false,valid=false;
};
struct ControlCompletion {
    ControlStatus status=ControlStatus::Idle;
    unsigned kind=0,control=0;
    uint64_t microseconds=0;
    uint16_t transaction=0,qmi_result=0,qmi_error=0;
    uint32_t ssc_response=0;
    bool sent=false;
};

template<class IO> class ControlSession {
    IO &io;
    ControlSettings accepted[NabuSensorKindCount]{};
    ControlSettings proposed{};
    ControlCompletion pending{};
    uint32_t node=0,port=0;
    uint64_t client=0,deadline_ms=0;
    uint16_t next_transaction=0x8000;
    bool started=false;

    bool in_flight()const{
        return pending.status==ControlStatus::Queued||pending.status==ControlStatus::Waiting;
    }
public:
    enum : unsigned {ClientPort=0x100,FirstTransaction=0x8000};
    unsigned sent=0,responses=0,foreign=0,invalid=0;
    constexpr explicit ControlSession(IO &provider):io(provider){}
    // Use the exact endpoint and QMI client already learned by Census. The QMI
    // request has no client-ID input; a new QRTR source port cannot be used to
    // update that existing subscription. High transactions are demultiplexed
    // before Census (whose one-time request IDs are below 0x8000).
    void start(uint32_t remote_node,uint32_t remote_port,uint64_t existing_client){
        if(started)return;
        node=remote_node;port=remote_port;client=existing_client;started=true;
    }
    // The owner calls bind only after the INITIAL configuration was accepted.
    // Repeated binds for the same SUID preserve subsequently accepted settings.
    bool bind(unsigned kind,Suid suid,bool on_change,uint64_t report_interval_us=40000,
              uint32_t batch_interval_us=0){
        if(!started||kind>=NabuSensorKindCount||(!on_change&&!report_interval_us))return false;
        auto &a=accepted[kind];
        if(a.valid)return equal(a.suid,suid)&&a.on_change==on_change;
        a={suid,on_change?0:report_interval_us,batch_interval_us,on_change,true};return true;
    }
    const ControlSettings *settings(unsigned kind)const{
        return kind<NabuSensorKindCount&&accepted[kind].valid?&accepted[kind]:nullptr;
    }
    ControlStatus status()const{return pending.status;}
    ControlStatus queue(unsigned kind,unsigned control,uint64_t microseconds,
                        uint64_t now_ms,uint32_t timeout_ms=1000){
        if(pending.status!=ControlStatus::Idle)return ControlStatus::Busy;
        const auto *a=settings(kind);if(!started||!a)return ControlStatus::NotReady;
        if(control>NabuSensorBatchIntervalUs)return ControlStatus::Unsupported;
        if(!timeout_ms)return ControlStatus::BadArgument;
        if(control==NabuSensorReportIntervalUs){
            if(a->on_change)return ControlStatus::Unsupported;
            if(!microseconds)return ControlStatus::BadArgument;
        }else if(microseconds>UINT32_MAX)return ControlStatus::BadArgument;
        proposed=*a;
        if(control==NabuSensorReportIntervalUs)proposed.report_interval_us=microseconds;
        else proposed.batch_interval_us=uint32_t(microseconds);
        pending={};pending.status=ControlStatus::Queued;pending.kind=kind;
        pending.control=control;pending.microseconds=microseconds;pending.transaction=next_transaction;
        // Ordinary 16-bit QMI transaction cycling, with the low half reserved
        // for Census. There is never more than one outstanding control request.
        next_transaction=uint16_t(next_transaction+1)|FirstTransaction;
        deadline_ms=now_ms+timeout_ms;return pending.status;
    }
    void tick(uint64_t now_ms){
        if(!in_flight())return;
        if(now_ms>=deadline_ms){pending.status=ControlStatus::TimedOut;return;}
        if(pending.status!=ControlStatus::Queued)return;
        uint8_t bytes[80];size_t size=encode_control_configure(bytes,sizeof bytes,pending.transaction,
            proposed.suid,proposed.on_change,proposed.report_interval_us,proposed.batch_interval_us);
        if(!size){pending.status=ControlStatus::BadArgument;return;}
        if(!io.send_ssc(node,port,ClientPort,bytes,unsigned(size)))return;
        pending.sent=true;pending.status=ControlStatus::Waiting;++sent;
    }
    static bool owns(const uint8_t *bytes,uint32_t size){
        return size>=7&&bytes[0]==2&&u16(bytes+3)==Control&&u16(bytes+1)>=FirstTransaction;
    }
    // True means this reserved control reply was consumed, including late,
    // duplicate and malformed replies, so it must not enter Census afterwards.
    bool receive(uint32_t remote_node,uint32_t remote_port,uint32_t local_port,
                 const uint8_t *bytes,uint32_t size,uint64_t now_ms){
        if(!owns(bytes,size))return false;
        if(!started||remote_node!=node||remote_port!=port||local_port!=ClientPort){++foreign;return true;}
        QmiPacket p;if(!decode_qmi(bytes,size,p)){++invalid;return true;}
        if(pending.status!=ControlStatus::Waiting||p.transaction!=pending.transaction){++invalid;return true;}
        if(now_ms>=deadline_ms){pending.status=ControlStatus::TimedOut;return true;}
        if(p.has_client&&p.client!=client){++foreign;return true;}
        ++responses;pending.qmi_result=p.result;pending.qmi_error=p.error;pending.ssc_response=p.response;
        if(p.result||p.error||(p.has_response&&p.response)){pending.status=ControlStatus::Rejected;return true;}
        // In the QMI schema, success requires BOTH client ID and SSC response.
        // Transport send success or an incomplete success response is no ack.
        if(!p.has_client||!p.has_response){pending.status=ControlStatus::InvalidResponse;return true;}
        accepted[pending.kind]=proposed;pending.status=ControlStatus::Accepted;return true;
    }
    bool take_result(ControlCompletion &result){
        if(pending.status==ControlStatus::Idle||in_flight())return false;
        result=pending;pending={};return true;
    }
    void unbind(unsigned kind){
        if(kind>=NabuSensorKindCount)return;
        accepted[kind].valid=false;
        if(in_flight()&&pending.kind==kind)pending.status=ControlStatus::Cancelled;
    }
    void stop(){
        started=false;
        for(unsigned kind=0;kind<NabuSensorKindCount;++kind)unbind(kind);
    }
};
} // namespace NabuSsc
