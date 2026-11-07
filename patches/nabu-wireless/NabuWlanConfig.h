// SPDX-License-Identifier: ISC
// Configuration tables derived from ath10k snoc.c:
// Copyright (c) 2018 The Linux Foundation. All rights reserved.
#pragma once
#include "NabuRmtfs.h"

// WCN399x SNOC configuration from the fixed Nabu ath10k snoc.c and WLFW IDL.
// These are target CE depths, not host ring depths. See the data-path report.
struct NabuWlanConfig {
    struct Pipe { uint32_t id, direction, entries, max_bytes, flags; };
    struct Service { uint32_t id, direction, pipe; };
    struct Shadow { uint16_t pipe, offset; };
    static constexpr Pipe pipes[] = {
        {0,2,32,2048,0},{1,1,32,2048,0},{2,1,64,2048,0},{3,2,32,2048,0},
        {4,2,256,256,8},{5,2,1024,64,8},{6,3,32,16384,0},{7,4,0,0,8},
        {8,1,32,2048,0},{9,1,32,2048,0},{10,1,32,2048,0},{11,1,32,2048,0}
    };
    static constexpr Service services[] = {
        {0x104,2,3},{0x104,1,2},{0x102,2,3},{0x102,1,2},
        {0x101,2,3},{0x101,1,2},{0x103,2,3},{0x103,1,2},
        {0x100,2,3},{0x100,1,2},{1,2,0},{1,1,2},
        {0xfe00,2,0},{0xfe00,1,2},{0x300,2,4},{0x300,1,1},
        {0xfe00,2,5},{0x301,1,9},{0x302,1,10},{0x600,1,11},{0,0,0}
    };
    static constexpr Shadow shadows[] = {
        {0,0x3c},{3,0x3c},{4,0x3c},{5,0x3c},{7,0x3c},
        {1,0x40},{2,0x40},{7,0x40},{8,0x40},{9,0x40},{10,0x40},{11,0x40}
    };
    uint8_t request[560]{};
    unsigned bytes=0, elapsed=0;
    uint16_t transaction=0, message=0, error=0;
    enum Phase { Idle, Config, Mode, Enabled, Failed, Lost } phase=Idle;
    bool waiting=false;

    void put(uint32_t value,unsigned count) {
        for(unsigned i=0;i<count;++i)request[bytes++]=(uint8_t)(value>>(8*i));
    }
    void header(uint16_t id,uint16_t tx) {
        bytes=0;message=id;transaction=tx;
        put(0,1);put(tx,2);put(id,2);put(0,2);
    }
    void array(unsigned tag,unsigned count,unsigned width) {
        put(tag,1);put(1+count*width,2);put(count,1);
    }
    void finish() { request[5]=(uint8_t)(bytes-7);request[6]=(uint8_t)((bytes-7)>>8); }
    bool begin(bool firmware_ready,bool resources_ready,uint16_t next_transaction) {
        if(phase!=Idle||!firmware_ready||!resources_ready)return false;
        phase=Config;header(0x23,next_transaction);
        array(0x11,12,20);
        for(const auto &p:pipes){put(p.id,4);put(p.direction,4);put(p.entries,4);put(p.max_bytes,4);put(p.flags,4);}
        array(0x12,21,12);
        for(const auto &s:services){put(s.id,4);put(s.direction,4);put(s.pipe,4);}
        array(0x13,12,4);
        for(const auto &s:shadows){put(s.pipe,2);put(s.offset,2);}
        finish();return true;
    }
    bool prepare_mode(uint16_t next_transaction) {
        if(phase!=Mode||waiting||bytes)return false;
        header(0x22,next_transaction);
        put(1,1);put(4,2);put(0,4); // MISSION = 0, not FTM or calibration mode.
        put(0x10,1);put(1,2);put(0,1); // hw_debug = 0, as in ath10k.
        finish();return true;
    }
    void sent(){waiting=true;elapsed=0;}
    void invalidate(){phase=Lost;waiting=false;bytes=0;}
    void tick(){if(waiting&&++elapsed>=10000){phase=Failed;waiting=false;bytes=0;}}
    bool receive(const uint8_t *data,unsigned size) {
        if(!waiting||size<7||data[0]!=2||NabuRmtfs::u16(data+5)!=size-7||
           NabuRmtfs::u16(data+1)!=transaction||NabuRmtfs::u16(data+3)!=message)return false;
        unsigned count=0;const uint8_t *result=NabuRmtfs::tlv(data,size,2,count);
        if(!result||count!=4)return false;
        waiting=false;bytes=0;error=NabuRmtfs::u16(result+2);
        if(NabuRmtfs::u16(result))phase=Failed;
        else phase=phase==Config?Mode:Enabled;
        return true;
    }
};
