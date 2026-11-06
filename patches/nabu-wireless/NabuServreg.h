// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "NabuRmtfs.h"

struct NabuServreg {
    const uint8_t *records = nullptr;
    unsigned count = 0, requests = 0;
    bool load(const uint8_t *data, unsigned bytes) {
        if (bytes < 8 || memcmp(data,"NSR1",4)) return false;
        count = NabuRmtfs::u32(data+4);
        if (count > (bytes-8)/140 || bytes != 8+count*140) return false;
        records = data+8; return true;
    }
    unsigned answer(const uint8_t *data, unsigned bytes, uint8_t *output) {
        if (bytes < 7 || data[0] || NabuRmtfs::u16(data+5) != bytes-7) return 0;
        requests++; memset(output,0,1024); output[0]=2; memcpy(output+1,data+1,4); output[7]=2; output[8]=4;
        unsigned msg=NabuRmtfs::u16(data+3),at=14,length=0,total=0,skip=0;
        if (msg==0x21) {
            const uint8_t *name=NabuRmtfs::tlv(data,bytes,1,length);
            if (!name || !length || length>=64) { output[10]=1;output[12]=2; }
            else {
                unsigned offset_bytes=0;const uint8_t *offset=NabuRmtfs::tlv(data,bytes,0x10,offset_bytes);
                if (offset && offset_bytes==4) skip=NabuRmtfs::u32(offset);
                for(unsigned i=0;i<count;++i) {
                    const uint8_t *entry=records+140*i;
                    if (strlen((const char*)entry)==length && !memcmp(entry,name,length)) ++total;
                }
                output[at++]=0x10;output[at++]=2;output[at++]=0;output[at++]=total;output[at++]=total>>8;
                output[at++]=0x11;output[at++]=2;output[at++]=0;output[at++]=1;output[at++]=0;
                if(total>skip) {
                    unsigned list=at,emitted=0,matched=0;output[at++]=0x12;at+=3;
                    for(unsigned i=0;i<count;++i) {
                        const uint8_t *entry=records+140*i;
                        if(strlen((const char*)entry)!=length || memcmp(entry,name,length)) continue;
                        if(matched++<skip)continue;
                        unsigned n=strlen((const char*)entry+64);
                        if(at+1+n+9>1024)break;
                        output[at++]=n;memcpy(output+at,entry+64,n);at+=n;
                        memcpy(output+at,entry+128,4);at+=4;output[at++]=NabuRmtfs::u32(entry+132)!=0;
                        memcpy(output+at,entry+136,4);at+=4;++emitted;
                    }
                    output[list+1]=at-list-3;output[list+2]=(at-list-3)>>8;output[list+3]=emitted;
                }
            }
        } else if(msg!=0x24) {output[10]=1;output[12]=2;}
        output[5]=at-7;output[6]=(at-7)>>8;return at;
    }
};
