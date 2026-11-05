// Execute the real DWC3 transport against DMA/MMIO and descriptor fixtures.
#include <cstdint>
#include <cstring>
#include <cassert>
#include <cstdlib>
static void *IOMallocAligned(unsigned n, unsigned alignment) { return aligned_alloc(alignment,n); }
using IOReturn = int;
constexpr int kIOReturnSuccess=0, kIOReturnIOError=-1, kIOReturnUnderrun=-2,
    kIOReturnOverrun=-3, kIOReturnAborted=-4, kIOReturnBadArgument=-5,
    kIOReturnUnsupported=-6, kIOReturnNotReady=-7, kIOReturnNoMemory=-8;
static bool ordinary_buffer(const void *, unsigned);
class IOMemoryDescriptor {
public:
    uint8_t data[65536] = {};
    unsigned wireCount = 0, prepares = 0, completes = 0;
    bool requiresPreparation = false, failRead = false;
    IOReturn prepareResult = kIOReturnSuccess;
    IOReturn prepare()
    { ++prepares; if (!prepareResult) ++wireCount; return prepareResult; }
    IOReturn complete()
    { assert(wireCount); --wireCount; ++completes; return kIOReturnSuccess; }
    unsigned readBytes(unsigned off, void *dst, unsigned n)
    { assert(!requiresPreparation || wireCount); assert(off+n<=sizeof(data) && ordinary_buffer(dst,n));
      if (failRead) { failRead=false; return 0; } memcpy(dst,data+off,n); return n; }
    unsigned writeBytes(unsigned off, const void *src, unsigned n)
    { assert(!requiresPreparation || wireCount); assert(off+n<=sizeof(data) && ordinary_buffer(src,n)); memcpy(data+off,src,n); return n; }
};
#define NABU_USB_NATIVE_SERVICE 1
#define main cdc_regression_main
#include "NabuUsbTest.cpp"
#undef main

static bool ordinary_buffer(const void *pointer, unsigned length)
{
    const uintptr_t p=reinterpret_cast<uintptr_t>(pointer);
    auto overlaps=[&](const volatile void *page) {
        const uintptr_t base=reinterpret_cast<uintptr_t>(page);
        return base && p<base+16384 && base<p+length;
    };
    if (overlaps(g_ep0)) return false;
    for (unsigned dep=2;dep<g_native_endpoint_count;++dep)
        if (overlaps(g_native_eps[dep].dma)) return false;
    return true;
}

