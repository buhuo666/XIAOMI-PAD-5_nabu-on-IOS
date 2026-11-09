/* SPDX-License-Identifier: MIT */
/* A640 fixed 32x16 RGBA8 offscreen diagnostic. Register/packet definitions and
 * solid-color path: Mesa 85fda3b36405bcaea8bffc64aa4f2651dc90770d,
 * a6xx.xml, adreno_pm4.xml, fd6_gmem_cache.h and tu_clear_blit.cc.
 * This uses the 2D raster/color path, not a shader or a Metal implementation. */
#ifndef NABU_A640_CLEAR_H
#define NABU_A640_CLEAR_H
#include "AdrenoPM4.h"
#include <stdint.h>
#include <stddef.h>

struct NabuA640ClearCommands {
    uint32_t words[160]{};
    size_t count=0;
    template<size_t N> void reg(uint32_t address,const uint32_t (&values)[N]) {
        AdrenoPM4Type4(address,N,&words[count++]);
        for(uint32_t value:values)words[count++]=value;
    }
    template<size_t N> void packet(uint32_t opcode,const uint32_t (&values)[N]) {
        AdrenoPM4Type7(opcode,N,&words[count++]);
        for(uint32_t value:values)words[count++]=value;
    }
    void idle() {AdrenoPM4Type7(0x26,0,&words[count++]);}
    void build(uint64_t target,uint64_t event) {
        count=0;
        idle();
        packet(0x65,{0x101}); // Keep IFPC disabled during the diagnostic.
        packet(0x65,{12});    // RM6_BLIT2DSCALE.
        packet(0x46,{0x18});  // Invalidate depth/color CCU before configuration.
        packet(0x46,{0x19});
        idle();
        reg(0x8e04,{0x04100000}); // A640 RB_DBG_ECO_CNTL (also its blit value).
        reg(0x8e01,{1});          // RB_RBP_CNTL.
        // Two CCUs, 64 KiB depth cache each: color offset = 128 KiB, full cache.
        reg(0x8e07,{0x10000000});
        reg(0x8c01,{0}); // Pixel blending disabled.
        reg(0x8c00,{0x00f03080}); // RGBA8 UNORM, solid color, all channels.
        reg(0x8400,{0x00f03080});
        reg(0xacc0,{0x0000f180}); // SP float output, format 0x30, all channels.
        reg(0x8c17,{0x30,uint32_t(target),uint32_t(target>>32),2}); // 128-byte pitch.
        reg(0x8c20,{0,0,0}); // Linear image; no UBWC flag buffer.
        const uint32_t colors[4][4]={{255,0,0,255},{0,255,0,255},
                                    {0,0,255,255},{255,255,255,255}};
        for(unsigned quadrant=0;quadrant<4;++quadrant) {
            reg(0x8c2c,colors[quadrant]);
            const uint32_t x=(quadrant&1)*16,y=(quadrant>>1)*8;
            reg(0x8405,{x|(y<<16),(x+15)|((y+7)<<16)});
            packet(0x2c,{3}); // CP_BLIT / BLIT_OP_SCALE, SOLID_COLOR set above.
            idle();
        }
        packet(0x46,{0x1d,uint32_t(event),uint32_t(event>>32),0}); // CCU color flush.
        idle(); // The caller appends and waits for the real CACHE_FLUSH_TS fence.
    }
};
#endif
