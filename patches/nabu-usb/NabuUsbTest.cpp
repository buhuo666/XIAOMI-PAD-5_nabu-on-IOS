// SPDX-License-Identifier: BSD-2-Clause-Patent
#define NABU_USB_HOST_TEST 1
#include "NabuUsbCaptureCdc.cpp"
#include <assert.h>
#include <string.h>

using namespace nabu_usb_capture;
static uint32_t core[0x100000/4], ep0[0x4000/4], bulk[0x4000/4];
static unsigned log_count;
static unsigned starts[32];
static bool ending[32];
static const char capture[] = "immutable boot log\n";
extern "C" uint32_t nabu_usb_test_mmio_read(volatile uint32_t *base, uint32_t off) { assert(off % 4 == 0); return base[off/4]; }
extern "C" void nabu_usb_test_mmio_write(volatile uint32_t *base, uint32_t off, uint32_t value)
{
    assert(off % 4 == 0);
    if (base == core && off >= 0xc80c && off <= 0xc9fc && (off-0xc80c)%16 == 0) {
        unsigned dep=(off-0xc80c)/16;
        value &= ~kDepcmdCmdact;
        if ((value & 15) == kDepcmdEndTransfer) ending[dep]=true;
        if ((value & 15) == kDepcmdStartTransfer) {
            starts[dep]++;
            if (ending[dep]) value |= 1u << 12;
            else value |= 1u << 16;
        }
    }
    base[off/4] = value;
}
extern "C" vm_offset_t ml_io_map(vm_offset_t, vm_size_t) { return 0; }
extern "C" vm_offset_t ml_vtophys(vm_offset_t value) { return value; }
extern "C" void FlushPoC_DcacheRegion(vm_offset_t, unsigned) {}
extern "C" const char *nabu_log_capture_data(void) { return capture; }
extern "C" uint32_t nabu_log_capture_length(void) { return sizeof(capture)-1; }
void IOLog(const char *, ...) { ++log_count; }
void IOSleep(unsigned ms) { if (ms) memset(ending,0,sizeof(ending)); }
int PE_parse_boot_argn(const char *, void *, int) { return 0; }
int kernel_thread_start(void (*)(void *, wait_result_t), void *, thread_t *) { return 1; }
void thread_deallocate(thread_t) {}
thread_t current_thread(void) { return nullptr; }
int thread_terminate(thread_t) { return 0; }

static void setup(uint8_t request_type, uint8_t request, uint16_t value, uint16_t length)
{
    ep0[kEp0SetupBuffer/4] = request_type | (request << 8) | (value << 16);
    ep0[kEp0SetupBuffer/4+1] = (uint32_t)length << 16;
    ep0_setup();
}