struct Completion { void *cookie; IOReturn status; uint32_t remaining; } completions[64];
static unsigned completed, controlOut, controlOutLength, resetCount;
static unsigned cableConnects, cableDisconnects;
static IOMemoryDescriptor payload, controlReply;
static unsigned setupMode;
static bool reenter;
static bool reenterStall;
static bool reenumerateOnStatus;
static int powerPresent=-1;
extern "C" int nabu_power_usb_present() { return powerPresent; }
extern "C" bool nabu_native_usb_create_controller() { return true; }
extern "C" void nabu_native_usb_poll(void(*p)()) { p(); }
extern "C" void nabu_native_usb_setup(const void*)
{
    if (setupMode==1) assert(nabu_dwc3_submit(0x80,&controlReply,67,(void*)101)==0);
    if (setupMode==2) assert(nabu_dwc3_submit(0x80,&controlReply,0,(void*)102)==0);
    if (setupMode==3) assert(nabu_dwc3_submit(0x80,&controlReply,82,(void*)104)==0);
}
extern "C" void nabu_native_usb_out_data(const void *p,uint32_t n)
{
    ++controlOut;controlOutLength=n;
    if (n) { assert(p && ordinary_buffer(p,n) && !memcmp(p,"1234567",n)); assert(nabu_dwc3_submit(0x80,&controlReply,0,(void*)103)==0); }
    if (!n && reenumerateOnStatus) {
        reenumerateOnStatus=false;
        assert(nabu_dwc3_set_active(false));
        assert(nabu_dwc3_set_active(true));
    }
}
extern "C" void nabu_native_usb_bus_reset() { ++resetCount; }
extern "C" void nabu_native_usb_abort_control() {
    nabu_dwc3_abort_endpoint(0x80);
    if (reenterStall) { reenterStall=false; nabu_dwc3_stall_endpoint(0,true); }
}
extern "C" void nabu_native_usb_connected() { ++cableConnects; }
extern "C" void nabu_native_usb_disconnected() { ++cableDisconnects; }
extern "C" void nabu_native_usb_transfer_done(void *cookie,IOReturn status,uint32_t remaining)
{
    assert(completed<64);completions[completed++]={cookie,status,remaining};
    if (reenter) { reenter=false; assert(!payload.wireCount); assert(nabu_dwc3_submit(0x81,&payload,17,(void*)77)==0); }
}
static void finish(unsigned dep,unsigned remaining)
{
    g_native_eps[dep].dma[2]=remaining;
    handle_dep_event((dep<<1)|(kDepevtXferComplete<<6));
}
int main()
{
    cdc_regression_main();
    g_native_mode=true;g_native_endpoint_count=8;g_native_connected=true;
    alignas(16384) static uint8_t pages[8][16384];
    for(unsigned dep=2;dep<8;++dep) {
        g_native_dma[dep]=pages[dep];
        g_native_eps[dep].dma=(volatile uint32_t*)g_native_dma[dep];
        g_native_eps[dep].pa=0x12380000+dep*16384;
    }
    assert(nabu_dwc3_connection_speed()==2);
    assert(nabu_dwc3_activate_endpoint(1,kEpTypeBulk,512,0)==0);
    assert(nabu_dwc3_activate_endpoint(0x81,kEpTypeBulk,512,0)==0);
    // Match Mux's initially unwired withAddressRanges descriptor. Reading or
    // writing it before prepare models XNU's "not wired" contract violation.
    payload.requiresPreparation = true;
    for(unsigned i=0;i<sizeof(payload.data);++i) payload.data[i]=(uint8_t)(i*17);
    // An OUT request's rounded DMA tail must never leak into the descriptor.
    assert(nabu_dwc3_submit(1,&payload,513,(void*)1)==0);
    assert(g_native_eps[2].dma[2]==1024);
    memset((uint8_t*)g_native_eps[2].dma+kNativeStage,0x5a,513);
    const auto sentinel=payload.data[513]; finish(2,511);
    assert(completed==1 && !completions[0].remaining && completions[0].status==0);
    assert(payload.prepares==1 && payload.completes==1 && !payload.wireCount);
    assert(payload.data[512]==0x5a && payload.data[513]==sentinel);
    // One logical IN transfer spans multiple DMA pages and ends with a ZLP.
    assert(nabu_dwc3_submit(0x81,&payload,32768,(void*)2)==0);
    unsigned offset=0;
    while(g_native_eps[3].cookie) {
        assert(payload.wireCount==1);
        const unsigned n=g_native_eps[3].chunk;
        assert(!memcmp((uint8_t*)g_native_eps[3].dma+kNativeStage,payload.data+offset,n));
        offset+=n;finish(3,0);
    }
    assert(offset==32768 && completed==2 && completions[1].remaining==0);
    assert(payload.prepares==2 && payload.completes==2 && !payload.wireCount);
    // A short OUT packet ends the request, preserving the unreceived count.
    assert(nabu_dwc3_submit(1,&payload,32768,(void*)3)==0);
    finish(2,0);finish(2,kNativeChunk-7);
    assert(completed==3 && completions[2].remaining==32768-kNativeChunk-7);
    // Completion may re-enter submit. The old request must not overwrite it.
    reenter=true;assert(nabu_dwc3_submit(0x81,&payload,7,(void*)4)==0);finish(3,0);
    assert(g_native_eps[3].cookie==(void*)77);finish(3,0);
    assert(completed==5 && completions[4].cookie==(void*)77);
    assert(nabu_dwc3_submit(1,&payload,1000,(void*)5)==0);
    nabu_dwc3_deactivate_endpoint(1);
    assert(completed==6 && completions[5].status==kIOReturnAborted && completions[5].remaining==1000);
    assert(payload.prepares==payload.completes && !payload.wireCount);
    assert(!(core[kDwc3Dalepena/4]&(1u<<2)));
    assert(nabu_dwc3_submit(1,&payload,1,(void*)6)==kIOReturnNotReady);
    // Native GET_DESCRIPTOR: family owns content; transport owns DATA/STATUS.
    ep_end_transfer(0,0);ep_end_transfer(1,0);setupMode=1;
    for(unsigned i=0;i<67;i++)controlReply.data[i]=(uint8_t)i;
    setup(0x80,6,0x200,255);
    assert(g_ep0_state==kEp0Data && g_ep0_trbs==2);
    ep0[2]=0;ep0[6]=0;handle_dep_event((1<<1)|(kDepevtXferComplete<<6));
    assert(completed==7 && completions[6].cookie==(void*)101 && g_ep0_state==kEp0WaitStatus);
    handle_dep_event((kDepevtXferNotReady<<6)|(kDepevtStatusControlStatus<<12));
    handle_dep_event(kDepevtXferComplete<<6);
    assert(g_ep0_state==kEp0Setup && controlOut==1 && controlOutLength==0);
    // A zero-length IN status request must finish only after host status stage.
    setupMode=2;setup(0,5,5,0);assert(completed==7);
    handle_dep_event((1<<1)|(kDepevtXferNotReady<<6)|(kDepevtStatusControlStatus<<12));
    handle_dep_event((1<<1)|(kDepevtXferComplete<<6));assert(completed==8);
    // Native OUT control data uses the actual received length, excluding padding.
    setupMode=0;setup(0x21,0x20,0,7);memcpy(ep0_stage(),"1234567",7);
    ep0[2]=0;ep0[6]=57;handle_dep_event(kDepevtXferComplete<<6);
    assert(controlOutLength==7 && g_ep0_state==kEp0WaitStatus);
    handle_dep_event((1<<1)|(kDepevtXferNotReady<<6)|(kDepevtStatusControlStatus<<12));
    handle_dep_event((1<<1)|(kDepevtXferComplete<<6));assert(completed==9);
    // Reset keeps an existing pending SETUP, and retires the bulk request once.
    assert(nabu_dwc3_activate_endpoint(1,kEpTypeBulk,512,0)==0);
    assert(nabu_dwc3_submit(1,&payload,1024,(void*)9)==0);
    const unsigned prior=starts[0];handle_device_event(1|(kDevEventReset<<8));
    assert(starts[0]==prior && resetCount==1 && completed==10);
    assert(completions[9].status==kIOReturnAborted && !g_native_eps[2].enabled && !g_faulted);
    setupMode=1;setup(0x80,6,0x200,255);ep0[2]=15u<<kTrbSizeTrbstsShift;reenterStall=true;
    const unsigned beforeStall=starts[0];
    handle_dep_event((1<<1)|(kDepevtXferComplete<<6));
    assert(completed==11 && completions[10].status==kIOReturnAborted && g_ep0_state==kEp0Setup);
    assert(starts[0]==beforeStall+1 && !g_faulted);
    // DeviceFamily stalls both directions; the second hook must not restart
    // the shared EP0 a second time before the next SETUP arrives.
    setupMode=0;setup(0x80,6,0x200,255);
    const unsigned beforeDirections=starts[0];
    nabu_dwc3_stall_endpoint(0x80,true);
    nabu_dwc3_stall_endpoint(0,true);
    assert(starts[0]==beforeDirections+1 && !g_faulted);
    // The stock vendor 0xc0/0x52 status callback can synchronously re-enumerate.
    // Preserve the SETUP transfer armed by goOnBus(true) inside that callback.
    g_native_active=true;core[kDwc3Dctl/4]|=kDctlRunStop;
    setupMode=1;setup(0xc0,0x52,3,67);
    ep0[2]=0;ep0[6]=0;handle_dep_event((1<<1)|(kDepevtXferComplete<<6));
    handle_dep_event((kDepevtXferNotReady<<6)|(kDepevtStatusControlStatus<<12));
    const unsigned beforeReenumeration=starts[0];reenumerateOnStatus=true;
    handle_dep_event(kDepevtXferComplete<<6);
    assert(starts[0]==beforeReenumeration+1 && g_ep0_state==kEp0Setup && !g_faulted);
    assert(deviceSoftResets==1 && resourceAllocated[0] && resourceAllocated[1]);
    // A later cable reconnect must reset the stopped DWC_usb31, acknowledge
    // stale events and rebuild resources without losing diagnostic counters.
    const unsigned beforeReconnect=starts[0], savedSetups=g_setups, savedEvents=g_events;
    assert(nabu_dwc3_set_active(false) && reconnectNeedsReset);
    assert(!g_native_connected);
    core[kDwc3Gevntcount/4]=8;g_evt_cursor=8;
    assert(nabu_dwc3_set_active(true));
    assert(deviceSoftResets==2 && !reconnectNeedsReset && !g_faulted);
    assert(starts[0]==beforeReconnect+1 && !core[kDwc3Gevntcount/4] && !g_evt_cursor);
    assert(g_setups==savedSetups && g_events==savedEvents);
    powerPresent=1;native_poll_events();native_poll_events();assert(cableConnects==1 && !cableDisconnects);
    handle_device_event(1|(kDevEventDisconnect<<8));native_poll_events();
    assert(cableConnects==1 && !cableDisconnects); // Link state is not cable state.
    powerPresent=0;native_poll_events();assert(cableDisconnects==1);
    powerPresent=1;native_poll_events();assert(cableConnects==2);
    // Run51 halted on an 82-byte UTF-16 string: ordinary bcopy's paired tail
    // writes at DMA+50. Descriptor methods must receive only normal RAM.
    for (unsigned i=0;i<82;++i) controlReply.data[i]=(uint8_t)(i^0x5a);
    ep0_stage()[82]=0x6d;
    const unsigned beforeString=completed;
    setupMode=3;setup(0x80,6,0x303,255);
    assert(g_ep0_trbs==2 && ep0[2]==64 && ep0[6]==18);
    assert(!memcmp(ep0_stage(),controlReply.data,82) && ep0_stage()[82]==0x6d);
    ep0[2]=0;ep0[6]=0;handle_dep_event((1<<1)|(kDepevtXferComplete<<6));
    assert(completed==beforeString+1 && completions[beforeString].cookie==(void*)104);
    assert(completions[beforeString].status==0 && completions[beforeString].remaining==0);
    handle_dep_event((kDepevtXferNotReady<<6)|(kDepevtStatusControlStatus<<12));
    handle_dep_event(kDepevtXferComplete<<6);
    assert(g_ep0_state==kEp0Setup && !g_faulted);
    // Failed preparation creates neither a transfer nor a completion, and a
    // later staging failure must release the successfully prepared descriptor.
    assert(nabu_dwc3_activate_endpoint(0x81,kEpTypeBulk,512,0)==0);
    const unsigned beforeFailures=completed, priorPrepares=payload.prepares,
        priorCompletes=payload.completes, priorStarts=starts[3];
    payload.prepareResult=kIOReturnNoMemory;
    assert(nabu_dwc3_submit(0x81,&payload,17,(void*)88)==kIOReturnNoMemory);
    assert(!payload.wireCount && payload.prepares==priorPrepares+1 && payload.completes==priorCompletes);
    assert(!g_native_eps[3].cookie && !g_native_eps[3].buffer && starts[3]==priorStarts);
    payload.prepareResult=kIOReturnSuccess;payload.failRead=true;
    assert(nabu_dwc3_submit(0x81,&payload,17,(void*)89)==kIOReturnUnderrun);
    assert(!payload.wireCount && payload.prepares==priorPrepares+2 && payload.completes==priorCompletes+1);
    assert(!g_native_eps[3].cookie && !g_native_eps[3].buffer && completed==beforeFailures);
    assert(!controlReply.prepares && !controlReply.completes);
    puts("Native DWC3 checks passed: bidirectional DMA, short packets, ZLP, completion reentry, abort, native control stages and reset.");
}
