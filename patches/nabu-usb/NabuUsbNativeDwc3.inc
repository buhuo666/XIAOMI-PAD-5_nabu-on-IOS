// Included after the verified DWC3 primitives in NabuUsbCaptureCdc.cpp.
// All calls into this transport run under the native family's workloop gate.
namespace nabu_usb_capture {
namespace {
constexpr unsigned kNativeStage = 0x100;
constexpr unsigned kNativeChunk = 0x3e00; // 31 high-speed packets; 16 KiB DMA page.
uint8_t *g_native_dma[32];
struct NativeEndpoint {
    volatile uint32_t *dma;
    uint64_t pa;
    IOMemoryDescriptor *buffer;
    void *cookie;
    uint32_t total, done, chunk, programmed, maxPacket;
    bool enabled, configured, stalled, zlp;
};
NativeEndpoint g_native_eps[32];
bool g_native_active, g_native_connected;
int g_native_vbus = -1;
void *g_native_control_cookie;
uint32_t g_native_control_length, g_native_setup_length;

static unsigned native_dep(uint32_t address)
{ return ((address & 15u) << 1) | ((address >> 7) & 1u); }

static bool native_dma_setup(uint64_t limit)
{
    // DWC3 GHWPARAMS3.NUM_EPS includes control endpoints, both directions.
    g_native_endpoint_count = (mrd(g_regs, 0xc14c) >> 12) & 0x3f;
    IOLog("NABU USB NATIVE: hardware endpoints=%u\n", g_native_endpoint_count);
    if (g_native_endpoint_count < 4 || g_native_endpoint_count > 32) return false;
    for (unsigned dep = 2; dep < g_native_endpoint_count; ++dep) {
        NativeEndpoint &ep = g_native_eps[dep];
        g_native_dma[dep] = static_cast<uint8_t *>(IOMallocAligned(16384, 16384));
        if (!g_native_dma[dep]) return false;
        bzero(g_native_dma[dep], 16384);
        if (!dma_block(g_native_dma[dep], 16384, &ep.dma, &ep.pa) || ep.pa + 16383 > limit)
            return false;
    }
    return true;
}

static void native_finish(unsigned dep, IOReturn status)
{
    NativeEndpoint &ep = g_native_eps[dep];
    void *cookie = ep.cookie;
    const uint32_t remaining = ep.total - ep.done;
    // The stock completion can immediately submit the next request.
    ep.cookie = nullptr; ep.buffer = nullptr;
    if (cookie) nabu_native_usb_transfer_done(cookie, status, remaining);
}

static IOReturn native_start_chunk(unsigned dep)
{
    NativeEndpoint &ep = g_native_eps[dep];
    const uint32_t left = ep.total - ep.done;
    ep.chunk = left > kNativeChunk ? kNativeChunk : left;
    ep.programmed = ep.chunk;
    if (!(dep & 1u)) {
        // DWC3 OUT TRBs cover complete packets; only actual bytes are copied.
        ep.programmed = (ep.chunk + ep.maxPacket - 1) / ep.maxPacket * ep.maxPacket;
        if (!ep.programmed) ep.programmed = ep.maxPacket;
    }
    uint8_t *stage = reinterpret_cast<uint8_t *>(const_cast<uint32_t *>(ep.dma)) + kNativeStage;
    if ((dep & 1u) && ep.chunk && ep.buffer->readBytes(ep.done, stage, ep.chunk) != ep.chunk)
        return kIOReturnUnderrun;
    ep.dma[0] = static_cast<uint32_t>(ep.pa + kNativeStage);
    ep.dma[1] = static_cast<uint32_t>((ep.pa + kNativeStage) >> 32);
    ep.dma[2] = ep.programmed;
    mmio_barrier();
    ep.dma[3] = kTrbctlNormal | kTrbCtrlIspImi | kTrbCtrlIoc | kTrbCtrlLst | kTrbCtrlHwo;
    mmio_barrier();
    return ep_cmd(dep, kDepcmdStartTransfer, static_cast<uint32_t>(ep.pa >> 32),
        static_cast<uint32_t>(ep.pa), 0, nullptr) ? kIOReturnIOError : kIOReturnSuccess;
}

static void native_bulk_complete(unsigned dep)
{
    NativeEndpoint &ep = g_native_eps[dep];
    if (!ep.cookie) return;
    const uint32_t word = mrd(ep.dma, 8), remaining = word & kTrbSizeMask;
    if ((word & kTrbSizeTrbstsMask) || remaining > ep.programmed) {
        native_finish(dep, kIOReturnIOError); return;
    }
    const uint32_t actual = ep.programmed - remaining;
    if (actual > ep.chunk) { native_finish(dep, kIOReturnOverrun); return; }
    if (!(dep & 1u) && actual) {
        const uint8_t *stage = reinterpret_cast<const uint8_t *>(const_cast<uint32_t *>(ep.dma)) + kNativeStage;
        if (ep.buffer->writeBytes(ep.done, stage, actual) != actual) {
            native_finish(dep, kIOReturnUnderrun); return;
        }
    }
    ep.done += actual;
    if (actual < ep.chunk) { native_finish(dep, kIOReturnSuccess); return; }
    if (ep.done == ep.total) {
        if ((dep & 1u) && ep.total && !(ep.total % ep.maxPacket) && !ep.zlp) {
            ep.zlp = true; // Terminate the logical IN transfer with a short packet.
        } else { native_finish(dep, kIOReturnSuccess); return; }
    }
    const IOReturn status = native_start_chunk(dep);
    if (status) native_finish(dep, status);
}

static void native_control_complete(IOReturn status, uint32_t remaining)
{
    void *cookie = g_native_control_cookie;
    g_native_control_cookie = nullptr;
    if (cookie) nabu_native_usb_transfer_done(cookie, status, remaining);
}

static void native_ep0_setup()
{
    uint32_t setup[2] = {mrd(g_ep0, kEp0SetupBuffer), mrd(g_ep0, kEp0SetupBuffer + 4)};
    g_native_setup_length = setup[1] >> 16;
    ++g_setups;
    g_ep0_three = g_native_setup_length != 0;
    g_ep0_in = g_ep0_three && (setup[0] & 0x80u);
    g_ep0_status_dep = g_ep0_in ? 0 : 1;
    g_ep0_state = kEp0WaitStatus;
    g_ep0_zlp = false;
    g_native_eps[0].stalled = g_native_eps[1].stalled = false;
    IOLog("NABU USB NATIVE: setup=%08x/%08x\n", setup[0], setup[1]);
    nabu_native_usb_setup(setup);
    if (g_ep0_three && !g_ep0_in && g_ep0_state == kEp0WaitStatus) {
        if (g_native_setup_length > kEp0StageBytes) { ep0_restart(); return; }
        ep0_data(0, kEp0Stage, g_native_setup_length);
    }
}

static void native_dep_event(uint32_t event)
{
    const unsigned dep = (event >> 1) & 31, kind = (event >> 6) & 15;
    const unsigned status = (event >> 12) & 15;
    if (kind == kDepevtXferNotReady) {
        if (dep <= 1 && status == kDepevtStatusControlStatus &&
            dep == g_ep0_status_dep && g_ep0_state == kEp0WaitStatus) ep0_status(dep);
        return;
    }
    if (kind != kDepevtXferComplete) return;
    g_resources[dep] = 0;
    if (dep > 1) { native_bulk_complete(dep); return; }
    if (g_ep0_state == kEp0Setup && dep == 0) { native_ep0_setup(); return; }
    if (g_ep0_state == kEp0Data) {
        uint32_t remaining = 0;
        for (unsigned i = 0; i < g_ep0_trbs; ++i) {
            const uint32_t word = mrd(ep0_trb(i), 8);
            if ((word >> kTrbSizeTrbstsShift) == kTrbstsSetupPending) {
                ep_end_transfer(0,0); ep_end_transfer(1,0);
                nabu_native_usb_abort_control();
                ep0_arm_setup(); return;
            }
            if (word & kTrbSizeTrbstsMask) {
                IOLog("NABU USB NATIVE: control TRB error=%08x\n",word);
                nabu_dwc3_stall_endpoint(0,true); return;
            }
            remaining += word & kTrbSizeMask;
        }
        const uint32_t programmed = dep == 1 ? g_native_control_length :
            (g_native_setup_length + 63) & ~63u;
        if (remaining > programmed) { nabu_dwc3_stall_endpoint(0,true); return; }
        g_ep0_state = kEp0WaitStatus;
        if (dep == 1) {
            native_control_complete(kIOReturnSuccess, remaining);
        } else {
            nabu_native_usb_out_data(ep0_stage(), programmed - remaining);
        }
        return;
    }
    if (g_ep0_state == kEp0Status) {
        if (dep == 1) native_control_complete(kIOReturnSuccess, 0);
        else nabu_native_usb_out_data(nullptr, 0);
        ep0_arm_setup();
    }
}

static void native_device_event(uint32_t event)
{
    const unsigned type = (event >> 8) & 15;
    IOLog("NABU USB NATIVE: bus event=%u\n", type);
    if (type == kDevEventReset) {
        // The frontend drains all queues before any cancellation callback can
        // re-enter submit, and resets the stock control-request state first.
        nabu_native_usb_bus_reset();
        for (unsigned dep = 2; dep < g_native_endpoint_count; ++dep) {
            g_native_eps[dep].enabled = false;
            nabu_dwc3_abort_endpoint((dep >> 1) | ((dep & 1) << 7));
            g_native_eps[dep].configured = false;
            dalepena_set(dep, false);
        }
        if (g_ep0_state != kEp0Setup) {
            ep_end_transfer(0, 0); ep_end_transfer(1, 0);
            native_control_complete(kIOReturnAborted, g_native_control_length);
            ep0_arm_setup();
        }
        mwr(g_regs, kDwc3Dcfg, mrd(g_regs, kDwc3Dcfg) & ~kDcfgDevaddrMask);
    } else if (type == kDevEventConnectDone) {
        if ((mrd(g_regs, kDwc3Dsts) & kDstsConnectspdMask) != kDcfgHighSpeed) {
            IOLog("NABU USB NATIVE: unsupported negotiated speed\n"); g_faulted = true; return;
        }
        ep_enable(0, kEpTypeControl, 64, kDepcfgActionModify);
        ep_enable(1, kEpTypeControl, 64, kDepcfgActionModify);
        g_native_connected = true;
    } else if (type == kDevEventDisconnect) {
        g_native_connected = false;
        // A link disconnect also occurs during intentional re-enumeration.
        // Physical cable state comes from the existing PMIC power sampler.
        nabu_native_usb_bus_reset();
        for (unsigned dep = 2; dep < g_native_endpoint_count; ++dep)
            nabu_dwc3_abort_endpoint((dep >> 1) | ((dep & 1) << 7));
        native_control_complete(kIOReturnAborted, g_native_control_length);
    }
}

static void native_poll_events()
{
    poll_events();
    const int present = nabu_power_usb_present();
    if (present >= 0 && present != g_native_vbus) {
        g_native_vbus = present;
        IOLog("NABU USB NATIVE: PMIC VBUS=%d\n",present);
        if (present) nabu_native_usb_connected();
        else nabu_native_usb_disconnected();
    }
}
} // namespace

extern "C" bool nabu_dwc3_set_active(bool active)
{
    if (active == g_native_active) return true;
    if (active) {
        ep0_arm_setup();
        uint32_t value = mrd(g_regs, kDwc3Dctl) | kDctlRunStop;
        mwr(g_regs, kDwc3Dctl, (value & ~kDctlHirdThresMask) | kDctlHirdThres);
    } else {
        for (unsigned dep = 0; dep < g_native_endpoint_count; ++dep)
            nabu_dwc3_abort_endpoint((dep >> 1) | ((dep & 1) << 7));
        mwr(g_regs, kDwc3Dctl, mrd(g_regs, kDwc3Dctl) & ~kDctlRunStop);
    }
    g_native_active = active;
    return !g_faulted;
}

extern "C" IOReturn nabu_dwc3_activate_endpoint(uint32_t address, uint32_t type,
    uint32_t maxPacket, uint32_t interval)
{
    const unsigned dep = native_dep(address);
    if (dep < 2 || dep >= g_native_endpoint_count || !maxPacket || maxPacket > 512)
        return kIOReturnBadArgument;
    if (type != kEpTypeBulk) return kIOReturnUnsupported;
    (void)interval;
    NativeEndpoint &ep = g_native_eps[dep];
    ep_enable(dep, type, maxPacket, ep.configured ? kDepcfgActionModify : kDepcfgActionInit);
    if (g_faulted) return kIOReturnIOError;
    ep.maxPacket = maxPacket; ep.configured = true; ep.enabled = true; ep.stalled = false;
    dalepena_set(dep, true);
    return kIOReturnSuccess;
}

extern "C" void nabu_dwc3_abort_endpoint(uint32_t address)
{
    const unsigned dep = native_dep(address);
    ep_end_transfer(dep, 0);
    if (dep <= 1) native_control_complete(kIOReturnAborted, g_native_control_length);
    else native_finish(dep, kIOReturnAborted);
}

extern "C" IOReturn nabu_dwc3_deactivate_endpoint(uint32_t address)
{
    const unsigned dep = native_dep(address);
    if (dep < 2 || dep >= g_native_endpoint_count) return kIOReturnBadArgument;
    g_native_eps[dep].enabled = false;
    nabu_dwc3_abort_endpoint(address);
    dalepena_set(dep, false);
    return g_faulted ? kIOReturnIOError : kIOReturnSuccess;
}

extern "C" void nabu_dwc3_stall_endpoint(uint32_t address, bool stalled)
{
    const unsigned dep = native_dep(address);
    if (dep <= 1 && stalled) {
        ep_end_transfer(0, 0); ep_end_transfer(1, 0);
        nabu_native_usb_abort_control();
        ep0_restart();
        g_native_eps[0].stalled = g_native_eps[1].stalled = true;
        return;
    }
    ep_cmd(dep, stalled ? kDepcmdSetStall : kDepcmdClearStall, 0, 0, 0, nullptr);
    g_native_eps[dep].stalled = stalled;
}
extern "C" bool nabu_dwc3_endpoint_stalled(uint32_t address)
{ return g_native_eps[native_dep(address)].stalled; }
extern "C" IOReturn nabu_dwc3_set_address(uint16_t address)
{
    uint32_t value = mrd(g_regs, kDwc3Dcfg) & ~kDcfgDevaddrMask;
    mwr(g_regs, kDwc3Dcfg, value | ((address & 127) << kDcfgDevaddrShift));
    return kIOReturnSuccess;
}
extern "C" int nabu_dwc3_connection_speed()
{ return g_native_connected ? 2 : -1; }
extern "C" void nabu_dwc3_reset_toggle(uint32_t address)
{ nabu_dwc3_stall_endpoint(address, false); }

extern "C" IOReturn nabu_dwc3_submit(uint32_t address, IOMemoryDescriptor *buffer,
    uint32_t length, void *cookie)
{
    const unsigned dep = native_dep(address);
    if (dep < 2) {
        if (dep != 1 || length > kEp0StageBytes || g_native_control_cookie) return kIOReturnBadArgument;
        if (length && buffer->readBytes(0, ep0_stage(), length) != length) return kIOReturnUnderrun;
        g_native_control_cookie = cookie; g_native_control_length = length;
        if (!length && (!g_ep0_three || !g_ep0_in)) g_ep0_state = kEp0WaitStatus;
        else ep0_data(1, kEp0Stage, length);
        if (g_faulted) { g_native_control_cookie = nullptr; return kIOReturnIOError; }
        return kIOReturnSuccess;
    }
    NativeEndpoint &ep = g_native_eps[dep];
    if (!ep.enabled || ep.cookie) return kIOReturnNotReady;
    ep.cookie = cookie; ep.buffer = buffer; ep.total = length; ep.done = 0; ep.zlp = false;
    const IOReturn status = native_start_chunk(dep);
    if (status) { ep.cookie = nullptr; ep.buffer = nullptr; }
    return status;
}
} // namespace nabu_usb_capture
