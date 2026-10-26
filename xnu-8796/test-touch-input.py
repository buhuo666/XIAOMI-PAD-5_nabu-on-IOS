#!/usr/bin/env python3
"""Compile the real nabu touch helpers and protocol with a fake SPI transport."""
import argparse
from pathlib import Path
import subprocess
import tempfile

HARNESS = r"""
#include <assert.h>
#include <stdbool.h>
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "nabu_touch_input.h"
typedef uintptr_t vm_offset_t;
static struct {int slot,down,x,y;} events[64];
static unsigned emitted;
static void emit(int s,int d,int x,int y) {
    assert(emitted<64); events[emitted].slot=s; events[emitted].down=d;
    events[emitted].x=x;events[emitted++].y=y;
}
static uint8_t packet[NVT_POINT_DATA_LEN];
static int fail_read;
static unsigned polling_mode, polling_reads, polling_ms, first_down_ms;
static unsigned polling_abort_ms;
static uint32_t irq_mock_cfg=1u, irq_mock_status;
static unsigned irq_poll_active, irq_status_consumed_ms=UINT32_MAX;
static jmp_buf polling_abort;
static int transfer(void *ctx,const uint8_t *tx,uint8_t *rx,size_t n) {
    (void)ctx; assert(tx && n);
    if(tx[0]==0xff && n==3 && !rx) return 0;
    if(fail_read) return fail_read;
    if(rx) {
        memset(rx,0,n);
        if(n==NVT_POINT_DATA_LEN+2) {
            if (!polling_mode) {
                memcpy(rx+2,packet,sizeof(packet));
            } else {
                polling_reads++;
                if (polling_mode==1 &&
                    (polling_ms==500 || polling_ms==510)) {
                    rx[2]=9;rx[3]=50;rx[4]=62;
                    rx[5]=polling_ms==500?8:0xa8;rx[6]=1;rx[7]=1;
                    unsigned sum=0;
                    for(unsigned i=2;i<n-1;i++)sum+=rx[i];
                    rx[n-1]=(uint8_t)(0u-sum);
                } else if (polling_mode==1 && polling_ms==520) {
                    memset(rx+2,0xff,NVT_POINT_DATA_LEN-1);
                    unsigned sum=0;
                    for(unsigned i=2;i<n-1;i++)sum+=rx[i];
                    rx[n-1]=(uint8_t)(0u-sum);
                } else if (polling_mode==3 && polling_ms==0) {
                    rx[2]=9;rx[3]=50;rx[4]=62;rx[5]=8;rx[6]=1;rx[7]=1;
                    unsigned sum=0;
                    for(unsigned i=2;i<n-1;i++)sum+=rx[i];
                    rx[n-1]=(uint8_t)(0u-sum);
                } else if (polling_mode==3 && polling_ms<30000) {
                    memset(rx+2,0xff,NVT_POINT_DATA_LEN);
                    rx[n-1]=0x1b;
                } else {
                    memset(rx+2,0xff,NVT_POINT_DATA_LEN);
                    rx[n-1]=0x1b; /* Synthetic startup frame with bad checksum. */
                }
            }
        }
        if(polling_mode && n==7 && tx[0]==0x60)
            rx[2]=polling_ms<500?0xa1:0xa3;
    }
    return 0;
}
static void checksum(void) {
    unsigned sum=0; for(unsigned i=0;i<NVT_POINT_DATA_LEN-1;i++) sum+=packet[i];
    packet[NVT_POINT_DATA_LEN-1]=(uint8_t)(0u-sum);
}

/* Compile the actual GPIO39 edge-latch and poll path with fake MMIO/SPI.
 * Replays narrow rising edges that are absent from sampled input levels. */
#define NSEC_PER_MSEC 1000000u
#define NABU_TOUCH_IRQ_GPIO 39u
#define NABU_TLMM_GPIO(pin) ((uint32_t)(pin)*0x1000u)
#define NABU_TLMM_IO(pin) ((uint32_t)(pin)*0x1000u+4u)
#define NABU_TLMM_INTR_CFG(pin) ((uint32_t)(pin)*0x1000u+8u)
#define NABU_TLMM_INTR_STATUS(pin) ((uint32_t)(pin)*0x1000u+12u)
#define NABU_TLMM_INTR_ENABLE       (1u << 0)
#define NABU_TLMM_INTR_POLARITY     (1u << 1)
#define NABU_TLMM_INTR_DETECTION    (3u << 2)
#define NABU_TLMM_INTR_RAW_STATUS   (1u << 4)
#define NABU_TLMM_INTR_TARGET       (7u << 5)
#define NABU_TLMM_INTR_TARGET_APPS  (3u << 5)
#define NABU_TLMM_INTR_EDGE_RISING  (1u << 2)
static struct {
    struct nvt_bus bus;
    struct nbu_touch_slots slots;
    uintptr_t north;
    struct {
        unsigned last_pio_irq, last_pio_status, last_pio_rx_status;
        size_t last_pio_tx_bytes, last_pio_rx_bytes;
    } spi;
} ts;
static uint64_t mach_absolute_time(void) {return polling_ms;}
static void clock_interval_to_deadline(unsigned ms,unsigned scale,uint64_t *out) {
    assert(scale==NSEC_PER_MSEC);*out=(uint64_t)polling_ms+ms;
}
static void nbu_sleep_ms(unsigned ms) {
    assert(ms==1);polling_ms+=ms;
    if (polling_abort_ms && polling_ms>=polling_abort_ms)
        longjmp(polling_abort,1);
    assert(polling_ms<=31000); /* No unbounded wait on a broken controller. */
}
static uint32_t nbu_rd(uintptr_t base,uint32_t off) {
    assert(base==1);
    if(off==NABU_TLMM_INTR_CFG(NABU_TOUCH_IRQ_GPIO)) return irq_mock_cfg;
    if(off==NABU_TLMM_INTR_STATUS(NABU_TOUCH_IRQ_GPIO)) {
        if (irq_poll_active) {
            bool event = (polling_mode==1 &&
                          (polling_ms==500 || polling_ms==510 || polling_ms==520)) ||
                         (polling_mode==3 && polling_ms%10==0 &&
                          irq_status_consumed_ms!=polling_ms);
            if(event) irq_mock_status|=1u;
        }
        return irq_mock_status;
    }
    if(off==NABU_TLMM_IO(NABU_TOUCH_IRQ_GPIO)) return 0; /* Edge is narrower than the sampling interval. */
    assert(!"unexpected GPIO register read");
    return 0;
}
static void nbu_wr(uintptr_t base,uint32_t off,uint32_t value) {
    assert(base==1);
    if(off==NABU_TLMM_INTR_STATUS(NABU_TOUCH_IRQ_GPIO)) {
        /* The real SM8150 GPIO interrupt status is write-zero-to-clear. */
        irq_mock_status &= value;
        irq_status_consumed_ms=polling_ms;
        return;
    }
    if(off==NABU_TLMM_INTR_CFG(NABU_TOUCH_IRQ_GPIO)) {
        irq_mock_cfg=value;
        irq_poll_active=1;
        irq_status_consumed_ms=UINT32_MAX;
        return;
    }
    assert(!"unexpected GPIO register write");
}
static void nabu_hid_touch(int slot,int down,int x,int y) {
    if(down && first_down_ms==UINT32_MAX) first_down_ms=polling_ms;
    emit(slot,down,x,y);
}
static int polling_log(const char *format,...) {(void)format;return 0;}
#define printf polling_log
/* ACTUAL_IRQ_AND_POLLING */
#undef printf

static void replay_polling(unsigned mode) {
    memset(&ts,0,sizeof(ts));ts.north=1;ts.bus.xfer=transfer;
    polling_mode=mode;polling_reads=polling_ms=emitted=0;
    first_down_ms=UINT32_MAX;polling_abort_ms=0;
    irq_mock_cfg=1u;irq_mock_status=0;irq_poll_active=0;
    irq_status_consumed_ms=UINT32_MAX;
    const uint32_t expected_irq_cfg = NABU_TLMM_INTR_POLARITY |
        NABU_TLMM_INTR_EDGE_RISING | NABU_TLMM_INTR_RAW_STATUS |
        NABU_TLMM_INTR_TARGET_APPS;
    if(mode==1) {
        polling_abort_ms=1000;
        if(setjmp(polling_abort)==0) nbu_poll_points();
        polling_abort_ms=0;
        assert(polling_reads==3 && first_down_ms==500 && emitted==3);
        assert(events[0].down && events[0].x==800 && events[0].y==1000);
        assert(events[1].down && events[1].x==810 && events[1].y==1000);
        assert(!events[2].down);
        assert(ts.slots.active==0 && polling_ms==1000);
    } else if(mode==2) {
        nbu_poll_points();
        assert(polling_reads==0 && emitted==0 && polling_ms==30000);
    } else {
        nbu_poll_points();
        assert(polling_reads==33 && first_down_ms==0 && emitted==2);
        assert(!events[1].down && ts.slots.active==0 && polling_ms==320);
    }
    assert((irq_mock_cfg & (NABU_TLMM_INTR_ENABLE |
        NABU_TLMM_INTR_POLARITY | NABU_TLMM_INTR_DETECTION |
        NABU_TLMM_INTR_RAW_STATUS | NABU_TLMM_INTR_TARGET)) == expected_irq_cfg);
    assert(irq_mock_status==0); /* Every latched test edge was acknowledged. */
    polling_mode=0;polling_abort_ms=0;
}
int main(void) {
    assert(NBU_TOUCH_EAST_PA==0x03500000u && NBU_TOUCH_NORTH_PA==0x03900000u);
    assert(NBU_TOUCH_EAST_SIZE>26u*0x1000u+4u);
    assert(NBU_TOUCH_NORTH_SIZE>39u*0x1000u+4u);
    assert(nbu_touch_pin_mux(23)==2 && nbu_touch_pin_mux(24)==3);
    assert(nbu_touch_pin_mux(25)==3 && nbu_touch_pin_mux(26)==2);
    assert(nbu_touch_branch_ready(NBU_TOUCH_S_AHB,0x80000002,NBU_TOUCH_VOTES));
    assert(!nbu_touch_branch_ready(NBU_TOUCH_S_AHB,0x80000000,NBU_TOUCH_VOTES));
    assert(!nbu_touch_branch_ready(NBU_TOUCH_S_AHB,0x80000002,0));
    assert(!nbu_touch_branch_ready(NBU_TOUCH_M_AHB,0x80000002,NBU_TOUCH_VOTES));
    assert(nbu_touch_branch_ready(NBU_TOUCH_M_AHB,0,NBU_TOUCH_VOTES));
    assert(nbu_touch_branch_ready(NBU_TOUCH_SE_HALT,0x4220,NBU_TOUCH_VOTES));
    assert(!nbu_touch_branch_ready(0x123,0,NBU_TOUCH_VOTES));
    uint32_t levels[8]; for(unsigned i=0;i<8;i++)levels[i]=0x106;
    assert(nbu_touch_xo_level(levels)==-1);
    levels[3]=0x100001; assert(nbu_touch_xo_level(levels)==3);
    assert(nbu_touch_normalize(0,1600)==0);
    assert(nbu_touch_normalize(-10,1600)==0);
    assert(nbu_touch_normalize(1599,1600)==65536);
    assert(nbu_touch_normalize(2559,2560)==65536);
    assert(nbu_touch_normalize(9999,1600)==65536);
    assert(nbu_touch_normalize(800,1600)>32768);
    assert(nbu_touch_normalize(0,0)==0);

    struct nbu_touch_slots s={0};
    struct nvt_contact p[2]={{.id=1,.down=1,.x=1599,.y=2559},
                            {.id=10,.down=1,.x=10,.y=20}};
    assert(!nbu_touch_publish(&s,p,2,emit) && s.active==0x201 && emitted==2);
    assert(events[0].slot==0 && events[1].slot==9);
    emitted=0; p[0].x=800;
    assert(!nbu_touch_publish(&s,p,1,emit) && s.active==1 && emitted==2);
    assert(events[0].slot==9 && !events[0].down);
    assert(events[1].slot==0 && events[1].x==800);
    emitted=0; p[1]=p[0];
    assert(nbu_touch_publish(&s,p,2,emit)==-1 && emitted==0 && s.active==1);
    p[0].id=0; assert(nbu_touch_publish(&s,p,1,emit)==-1);
    p[0].id=1;p[0].x=1600; assert(nbu_touch_publish(&s,p,1,emit)==-1);
    nbu_touch_release(&s,emit);assert(s.active==0 && emitted==1 && !events[0].down);
    nbu_touch_release(&s,emit);assert(emitted==1);

    struct nvt_bus bus={.xfer=transfer};
    uint8_t raw[NVT_POINT_DATA_LEN], big[257];
    struct nvt_frame_diag diag;
    packet[0]=(1u<<3)|1; packet[1]=99;packet[2]=159;packet[3]=0xff;
    packet[4]=1;packet[5]=1;checksum();
    assert(!nvt_read_point_frame_diag(&bus,raw,&diag) && diag.stage==5);
    assert(nvt_parse_points(raw,1600,2560,p,2)==1 && p[0].x==1599 && p[0].y==2559);
    raw[1]=100;raw[3]=0x0f; assert(nvt_parse_points(raw,1600,2560,p,2)==0);
    packet[10]^=1;
    assert(nvt_read_point_frame_diag(&bus,raw,&diag)==-1 && diag.stage==3);
    assert(diag.checksum_expected!=diag.checksum_observed);
    packet[10]^=1;
    memset(packet,0,sizeof(packet));checksum();assert(!nvt_read_point_frame(&bus,raw));
    for(unsigned i=0;i<6;i++){packet[i]=0x77;} checksum();
    assert(nvt_read_point_frame(&bus,raw)==-1);
    for(unsigned i=0;i<6;i++){packet[i]=0xfd;} checksum();
    assert(nvt_read_point_frame(&bus,raw)==-1);
    fail_read=-110;
    assert(nvt_read_point_frame_diag(&bus,raw,&diag)==-110 && diag.stage==2);
    assert(diag.transfer_status==-110);fail_read=0;
    assert(nvt_read_addr(&bus,0,big,sizeof(big))==-1);
    assert(nvt_write_addr(&bus,0,big,sizeof(big))==-1);
    uint8_t fw[39]={0};struct nvt_info info;
    fw[0]=1;fw[1]=254;fw[4]=6;fw[5]=64;fw[6]=10;fw[7]=0;
    assert(!nvt_parse_fwinfo(fw,sizeof(fw),&info)&&info.valid&&info.max_x==1600&&info.max_y==2560);
    replay_polling(1);replay_polling(2);replay_polling(3);
    puts("Actual GPIO39 edge-latch gated loop replay passed: sub-sample rising edges reach SPI/HID; no edge performs zero point reads; bad frames release contacts.");
    puts("Actual touch helpers passed: SM8150 HWCG/votes/tiles/mux, native coordinates, HID slots/releases, checksum/recovery, bounded stack buffers.");
    return 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xnu-source", type=Path, required=True)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    source = args.xnu_source.resolve()
    dev = source / "bsd/dev"
    touch = (dev / "nabu_touch.c").read_text(encoding="utf-8")
    hid = (source / "iokit/Kernel/arm/hid/NabuHID.cpp").read_text(encoding="utf-8")
    assert "nbu_touch_branch_ready(branches[i].off, v," in touch
    assert "publish_status = nbu_touch_publish(&ts.slots, contacts, n," in touch
    assert "nbu_touch_release(&ts.slots, nabu_hid_touch)" in touch
    assert "nvt_read_point_frame_diag(&ts.bus, frame, &diag)" in touch
    assert "parsed=%d publish=%d" in touch
    assert "first-frame-data=%s" in touch
    geni = (source / "bsd/dev/nabu_geni_spi.c").read_text(encoding="utf-8")
    assert "last_pio_irq |= st" in geni
    assert "last_pio_rx_bytes = len - x.rx_rem" in geni
    assert "nvt_read_point_frame_diag(&ts.bus, frame, &diag)" in touch
    assert "last_pio_irq" in touch and "last_pio_rx_bytes" in touch
    assert "if (nbu_probe_chip() || nbu_upload_firmware()) {\n\t\tnbu_poll_points();\n\t}" in touch
    assert "nvt_start_scanning" not in touch
    irq_start = touch.index("static bool\nnbu_touch_irq_prepare(void)\n")
    irq_end = touch.index("\nstatic uint32_t\nnbu_se_rd(", irq_start)
    poll_start = touch.index("static void\nnbu_poll_points(void)\n")
    poll_end = touch.index("\nstatic void\nnbu_touch_thread(", poll_start)
    polling_loop = touch[poll_start:poll_end]
    irq_helpers = touch[irq_start:irq_end]
    assert "NABU_TLMM_INTR_STATUS(NABU_TOUCH_IRQ_GPIO)" in touch
    assert "NABU_TLMM_INTR_EDGE_RISING" in touch
    assert "NABU_TLMM_INTR_RAW_STATUS" in touch
    assert "parent=masked" in touch
    assert "return (observed & mask) == (cfg & mask)" in touch
    assert "nbu_touch_irq_take()" in polling_loop
    assert "irq_consumed" not in polling_loop
    harness = HARNESS.replace("/* ACTUAL_IRQ_AND_POLLING */",
                              irq_helpers + polling_loop)
    assert "ts.clock_level" in touch and "nbu_touch_xo_level(levels)" in touch
    assert "ts.east = ml_io_map(NBU_TOUCH_EAST_PA" in touch
    assert "ts.north = ml_io_map(NBU_TOUCH_NORTH_PA" in touch
    assert "bool frame_ready = nbu_touch_irq_take();" in polling_loop
    assert "if (!frame_ready)" in touch
    assert "nbu_sleep_ms(1)" in touch and "i < 100;" not in touch
    assert "nabu_rpmh_vreg_enable" not in touch and "nbu_pin(90" not in touch
    assert "nbu_touch_normalize(x, fLogicalW)" in hid
    assert "fLogicalW = NBU_TOUCH_WIDTH" in hid
    assert not any(old in hid for old in ("1125", "2436", "1079", "2399", "68 << 16", "151 << 16"))
    with tempfile.TemporaryDirectory(prefix="nabu-touch-") as tmp:
        out = Path(tmp)
        (out / "sys").mkdir()
        (out / "sys/systm.h").write_text("#include <string.h>\n")
        (out / "touch.c").write_text(harness)
        exe = out / "touch-test"
        subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                        "-I", str(dev), "-I", str(out),
                        str(dev / "nabu_nt36523.c"), str(out / "touch.c"),
                        "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
