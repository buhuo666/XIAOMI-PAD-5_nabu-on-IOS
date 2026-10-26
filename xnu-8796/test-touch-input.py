#!/usr/bin/env python3
"""Compile the real nabu touch helpers and protocol with a fake SPI transport."""
import argparse
from pathlib import Path
import subprocess
import tempfile

HARNESS = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "nabu_touch_input.h"
static struct {int slot,down,x,y;} events[64];
static unsigned emitted;
static void emit(int s,int d,int x,int y) {
    assert(emitted<64); events[emitted].slot=s; events[emitted].down=d;
    events[emitted].x=x;events[emitted++].y=y;
}
static uint8_t packet[NVT_POINT_DATA_LEN];
static int fail_read;
struct scan_model {
    uint32_t page;
    unsigned commands, delays, fail_command, never_ack;
    uint8_t command[16];
    uint16_t value[16];
};
static int transfer(void *ctx,const uint8_t *tx,uint8_t *rx,size_t n) {
    (void)ctx; assert(tx && n);
    if(tx[0]==0xff && n==3 && !rx) return 0;
    if(fail_read) return fail_read;
    if(rx) {
        memset(rx,0,n);
        if(n==NVT_POINT_DATA_LEN+2) memcpy(rx+2,packet,sizeof(packet));
    }
    return 0;
}
static int scan_transfer(void *ctx,const uint8_t *tx,uint8_t *rx,size_t n) {
    struct scan_model *m=ctx;assert(m&&tx&&n);
    if(tx[0]==0xff&&n==3&&!rx) {
        m->page=(uint32_t)tx[1]<<15|(uint32_t)tx[2]<<7;return 0;
    }
    uint32_t address=m->page|(tx[0]&0x7fu);
    if(rx) {
        if(fail_read)return fail_read;
        memset(rx,0,n);
        if(n==3&&address==(NVT_EVENT_BUF_ADDR|0x50u))rx[2]=m->never_ack?1:0;
        if(n==3&&address==(NVT_EVENT_BUF_ADDR|0x60u))rx[2]=0xa1;
    } else if(n==6&&address==(NVT_EVENT_BUF_ADDR|0x50u)) {
        assert(m->commands<16);unsigned i=m->commands++;
        m->command[i]=tx[1];m->value[i]=(uint16_t)(tx[3]|(uint16_t)tx[4]<<8);
        if(m->fail_command==(unsigned)tx[1])return -5;
    } else if(n==3&&address==0x113718u) {
        assert(tx[1]==120&&tx[2]==0);
    }
    return 0;
}
static void scan_delay(void *ctx,unsigned ms) {
    ((struct scan_model *)ctx)->delays+=ms;
}
static void checksum(void) {
    unsigned sum=0; for(unsigned i=0;i<NVT_POINT_DATA_LEN-1;i++) sum+=packet[i];
    packet[NVT_POINT_DATA_LEN-1]=(uint8_t)(0u-sum);
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
    struct scan_model model={0};
    struct nvt_bus scan_bus={.ctx=&model,.xfer=scan_transfer,.delay_ms=scan_delay};
    struct nvt_scan_diag scan;
    assert(!nvt_start_scanning(&scan_bus,&scan)&&scan.stage==9&&scan.reset_state==0xa1);
    assert(model.commands==2&&model.command[0]==0x19&&model.value[0]==0);
    assert(model.command[1]==0x01&&model.value[1]==2);
    model=(struct scan_model){.fail_command=0x19};
    assert(nvt_start_scanning(&scan_bus,&scan)==-5&&scan.stage==2);
    model=(struct scan_model){.never_ack=1};
    assert(nvt_start_scanning(&scan_bus,&scan)==-1&&scan.stage==4&&scan.status==1);
    model=(struct scan_model){0};
    fail_read=-110;assert(nvt_start_scanning(&scan_bus,&scan)==-110&&scan.stage==3);fail_read=0;
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
    assert "nvt_start_scanning(&ts.bus, &scan)" in touch
    assert "NABU TOUCH: scan result=" in touch
    assert "ts.clock_level" in touch and "nbu_touch_xo_level(levels)" in touch
    assert "ts.east = ml_io_map(NBU_TOUCH_EAST_PA" in touch
    assert "ts.north = ml_io_map(NBU_TOUCH_NORTH_PA" in touch
    assert "nbu_sleep_ms(10)" in touch and "i < 100;" not in touch
    assert "nabu_rpmh_vreg_enable" not in touch and "nbu_pin(90" not in touch
    assert "nbu_touch_normalize(x, fLogicalW)" in hid
    assert "fLogicalW = NBU_TOUCH_WIDTH" in hid
    assert not any(old in hid for old in ("1125", "2436", "1079", "2399", "68 << 16", "151 << 16"))
    with tempfile.TemporaryDirectory(prefix="nabu-touch-") as tmp:
        out = Path(tmp)
        (out / "sys").mkdir()
        (out / "sys/systm.h").write_text("#include <string.h>\n")
        (out / "touch.c").write_text(HARNESS)
        exe = out / "touch-test"
        subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                        "-I", str(dev), "-I", str(out),
                        str(dev / "nabu_nt36523.c"), str(out / "touch.c"),
                        "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
