// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "NabuRmtfs.h"

struct NabuWlfw {
    uint8_t request[6200]{};
    unsigned bytes = 0, step = 0, elapsed = 0;
    uint16_t transaction = 0, message = 0;
    bool waiting = false, failed = false, complete = false;
    bool activate = false, permissions_ready = false, capability_valid = false, msa_ready = false;
    const uint8_t *board_data=nullptr;
    unsigned board_bytes=0,board_sent=0,board_segment=0,chunk=0;
    bool fw_ready=false;
    bool init_done=false,status_valid=false;
    unsigned pin_result_count=0,pin_result_step=0;
    bool pin_result_valid[3]{};
    uint32_t pin_result[3]{};
    bool dynamic_feature_complete=false;
    bool dynamic_prev_valid=false,dynamic_current_valid=false;
    uint64_t dynamic_prev=0,dynamic_current=0;
    unsigned rejuvenate_count=0,rejuvenate_step=0;
    bool rejuvenate_valid[4]{};
    uint8_t rejuvenate_cause=0,rejuvenate_subsystem=0;
    uint16_t rejuvenate_line=0;
    char rejuvenate_function[129]{};
    bool rejuvenate_ack_finished=false,rejuvenate_ack_success=false;
    bool board_id_valid=false;
    bool mac_available=false,mac_set=false;
    uint8_t mac_address[6]{};
    uint64_t fw_status=0;
    uint32_t chip_id=0,chip_family=0,board_id=0xff,soc_id=0,fw_version=0;
    char build_id[129]{};
    struct Region { uint64_t address; uint32_t size; bool secure; } regions[2]{};
    unsigned region_count = 0;
    unsigned local_port() const { return rejuvenate_count||(step==5&&!dynamic_feature_complete)?0x4003:board_data&&step>=5?0x4004:0x4003; }
    void value(unsigned type, uint64_t value, unsigned size) {
        request[bytes++]=type;request[bytes++]=size;request[bytes++]=0;
        for(unsigned i=0;i<size;++i)request[bytes++]=value>>(8*i);
    }
    void prepare() {
        static const uint16_t ids[]={0x20,0x34,0x2d,0x2e,0x24,0x20,0x25,0x26,0x33};
        if(rejuvenate_count){if(rejuvenate_ack_finished||failed)return;message=0x3a;}
        else {
            if(failed||step>=(board_data?(mac_available?9u:8u):activate?5u:3u))return;
            message=step==5&&!dynamic_feature_complete?0x3b:ids[step];
        }
        ++transaction;memset(request,0,sizeof(request));bytes=7;
        request[1]=transaction;request[2]=transaction>>8;request[3]=message;request[4]=message>>8;
        if(message==0x3a)return; // No data path is active; acknowledge the stop through KNEL.
        if(message==0x3b){value(0x10,1,8);request[5]=bytes-7;return;}
        if(step==0||step==5){
            value(0x10,1,1);
            if(step!=0){value(0x11,1,1);value(0x12,1,1);}
            value(0x13,1,1);
            if(step==0)value(0x14,1,1); // ICNSS KNEL subscribes to pin-connect results.
            value(0x15,step==0?0x4b4e454c:0x444d4f4e,4);value(0x18,1,1);
            if(step==0)value(0x19,1,4); // Original Android quirks=128 enables rejuvenation.
        }
        if(step==1)value(0x10,board_data?1:0,4);
        if(step==2){value(1,0x8bc00000,8);value(2,0x180000,4);}
        if(step==6){
            chunk=board_bytes-board_sent; if(chunk>6144)chunk=6144;
            value(1,1,1);value(0x10,0,4);value(0x11,board_bytes,4);value(0x12,board_segment,4);
            request[bytes++]=0x13;request[bytes++]=chunk+2;request[bytes++]=(chunk+2)>>8;
            request[bytes++]=chunk;request[bytes++]=chunk>>8;
            memcpy(request+bytes,board_data+board_sent,chunk);bytes+=chunk;value(0x14,board_sent+chunk==board_bytes,1);
            value(0x15,0,1); // Original Xiaomi daemon explicitly selects BIN board-data type.
        }
        if(step==7){
            value(1,0,1); // Report no saved calibration IDs; this is not a calibration-complete result.
            // Official Xiaomi cnss-daemon: builder 0xf4c0, QMI descriptor 0x7623.
            // Optional TLV 0x11 is u8(0); its field semantics are still unknown.
            value(0x11,0,1);
        }
        if(step==8){
            request[bytes++]=0x10;request[bytes++]=6;request[bytes++]=0;
            memcpy(request+bytes,mac_address,6);bytes+=6;
        }
        request[5]=bytes-7;request[6]=(bytes-7)>>8;
    }
    void sent() {waiting=true;elapsed=0;}
    void tick(){if(waiting&&++elapsed>=10000){waiting=false;failed=true;}}
    bool receive(const uint8_t *data,unsigned size) {
        if(size<7||NabuRmtfs::u16(data+5)!=size-7)return false;
        if(data[0]==4){
            uint16_t indication=NabuRmtfs::u16(data+3);
            if(indication==0x21)fw_ready=true;
            if(indication==0x38)init_done=true;
            if(indication==0x2c){
                ++pin_result_count;pin_result_step=step;
                for(unsigned i=0;i<3;++i){
                    unsigned length=0;const uint8_t *p=NabuRmtfs::tlv(data,size,0x10+i,length);
                    pin_result_valid[i]=p&&length==4;
                    pin_result[i]=pin_result_valid[i]?NabuRmtfs::u32(p):0;
                }
            }
            if(indication==0x39){
                ++rejuvenate_count;rejuvenate_step=step;
                unsigned length=0;const uint8_t *p=NabuRmtfs::tlv(data,size,0x10,length);
                rejuvenate_valid[0]=p&&length==1;rejuvenate_cause=rejuvenate_valid[0]?p[0]:0;
                p=NabuRmtfs::tlv(data,size,0x11,length);
                rejuvenate_valid[1]=p&&length==1;rejuvenate_subsystem=rejuvenate_valid[1]?p[0]:0;
                p=NabuRmtfs::tlv(data,size,0x12,length);
                rejuvenate_valid[2]=p&&length==2;rejuvenate_line=rejuvenate_valid[2]?NabuRmtfs::u16(p):0;
                p=NabuRmtfs::tlv(data,size,0x13,length);
                rejuvenate_valid[3]=p&&length<=128;memset(rejuvenate_function,0,sizeof(rejuvenate_function));
                if(rejuvenate_valid[3])memcpy(rejuvenate_function,p,length);
                if(rejuvenate_count==1){waiting=false;failed=false;complete=false;bytes=0;}
            }
            return false;
        }
        if(data[0]!=2||NabuRmtfs::u16(data+1)!=transaction||NabuRmtfs::u16(data+3)!=message)return false;
        unsigned length=0;const uint8_t *result=NabuRmtfs::tlv(data,size,2,length);
        if(!waiting||!result||length!=4)return false;
        waiting=false;
        if(message==0x3a){
            rejuvenate_ack_finished=true;rejuvenate_ack_success=NabuRmtfs::u16(result)==0;
            failed=!rejuvenate_ack_success;bytes=0;return true;
        }
        if(message==0x3b){
            const uint8_t *p=NabuRmtfs::tlv(data,size,0x10,length);
            dynamic_prev_valid=p&&length==8;dynamic_prev=dynamic_prev_valid?(uint64_t)NabuRmtfs::u32(p)|(uint64_t)NabuRmtfs::u32(p+4)<<32:0;
            p=NabuRmtfs::tlv(data,size,0x11,length);
            dynamic_current_valid=p&&length==8;dynamic_current=dynamic_current_valid?(uint64_t)NabuRmtfs::u32(p)|(uint64_t)NabuRmtfs::u32(p+4)<<32:0;
            failed=NabuRmtfs::u16(result)!=0;dynamic_feature_complete=!failed;bytes=0;return true;
        }
        // Some older firmware doesn't implement host capabilities (QMI error 94).
        if(NabuRmtfs::u16(result) && !(step==1&&NabuRmtfs::u16(result+2)==94)){failed=true;return true;}
        if(message==0x20){
            status_valid=false;fw_status=0;
            const uint8_t *status=NabuRmtfs::tlv(data,size,0x10,length);
            if(status&&length==8){status_valid=true;fw_status=(uint64_t)NabuRmtfs::u32(status)|(uint64_t)NabuRmtfs::u32(status+4)<<32;}
        }
        if(step==2){
            const uint8_t *list=NabuRmtfs::tlv(data,size,3,length);
            if(!list||!length||list[0]>2||length!=1+13*list[0]){failed=true;return true;}
            region_count=list[0];
            for(unsigned i=0;i<region_count;++i){
                const uint8_t *p=list+1+13*i;
                regions[i]={(uint64_t)NabuRmtfs::u32(p)|(uint64_t)NabuRmtfs::u32(p+4)<<32,NabuRmtfs::u32(p+8),p[12]!=0};
                if(regions[i].address<0x8bc00000||regions[i].address>0x8bd80000||regions[i].size>0x8bd80000-regions[i].address)failed=true;
            }
        }
        if(step==3)msa_ready=true;
        if(step==4){
            const uint8_t *p=NabuRmtfs::tlv(data,size,0x10,length);
            if(p&&length==8){chip_id=NabuRmtfs::u32(p);chip_family=NabuRmtfs::u32(p+4);capability_valid=true;}
            p=NabuRmtfs::tlv(data,size,0x11,length);if(p&&length==4){board_id=NabuRmtfs::u32(p);board_id_valid=true;}
            p=NabuRmtfs::tlv(data,size,0x12,length);if(p&&length==4)soc_id=NabuRmtfs::u32(p);
            p=NabuRmtfs::tlv(data,size,0x13,length);if(p&&length>=4)fw_version=NabuRmtfs::u32(p);
            p=NabuRmtfs::tlv(data,size,0x14,length);if(p){unsigned n=length<128?length:128;memcpy(build_id,p,n);build_id[n]=0;}
        }
        if(step==6){board_sent+=chunk;++board_segment;if(board_sent<board_bytes){bytes=0;return true;}}
        if(step==8)mac_set=true;
        ++step;complete=step==(board_data?(mac_available?9u:8u):activate?5u:3u)&&!failed;bytes=0;return true;
    }
};