int main()
{
    g_regs=core; g_ep0=ep0; g_bulk=bulk; g_ep0_pa=0x12340000; g_bulk_pa=0x12344000;
    assert(kDeviceDesc[4]==2 && kDeviceDesc[5]==2 && kDeviceDesc[6]==1);
    assert(kConfigDesc[2]==sizeof(kConfigDesc) && kConfigDesc[4]==2);
    ep0_arm_setup();
    assert(ep0[0]==g_ep0_pa+kEp0SetupBuffer && ep0[2]==8);
    assert(ep0[3]&kTrbCtrlHwo);
    unsigned setup_starts=starts[0];
    handle_device_event(1u|(kDevEventReset<<8));
    assert(starts[0]==setup_starts && g_ep0_state==kEp0Setup && !g_faulted);
    setup(0x80,6,0x200,255);
    assert(g_ep0_state==kEp0Data && g_ep0_trbs==2);
    assert(ep0[2]==64 && ep0[6]==3);
    assert((ep0[3]&(kTrbCtrlHwo|kTrbCtrlChn))==(kTrbCtrlHwo|kTrbCtrlChn));
    assert((ep0[7]&(kTrbCtrlHwo|kTrbCtrlLst))==(kTrbCtrlHwo|kTrbCtrlLst));
    assert(!(ep0[7]&kTrbCtrlChn));
    assert(memcmp((const void *)((uint8_t*)ep0+kEp0Stage),kConfigDesc,sizeof(kConfigDesc))==0);
    // A real SETUP_PENDING completion lives in TRB word 2 (byte offset 8).
    ep0[6]=kTrbstsSetupPending<<kTrbSizeTrbstsShift;
    handle_dep_event((1u<<1)|(kDepevtXferComplete<<6));
    assert(g_ep0_state==kEp0Setup && ep0[0]==g_ep0_pa+kEp0SetupBuffer);
    setup(0x21,0x20,0,7);
    assert(g_ep0_data_dep==0 && g_ep0_trbs==2 && ep0[2]==7 && ep0[6]==57);
    setup(0x21,0x22,3,0);
    assert(g_ep0_state==kEp0WaitStatus);
    handle_dep_event((1u<<1)|(kDepevtXferNotReady<<6)|(kDepevtStatusControlStatus<<12));
    assert(g_ep0_state==kEp0Status);
    handle_dep_event((1u<<1)|(kDepevtXferComplete<<6));
    assert(g_ep0_state==kEp0Setup);
    setup(0,9,1,0);
    assert(g_configured==1 && g_bulk_enabled);
    g_dtr=false;
    bulk_pump();
    assert(!g_bulk_busy && g_log_cursor==0);
    setup(0x21,0x22,3,0);
    bulk_pump();
    assert(g_bulk_busy && g_bulk_len==sizeof(capture)-1);
    assert(memcmp((uint8_t*)bulk+kBulkStage,capture,sizeof(capture)-1)==0);
    bulk[2]=0;
    unsigned prior=log_count;
    bulk_complete();
    assert(!g_bulk_busy && g_log_cursor==sizeof(capture)-1 && log_count==prior);
    setup(0x21,0x22,0,0);
    assert(!g_dtr);
    bulk_pump();
    assert(!g_bulk_busy);
    setup(0x21,0x22,3,0);
    assert(g_dtr && g_log_cursor==0);
    bulk_pump();
    assert(g_bulk_busy && !memcmp((uint8_t*)bulk+kBulkStage,capture,sizeof(capture)-1));
    uint8_t out[32];
    assert(!nabuUsbLogCopy(sizeof(capture),1,out));
    assert(!nabuUsbLogCopy(sizeof(capture)-1,1,out));
    assert(nabuUsbLogCopy(0,sizeof(capture)-1,out));
    // Reset returns endpoints to unconfigured state and re-arms setup.
    handle_device_event(1u|(kDevEventReset<<8));
    assert(!g_configured && !g_bulk_enabled && g_ep0_state==kEp0Setup && !g_faulted);
    // Restart after END must wait for the controller to release the resource.
    ep_end_transfer(0,0);
    assert(!ending[0]);
    ep0_arm_setup();
    assert(!g_faulted);

    using namespace nabu_usb::smmu;
    static uint32_t smmu[kWindow/4];
    auto read=[](uint32_t offset){return smmu[offset/4];};
    smmu[kIdr0/4]=kIdr0Sms|94|(15<<kIdr0NumsidbShift);
    smmu[kIdr1/4]=56|(5<<kIdr1NumpagendxbShift);
    smmu[kIdr2/4]=kIdr2Ptfs4k;
    Info info; assert(read_info(read,&info));
    // Retain the existing UFS stream and its context, allocate only USB.
    smmu[kSmrBase/4]=kSmrValid|0x300;
    smmu[kS2crBase/4]=1;
    smmu[context_offset(info.global_pages,1)/4]=0x009700e0;
    smmu[(kCbarBase+4)/4]=0x1f000;
    smmu[(kCba2rBase+4)/4]=1;
    Plan p=plan_bypass(read,info,0x140);
    assert(p.valid && !p.reuse && p.index==1 && p.bank!=1);
    auto write=[](uint32_t offset,uint32_t value){smmu[offset/4]=value;};
    assert(configure_bypass(read,write,p,0x140));
    assert(smmu[kSmrBase/4]==(kSmrValid|0x300) && smmu[kS2crBase/4]==1);
    p=plan_bypass(read,info,0x140); assert(p.valid && p.reuse);
    smmu[context_offset(info.global_pages,p.bank)/4]|=1;
    assert(!plan_bypass(read,info,0x140).valid);
    puts("USB host checks passed: Windows class, EP0 DMA separation, 67-byte descriptor chain, setup-pending, CDC control, log transfer, reset and isolated SMMU route.");
    return 0;
}
