// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "NabuRmtfs.h"

struct NabuWlfw {
    uint8_t request[3900]{};
    unsigned bytes = 0, step = 0, elapsed = 0;
    uint16_t transaction = 0, message = 0;
    bool waiting = false, failed = false, complete = false;
    bool activate = false, permissions_ready = false, capability_valid = false, msa_ready = false;
    const uint8_t *board_data=nullptr;
    unsigned board_bytes=0,board_sent=0,board_segment=0,chunk=0;
    bool fw_ready=false;
    bool init_done=false,status_valid=false;
    uint64_t fw_status=0;
    unsigned post_cal_wait=0;
    uint32_t chip_id=0,chip_family=0,board_id=0,soc_id=0,fw_version=0;
    char build_id[129]{};
    struct Region { uint64_t address; uint32_t size; bool secure; } regions[2]{};
    unsigned region_count = 0;
    void value(unsigned type, uint64_t value, unsigned size) {
        request[bytes++]=type;request[bytes++]=size;request[bytes++]=0;
        for(unsigned i=0;i<size;++i)request[bytes++]=value>>(8*i);
    }
    void prepare() {
        static const uint16_t ids[]={0x20,0x34,0x2d,0x2e,0x24,0x25,0x26,0x20};
        if(step>=(board_data?8u:activate?5u:3u))return;
        message=ids[step];++transaction;memset(request,0,sizeof(request));bytes=7;
        request[1]=transaction;request[2]=transaction>>8;request[3]=message;request[4]=message>>8;
        if(step==0||step==7){value(0x10,1,1);value(0x13,1,1);value(0x15,0x4b4e454c,4);value(0x18,1,1);}
        if(step==1)value(0x10,0,4);
        if(step==2){value(1,0x8bc00000,8);value(2,0x180000,4);}
        if(step==5){
            chunk=board_bytes-board_sent; if(chunk>3800)chunk=3800;
            value(1,1,1);value(0x10,0,4);value(0x11,board_bytes,4);value(0x12,board_segment,4);
            request[bytes++]=0x13;request[bytes++]=chunk+2;request[bytes++]=(chunk+2)>>8;
            request[bytes++]=chunk;request[bytes++]=chunk>>8;
            memcpy(request+bytes,board_data+board_sent,chunk);bytes+=chunk;value(0x14,board_sent+chunk==board_bytes,1);
        }
        if(step==6)value(1,0,1); // No saved calibration IDs; request firmware calibration.
        request[5]=bytes-7;request[6]=(bytes-7)>>8;
    }
    void sent() {waiting=true;elapsed=0;}
    void tick(){if(waiting&&++elapsed>=10000){waiting=false;failed=true;}if(step==7&&!waiting&&post_cal_wait<2000)++post_cal_wait;}
    bool receive(const uint8_t *data,unsigned size) {
        if(size<7||NabuRmtfs::u16(data+5)!=size-7)return false;
        if(data[0]==4){if(NabuRmtfs::u16(data+3)==0x21)fw_ready=true;if(NabuRmtfs::u16(data+3)==0x38)init_done=true;return false;}
        if(data[0]!=2||NabuRmtfs::u16(data+1)!=transaction||NabuRmtfs::u16(data+3)!=message)return false;
        unsigned length=0;const uint8_t *result=NabuRmtfs::tlv(data,size,2,length);
        if(!waiting||!result||length!=4)return false;
        waiting=false;
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
            p=NabuRmtfs::tlv(data,size,0x11,length);if(p&&length==4)board_id=NabuRmtfs::u32(p);
            p=NabuRmtfs::tlv(data,size,0x12,length);if(p&&length==4)soc_id=NabuRmtfs::u32(p);
            p=NabuRmtfs::tlv(data,size,0x13,length);if(p&&length>=4)fw_version=NabuRmtfs::u32(p);
            p=NabuRmtfs::tlv(data,size,0x14,length);if(p){unsigned n=length<128?length:128;memcpy(build_id,p,n);build_id[n]=0;}
        }
        if(step==5){board_sent+=chunk;++board_segment;if(board_sent<board_bytes){bytes=0;return true;}}
        ++step;complete=step==(board_data?8u:activate?5u:3u)&&!failed;bytes=0;return true;
    }
};
