#!/usr/bin/env python3
"""Test the actual NT36523 RAM-download implementation against a bus model."""
import argparse
from pathlib import Path
import subprocess
import tempfile

HARNESS = r"""
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "nabu_touch_firmware.h"
static uint8_t memory[0x40000];
static unsigned page, writes, delays, fail_io, corrupt_read, never_ready, bad_crc;
static unsigned initialized_crc_values_differ, missing_crc_done;
static void put(uint8_t *p,uint32_t x) {
    for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(x>>(8*i));
}
static void wait_ms(void *ctx,unsigned ms) {(void)ctx;delays+=ms;}
static int transfer(void *ctx,const uint8_t *tx,uint8_t *rx,size_t n) {
    (void)ctx;
    if(fail_io)return -1;
    if(!rx&&n==3&&tx[0]==0xff){page=(unsigned)tx[1]<<15|(unsigned)tx[2]<<7;return 0;}
    unsigned address=page|(tx[0]&127u);
    if(rx) {
        assert(n>=2&&address+n-2<=sizeof(memory));
        memset(rx,0,n);memcpy(rx+2,memory+address,n-2);
        if(corrupt_read&&address==0&&n>2)rx[2]^=1;
    } else {
        assert(tx[0]&0x80);assert(address+n-1<=sizeof(memory));writes++;
        if(address>=NBU_FW_SRAM_END) {
            assert((address==0x3f0fe&&n==2&&tx[1]==0x69) ||
                   (address==0x3f310&&n==2&&tx[1]==0) ||
                   (address==0x3f128&&n==4)||(address==0x3f12c&&n==4)||
                   (address==0x3f118&&n==4)||(address==0x3f130&&n==4)||
                   (address==0x3f100&&n==5)||(address==0x3f104&&n==5)||
                   (address==0x3f7e8&&n==2&&tx[1]==0x69)||
                   (address==0x3f30e&&n==2)||(address==0x3f10d&&n==2&&tx[1]==1));
        }
        memcpy(memory+address,tx+1,n-1);
        if(address==0x3f10d&&tx[1]==1) {
            if(!never_ready)memory[NBU_FW_EVENT|0x60]=0xa1;
            memory[0x3f133]=bad_crc?7:missing_crc_done?0:4;
            memcpy(memory+0x3f120,memory+0x3f100,8);
            if(initialized_crc_values_differ)memory[0x3f120]^=0x5a;
        }
    }
    return 0;
}
static void reset(void) {
    memset(memory,0,sizeof(memory));page=writes=delays=fail_io=corrupt_read=never_ready=bad_crc=0;
    initialized_crc_values_differ=missing_crc_done=0;
}
static void exercise(const uint8_t *image,size_t length) {
    struct nbu_firmware fw;struct nbu_fw_result result;
    struct nvt_bus bus={.xfer=transfer,.delay_ms=wait_ms};
    assert(!nbu_fw_parse(image,length,&fw));
    reset();assert(!nbu_fw_download(&bus,&fw,&result));assert(result.stage==10);
    unsigned bytes=0;
    for(unsigned i=0;i<fw.count;i++)if(fw.part[i].size) {
        struct nbu_fw_part *p=&fw.part[i];bytes+=p->size+1;
        assert(!memcmp(memory+p->ram,image+p->bin,p->size+1));
    }
    assert(result.written==bytes&&result.verified==bytes);
    reset();fail_io=1;assert(nbu_fw_download(&bus,&fw,&result)==-1&&result.stage==1);
    reset();corrupt_read=1;assert(nbu_fw_download(&bus,&fw,&result)==-1&&result.stage==6);
    reset();never_ready=1;assert(nbu_fw_download(&bus,&fw,&result)==-1&&result.stage==8);
    assert(delays>=5000&&delays<=5010);
    reset();bad_crc=1;assert(nbu_fw_download(&bus,&fw,&result)==-1&&result.stage==9);
    assert(result.crc_flag==7&&result.reset_state==0xa1);
    reset();missing_crc_done=1;
    assert(nbu_fw_download(&bus,&fw,&result)==-1&&result.stage==9&&result.crc_flag==0);
    reset();initialized_crc_values_differ=1;
    assert(!nbu_fw_download(&bus,&fw,&result)&&result.stage==10);
    assert(result.crc_flag==4&&result.reset_state==0xa1&&!result.crc_values_match);
    assert(result.crc_expected[0]==fw.part[0].crc);
    assert(result.crc_result[0]==(fw.part[0].crc^0x5a));
    assert(result.written==bytes&&result.verified==bytes);
    printf("RAM download model: version=%u parts=%u cascade=%u transferred=%u; readback, timeout and CRC failures enforced.\n",
           fw.version,fw.count,fw.cascade,bytes);
}
int main(int argc,char **argv) {
    uint8_t image[8192]={0};struct nbu_firmware fw;
    put(image,0x40);put(image+4,0);put(image+8,15);
    put(image+12,0x200);put(image+16,0x20000);put(image+20,15);
    put(image+24,0x12345678);put(image+28,0x98765432);
    image[4096]=0x12;image[4097]=0xed;memcpy(image+8192-3,"NVT",3);
    for(unsigned i=0;i<16;i++){image[0x40+i]=(uint8_t)(i+1);image[0x200+i]=(uint8_t)(99-i);}
    exercise(image,sizeof(image));
    put(image+16,0x3f000);assert(nbu_fw_parse(image,sizeof(image),&fw)==-1);
    put(image+16,0);assert(nbu_fw_parse(image,sizeof(image),&fw)==-1);
    put(image+16,0x20000);put(image+12,0xfffffff0);assert(nbu_fw_parse(image,sizeof(image),&fw)==-1);
    put(image+12,0x200);image[4097]^=1;assert(nbu_fw_parse(image,sizeof(image),&fw)==-1);
    image[4097]^=1;image[8191]=0;assert(nbu_fw_parse(image,sizeof(image),&fw)==-1);
    if(argc==2) {
        FILE *file=fopen(argv[1],"rb");assert(file);assert(!fseek(file,0,SEEK_END));
        long length=ftell(file);assert(length>0&&length<=0x40000);rewind(file);
        uint8_t *data=malloc((size_t)length);assert(data);
        assert(fread(data,1,(size_t)length,file)==(size_t)length);fclose(file);
        exercise(data,(size_t)length);free(data);
    }
    puts("Actual NT36523 firmware parser/download tests passed; bus model only, not physical controller execution.");
    return 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xnu-source", type=Path, required=True)
    parser.add_argument("--cc", default="clang")
    parser.add_argument("--firmware", type=Path)
    args = parser.parse_args()
    dev = args.xnu_source.resolve() / "bsd/dev"
    touch = (dev / "nabu_touch.c").read_text(encoding="utf-8")
    assert 'SecureDTGetProperty(chosen, "nabu-touch-firmware"' in touch
    assert "nbu_probe_chip() || nbu_upload_firmware()" in touch
    assert "fw.version != 0x12u" in touch
    with tempfile.TemporaryDirectory(prefix="nabu-fw-") as tmp:
        out = Path(tmp)
        (out / "sys").mkdir()
        (out / "sys/systm.h").write_text("#include <string.h>\n")
        (out / "test.c").write_text(HARNESS)
        exe = out / "fw-test"
        subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                        "-I", str(dev), "-I", str(out),
                        str(dev / "nabu_nt36523.c"), str(out / "test.c"),
                        "-o", str(exe)], check=True)
        subprocess.run([str(exe)] + ([str(args.firmware.resolve())] if args.firmware else []),
                       check=True)


if __name__ == "__main__":
    main()
