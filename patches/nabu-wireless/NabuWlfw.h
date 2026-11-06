// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "NabuRmtfs.h"

struct NabuWlfw {
    uint8_t request[64]{};
    unsigned bytes = 0, step = 0, elapsed = 0;
    uint16_t transaction = 0, message = 0;
    bool waiting = false, failed = false, complete = false;
    struct Region { uint64_t address; uint32_t size; bool secure; } regions[2]{};
    unsigned region_count = 0;
    void value(unsigned type, uint64_t value, unsigned size) {
        request[bytes++]=type;request[bytes++]=size;request[bytes++]=0;
        for(unsigned i=0;i<size;++i)request[bytes++]=value>>(8*i);
    }
    void prepare() {
        static const uint16_t ids[]={0x20,0x34,0x2d};
        if(step>=3)return;
        message=ids[step];transaction=step+1;memset(request,0,sizeof(request));bytes=7;
        request[1]=transaction;request[3]=message;request[4]=message>>8;
        if(step==0){value(0x10,1,1);value(0x13,1,1);value(0x15,0x4b4e454c,4);}
        if(step==1)value(0x10,0,4);
        if(step==2){value(1,0x8bc00000,8);value(2,0x180000,4);}
        request[5]=bytes-7;request[6]=(bytes-7)>>8;
    }
    void sent() {waiting=true;elapsed=0;}
    void tick(){if(waiting&&++elapsed>=10000){waiting=false;failed=true;}}
    bool receive(const uint8_t *data,unsigned size) {
        if(size<7||data[0]!=2||NabuRmtfs::u16(data+1)!=transaction||NabuRmtfs::u16(data+3)!=message||NabuRmtfs::u16(data+5)!=size-7)return false;
        unsigned length=0;const uint8_t *result=NabuRmtfs::tlv(data,size,2,length);
        if(!waiting||!result||length!=4)return false;
        waiting=false;
        // Some older firmware doesn't implement host capabilities (QMI error 94).
        if(NabuRmtfs::u16(result) && !(step==1&&NabuRmtfs::u16(result+2)==94)){failed=true;return true;}
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
        ++step;complete=step==3&&!failed;bytes=0;return true;
    }
};
