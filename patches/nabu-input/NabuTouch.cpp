// SPDX-License-Identifier: BSD-2-Clause-Patent
// Port of UniXNU-nabu 54b4f98457f8e9e232cc0a077c20d08d0b2f0ac9 platform/NabuTouch.cpp.
// The board SPI/NT36523 protocol is retained; the 21H16 IOHIDDevice ABI is replaced
// with this kernel's hakios-touch queue. Firmware bytes come from the local ADT.
#include <IOKit/IOLib.h>
#include <IOKit/IORegistryEntry.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/c++/OSData.h>
#include <kern/thread.h>
#include <kern/clock.h>
#include <pexpert/pexpert.h>
#include "NabuTouchPackets.h"
extern "C" {
vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
void hakios_touch_post(uint32_t, uint32_t, uint32_t, uint32_t);
kern_return_t thread_terminate(thread_t);
volatile uint32_t nabu_touch_stats[8] = {};
}
#define TLOG(fmt, ...) IOLog("NABU TOUCH: " fmt "\n", ##__VA_ARGS__)
namespace {
// ---------------------------------------------------------------- MMIO
struct Mmio {
  volatile uint32_t *base = nullptr;
  uint32_t r(uint32_t off) const { return base[off / 4]; }
  void w(uint32_t off, uint32_t value) const {
    base[off / 4] = value;
    __asm__ volatile("dsb sy" ::: "memory");
  }
};

Mmio map(uint64_t pa, uint32_t size)
{
  Mmio m;
  m.base = reinterpret_cast<volatile uint32_t *>(ml_io_map(static_cast<vm_offset_t>(pa), size));
  return m;
}

uint64_t deadlineUs(uint64_t us)
{
  uint64_t delta;
  nanoseconds_to_absolutetime(us * 1000, &delta);
  return mach_absolute_time() + delta;
}

// ------------------------------------------------- GCC / TLMM / GENI SE18
constexpr uint64_t kGccQupPa = 0x0011e000;   // GCC + 0x1e000: wrap2 AHB CBCRs, S1 CBCR/RCG
constexpr uint64_t kGccVotePa = 0x00152000;  // GCC + 0x52000: APCS clock branch vote at +0x14
constexpr uint64_t kSePa = 0x00c84000;
constexpr uint64_t kTlmmSpiPa = 0x03517000;  // GPIO 23..26, one 0x1000 window each
constexpr uint32_t kRcg = 0x278;             // wrap2 S1 RCG CMD within kGccQupPa

enum : uint32_t {
  GENI_FORCE_DEFAULT = 0x20, GENI_OUTPUT_CTRL = 0x24, GENI_CGC_CTRL = 0x28, GENI_STATUS = 0x40,
  GENI_M_CLK_CFG = 0x48, GENI_FIFO_DISABLE = 0x64, GENI_FW_REVISION = 0x68, GENI_CLK_SEL = 0x7c,
  SPI_CPHA = 0x224, SPI_LOOPBACK = 0x22c, SPI_CPOL = 0x230, SPI_DEMUX_INV = 0x24c,
  SPI_DEMUX_SEL = 0x250, GENI_BYTE_GRAN = 0x254, GENI_DMA_MODE = 0x258, SPI_TRANS_CFG = 0x25c,
  TX_PACK0 = 0x260, TX_PACK1 = 0x264, SPI_WORD_LEN = 0x268, SPI_TX_LEN = 0x26c, SPI_RX_LEN = 0x270,
  SPI_PRE_POST_DLY = 0x274, SPI_DELAY = 0x278, RX_PACK0 = 0x284, RX_PACK1 = 0x288,
  M_CMD0 = 0x600, M_CMD_CTRL = 0x604, M_IRQ_STATUS = 0x610, M_IRQ_EN = 0x614, M_IRQ_CLEAR = 0x618,
  S_IRQ_CLEAR = 0x648, TX_FIFO = 0x700, RX_FIFO = 0x780, TX_FIFO_STATUS = 0x800,
  RX_FIFO_STATUS = 0x804, RX_WM = 0x810, RX_RFR_WM = 0x814, GSI_EVENT_EN = 0xe18, SE_IRQ_EN = 0xe1c,
};
constexpr uint32_t kMErrors = 0x3e;          // OVERRUN, ILLEGAL_CMD, FAILURE, CANCEL, ABORT
constexpr uint32_t kFifoWords = 16;

Mmio gSe;
uint8_t scratch[256];
uint8_t *gScratch = scratch;                 // full-duplex receive buffer
constexpr uint32_t kScratch = 256;

bool clocksUp()
{
  Mmio gcc = map(kGccQupPa, 0x1000), vote = map(kGccVotePa, 0x1000);
  if (!gcc.base || !vote.base) { return false; }
  TLOG("clk before vote=%#x m-ahb=%#x s-ahb=%#x se=%#x rcg=%#x/%#x dfs=%#x", vote.r(0x14),
       gcc.r(0x004), gcc.r(0x008), gcc.r(0x274), gcc.r(kRcg), gcc.r(kRcg + 4), gcc.r(kRcg + 0x14));
  // Shared vote register: only add SE18 core (bit5), wrap2 m-ahb (bit2) and s-ahb (bit1).
  vote.w(0x14, vote.r(0x14) | (1u << 5) | (1u << 2) | (1u << 1));
  uint64_t end = deadlineUs(20000);
  while (((gcc.r(0x004) | gcc.r(0x274)) & 0x80000000u) && mach_absolute_time() < end) { IODelay(10); }
  uint32_t m = gcc.r(0x004), se = gcc.r(0x274);
  TLOG("clk after vote=%#x m-ahb=%#x s-ahb=%#x se=%#x", vote.r(0x14), m, gcc.r(0x008), se);
  if ((m | se) & 0x80000000u) { return false; }
  // Pick an SE clock: DFS levels are preset by firmware and selected by GENI CLK_SEL.
  uint32_t level = 0;
  uint64_t hz = 0;
  if (gcc.r(kRcg + 0x14) & 1) {
    for (uint32_t l = 0; l < 8; l++) {
      uint32_t perf = gcc.r(kRcg + 0x1c + 4 * l);
      uint32_t src = (perf >> 8) & 7, div = perf & 0x1f, mode = (perf >> 12) & 3;
      uint64_t f = src == 0 ? 19200000ull : src == 1 ? 600000000ull : src == 6 ? 300000000ull : 0;
      if (div) { f = f * 2 / (div + 1); }
      if (mode && f) {
        uint32_t mv = gcc.r(kRcg + 0x5c + 4 * l) & 0xffff;
        uint32_t nv = ((~gcc.r(kRcg + 0x9c + 4 * l)) & 0xffff) + mv;
        f = nv ? f * mv / nv : 0;
      }
      TLOG("clk dfs level=%u perf=%#x hz=%llu", l, perf, (unsigned long long)f);
      if (f && (!hz || f < hz)) { hz = f; level = l; }
    }
  } else {
    // No DFS: run the RCG straight from TCXO.
    gcc.w(kRcg + 4, gcc.r(kRcg + 4) & ~0x371fu);
    gcc.w(kRcg, gcc.r(kRcg) | 1);
    end = deadlineUs(2000);
    while ((gcc.r(kRcg) & 1) && mach_absolute_time() < end) { IODelay(1); }
    hz = 19200000ull;
  }
  if (!hz) { TLOG("no usable SE18 clock"); return false; }
  uint32_t div = static_cast<uint32_t>((hz + 9600000 - 1) / 9600000);
  if (div < 1) { div = 1; }
  if (div > 0xfff) { div = 0xfff; }
  gSe.w(GENI_CLK_SEL, level);
  gSe.w(GENI_M_CLK_CFG, (div << 4) | 1);
  TLOG("clk se level=%u hz=%llu geni-div=%u sclk=%llu", level, (unsigned long long)hz, div, (unsigned long long)(hz / div));
  return true;
}

void pinsUp()
{
  static const uint32_t ctl[4] = {0x088, 0x08c, 0x08c, 0x088};   // qup18 function, 6 mA, no pull
  Mmio spi = map(kTlmmSpiPa, 0x4000);
  if (spi.base) {
    for (uint32_t i = 0; i < 4; i++) {
      TLOG("pin gpio%u ctl=%#x -> %#x", 23 + i, spi.r(i * 0x1000), ctl[i]);
      spi.w(i * 0x1000, ctl[i]);
    }
  }
}

bool seInit()
{
  uint32_t fw = gSe.r(GENI_FW_REVISION), fifoOff = gSe.r(GENI_FIFO_DISABLE);
  TLOG("se fw=%#x proto=%u fifo-disabled=%u status=%#x m-irq=%#x", fw, (fw >> 8) & 0xff,
       fifoOff & 1, gSe.r(GENI_STATUS), gSe.r(M_IRQ_STATUS));
  if (((fw >> 8) & 0xff) != 1 || (fifoOff & 1)) { return false; }
  if (gSe.r(GENI_STATUS) & 1) {
    gSe.w(M_CMD_CTRL, 1u << 2);
    IODelay(100);
    gSe.w(M_CMD_CTRL, 1u << 1);
    IODelay(100);
  }
  gSe.w(GENI_CGC_CTRL, gSe.r(GENI_CGC_CTRL) | 0x7f);
  gSe.w(GENI_OUTPUT_CTRL, 0x7f);
  gSe.w(GENI_FORCE_DEFAULT, 1);
  gSe.w(GSI_EVENT_EN, 0);
  gSe.w(SE_IRQ_EN, 0);                 // polled: keep the GIC line quiet
  gSe.w(GENI_DMA_MODE, gSe.r(GENI_DMA_MODE) & ~1u);
  gSe.w(M_IRQ_CLEAR, 0xffffffffu);
  gSe.w(S_IRQ_CLEAR, 0xffffffffu);
  gSe.w(M_IRQ_EN, gSe.r(M_IRQ_EN) | 0x4c00003fu);
  gSe.w(RX_WM, 0);
  gSe.w(RX_RFR_WM, kFifoWords - 2);
  gSe.w(TX_PACK0, 0x0007f8fe); gSe.w(TX_PACK1, 0x000ffefe);
  gSe.w(RX_PACK0, 0x0007f8fe); gSe.w(RX_PACK1, 0x000ffefe);
  gSe.w(GENI_BYTE_GRAN, 0);
  gSe.w(SPI_WORD_LEN, 8 - 4);
  gSe.w(SPI_CPHA, 0); gSe.w(SPI_CPOL, 0); gSe.w(SPI_LOOPBACK, 0);
  gSe.w(SPI_DEMUX_SEL, 0); gSe.w(SPI_DEMUX_INV, 0);
  gSe.w(SPI_TRANS_CFG, gSe.r(SPI_TRANS_CFG) & ~1u);
  gSe.w(SPI_PRE_POST_DLY, 0); gSe.w(SPI_DELAY, 0);
  return true;
}

// One CS-asserted transfer: header bytes then payload (payload nullptr sends zeros).
// rx, when given, receives all hlen + plen bytes clocked in.
bool spiXfer(const uint8_t *hdr, uint32_t hlen, const uint8_t *payload, uint32_t plen, uint8_t *rx)
{
  const uint32_t len = hlen + plen;
  uint64_t end = deadlineUs(5000);
  while ((gSe.r(GENI_STATUS) & 1) && mach_absolute_time() < end) { IODelay(1); }
  if (gSe.r(GENI_STATUS) & 1) { return false; }
  gSe.w(M_IRQ_CLEAR, 0xffffffffu);
  gSe.w(SPI_TX_LEN, len);
  if (rx) { gSe.w(SPI_RX_LEN, len); }
  gSe.w(M_CMD0, (rx ? 3u : 1u) << 27);
  uint32_t tx = 0, got = 0;
  end = deadlineUs(50000 + static_cast<uint64_t>(len) * 4);
  for (;;) {
    while (tx < len && (gSe.r(TX_FIFO_STATUS) & 0x0fffffffu) < kFifoWords) {
      uint32_t word = 0;
      for (uint32_t b = 0; b < 4 && tx < len; b++, tx++) {
        uint8_t v = tx < hlen ? hdr[tx] : (payload ? payload[tx - hlen] : 0);
        word |= static_cast<uint32_t>(v) << (8 * b);
      }
      gSe.w(TX_FIFO, word);
    }
    if (rx) {
      uint32_t words = gSe.r(RX_FIFO_STATUS) & 0x1ffffffu;
      while (words--) {
        uint32_t word = gSe.r(RX_FIFO);
        for (uint32_t b = 0; b < 4 && got < len; b++, got++) { rx[got] = static_cast<uint8_t>(word >> (8 * b)); }
      }
    }
    uint32_t irq = gSe.r(M_IRQ_STATUS);
    if (irq & kMErrors) { break; }
    if ((irq & 1) && tx >= len && (!rx || got >= len)) {
      gSe.w(M_IRQ_CLEAR, irq);
      return true;
    }
    if (mach_absolute_time() > end) { break; }
  }
  TLOG("spi fail len=%u tx=%u rx=%u irq=%#x status=%#x", len, tx, got, gSe.r(M_IRQ_STATUS), gSe.r(GENI_STATUS));
  gSe.w(M_CMD_CTRL, 1u << 2);
  IODelay(100);
  if (gSe.r(GENI_STATUS) & 1) { gSe.w(M_CMD_CTRL, 1u << 1); IODelay(100); }
  gSe.w(M_IRQ_CLEAR, 0xffffffffu);
  return false;
}

// ---------------------------------------------------------- NT36523 protocol
bool ntPage(uint32_t addr)
{
  const uint8_t b[3] = {0xff, static_cast<uint8_t>(addr >> 15), static_cast<uint8_t>(addr >> 7)};
  return spiXfer(b, 3, nullptr, 0, nullptr);
}

bool ntWrite(uint32_t addr, const uint8_t *data, uint32_t n)
{
  const uint8_t cmd = static_cast<uint8_t>(0x80 | (addr & 0x7f));
  return spiXfer(&cmd, 1, data, n, nullptr);
}

bool ntRead(uint32_t addr, uint8_t *out, uint32_t n)
{
  if (n + 2 > kScratch) { return false; }
  const uint8_t cmd = static_cast<uint8_t>(addr & 0x7f);
  if (!spiXfer(&cmd, 1, nullptr, n + 1, gScratch)) { return false; }
  memcpy(out, gScratch + 2, n);
  return true;
}

bool ntWriteAddr(uint32_t addr, uint8_t value)
{
  return ntPage(addr) && ntWrite(addr, &value, 1);
}

bool ntReadAddr(uint32_t addr, uint8_t *value)
{
  return ntPage(addr) && ntRead(addr, value, 1);
}

void ntBootloaderReset()
{
  ntWriteAddr(0x3f0fe, 0x69);
  IOSleep(5);
  ntWriteAddr(0x3f310, 0x00);
}

bool ntChipId()
{
  ntWriteAddr(0x7fff80, 0x5a);
  IOSleep(11);
  for (int attempt = 0; attempt < 5; attempt++) {
    ntBootloaderReset();
    uint8_t id[6] = {};
    bool ok = ntPage(0x3f004) && ntRead(0x3f004, id, 6);
    TLOG("chip-id try=%d ok=%d %02x %02x %02x %02x %02x %02x", attempt, ok, id[0], id[1], id[2], id[3], id[4], id[5]);
    if (ok && id[3] == 0x23 && id[4] == 0x65 && id[5] == 0x03) { return true; }
    IOSleep(10);
  }
  return false;
}

struct Firmware {
  const uint8_t *blob = nullptr;
  uint32_t blobSize = 0;
  const uint32_t *parts = nullptr;   // {sram, bin, length-to-write} triples
  uint32_t partCount = 0;
  uint32_t bank[6] = {};             // ILM sram/size/crc, DLM sram/size/crc
};

void ntCrcBank(uint32_t des, uint32_t len, uint32_t gchk, uint32_t sram, uint32_t size, uint32_t crc)
{
  ntPage(des);
  const uint8_t a[3] = {static_cast<uint8_t>(sram), static_cast<uint8_t>(sram >> 8), static_cast<uint8_t>(sram >> 16)};
  ntWrite(des, a, 3);
  const uint8_t l[3] = {static_cast<uint8_t>(size), static_cast<uint8_t>(size >> 8), static_cast<uint8_t>((size >> 16) & 1)};
  ntWrite(len, l, 3);
  const uint8_t c[4] = {static_cast<uint8_t>(crc), static_cast<uint8_t>(crc >> 8), static_cast<uint8_t>(crc >> 16),
                        static_cast<uint8_t>(crc >> 24)};
  ntWrite(gchk, c, 4);
}

uint32_t gXMax = 1600, gYMax = 2560;

bool ntDownload(const Firmware &fw)
{
  for (int attempt = 0; attempt < 3; attempt++) {
    uint64_t start = mach_absolute_time();
    ntBootloaderReset();
    ntCrcBank(0x3f128, 0x3f118, 0x3f100, fw.bank[0], fw.bank[1], fw.bank[2]);
    ntCrcBank(0x3f12c, 0x3f130, 0x3f104, fw.bank[3], fw.bank[4], fw.bank[5]);
    ntWriteAddr(0x3f7e8, 0x69);
    bool sent = true;
    for (uint32_t p = 0; p < fw.partCount && sent; p++) {
      uint32_t sram = fw.parts[3 * p], bin = fw.parts[3 * p + 1], left = fw.parts[3 * p + 2];
      while (left && sent) {
        uint32_t chunk = left < 63 * 1024 ? left : 63 * 1024;
        sent = ntPage(sram) && ntWrite(sram, fw.blob + bin, chunk);
        sram += chunk; bin += chunk; left -= chunk;
      }
    }
    uint8_t dma = 0xee;
    for (int i = 0; i < 200 && sent; i++) {
      if (ntReadAddr(0x3f7f1, &dma) && dma == 0) { break; }
      IOSleep(1);
    }
    uint8_t crcEn = 0;
    ntReadAddr(0x3f30e, &crcEn);
    ntWriteAddr(0x3f30e, crcEn | 0x80);
    ntPage(0x2fe00);
    uint8_t zero = 0, crcCmd = 0xae;
    ntWrite(0x2fe60, &zero, 1);
    ntWrite(0x2fe50, &crcCmd, 1);
    ntWriteAddr(0x3f10d, 1);
    IOSleep(5);
    uint8_t state[5] = {};
    bool booted = false;
    for (int i = 0; i < 10 && !booted; i++) {
      booted = ntPage(0x2fe60) && ntRead(0x2fe60, state, 5) && state[0] >= 0xa0 && state[0] <= 0xaf;
      if (!booted) { IOSleep(10); }
    }
    uint64_t ns;
    absolutetime_to_nanoseconds(mach_absolute_time() - start, &ns);
    TLOG("fw download try=%d sent=%d dma=%#x reset-state=%#x booted=%d ms=%llu", attempt, sent, dma,
         state[0], booted, (unsigned long long)(ns / 1000000));
    if (!booted) {
      uint8_t crcFlags = 0;
      ntReadAddr(0x3f133, &crcFlags);
      TLOG("fw crc flags=%#x", crcFlags);
      continue;
    }
    uint8_t info[38] = {};
    if (ntPage(0x2fe78) && ntRead(0x2fe78, info, sizeof(info))) {
      uint32_t xm = (info[4] << 8) | info[5], ym = (info[6] << 8) | info[7];
      TLOG("fw info ver=%#x/%#x xnum=%u ynum=%u xmax=%u ymax=%u type=%#x", info[0], info[1], info[2], info[3], xm,
           ym, info[13]);
      if (static_cast<uint8_t>(info[0] + info[1]) == 0xff && xm && ym) { gXMax = xm; gYMax = ym; }
    }
    uint8_t pid[2] = {};
    if (ntPage(0x2fe9a) && ntRead(0x2fe9a, pid, 2)) { TLOG("fw pid=%#x", pid[0] | (pid[1] << 8)); }
    ntPage(0x2fe00);
    nabu_touch_stats[7] = nabu_touch_stats[7] + 1;
    return true;
  }
  return false;
}

bool loadFirmware(Firmware &fw)
{
    IORegistryEntry *node = IORegistryEntry::fromPath("/nabu-touch", gIODTPlane);
    if (!node) { TLOG("ADT /nabu-touch missing"); return false; }
    OSData *blob = OSDynamicCast(OSData, node->getProperty("firmware"));
    OSData *parts = OSDynamicCast(OSData, node->getProperty("partitions"));
    OSData *bank = OSDynamicCast(OSData, node->getProperty("crc-bank"));
    bool ok = blob && parts && bank && parts->getLength() &&
              parts->getLength() % 12 == 0 && bank->getLength() == 24;
    if (ok) {
        fw.blob = static_cast<const uint8_t *>(blob->getBytesNoCopy());
        fw.blobSize = blob->getLength();
        fw.parts = static_cast<const uint32_t *>(parts->getBytesNoCopy());
        fw.partCount = parts->getLength() / 12;
        memcpy(fw.bank, bank->getBytesNoCopy(), sizeof(fw.bank));
        for (uint32_t p = 0; p < fw.partCount; ++p) {
            uint32_t offset = fw.parts[3 * p + 1], size = fw.parts[3 * p + 2];
            if (offset > fw.blobSize || size > fw.blobSize - offset) ok = false;
        }
    }
    node->release();
    TLOG("firmware ready=%d bytes=%u partitions=%u", ok, fw.blobSize, fw.partCount);
    return ok;
}

void runTouch(void)
{
    Firmware fw;
    if (!loadFirmware(fw)) return;
    nabu_touch_stats[0] = 1;
    gSe = map(kSePa, 0x4000);
    if (!gSe.base || !clocksUp()) { TLOG("clock setup failed"); return; }
    pinsUp();
    if (!seInit() || !ntChipId()) { TLOG("SPI or chip identification failed"); return; }
    nabu_touch_stats[0] = 2;
    if (!ntDownload(fw)) { TLOG("firmware download failed"); return; }
    nabu_touch_stats[0] = 3;
    TLOG("point polling active: %ux%u, 8 ms interval", gXMax, gYMax);
    NabuContacts previous = {};
    uint8_t packet[80];
    unsigned restartFrames = 0;
    uint64_t nextStatus = deadlineUs(30000000);
    for (;;) {
        if (ntRead(0x2fe00, packet, sizeof(packet))) {
            ++nabu_touch_stats[1];
            NabuContacts current;
            int result = nabu_decode_contacts(packet, gXMax, gYMax, &current);
            if (result == 0) {
                restartFrames = 0;
                if (current.active) ++nabu_touch_stats[2];
                nabu_publish_contacts(&previous, &current, hakios_touch_post);
                ++nabu_touch_stats[4];
            } else if (result == -2 && ++restartFrames >= 10) {
                NabuContacts released = {};
                nabu_publish_contacts(&previous, &released, hakios_touch_post);
                TLOG("controller restart pattern; reloading firmware");
                if (!ntDownload(fw)) return;
                restartFrames = 0;
            } else if (result == -1) {
                restartFrames = 0;
                ++nabu_touch_stats[3];
            }
        } else {
            ++nabu_touch_stats[5];
        }
        if (mach_absolute_time() >= nextStatus) {
            TLOG("frames=%u touching=%u bad=%u accepted=%u bus-errors=%u firmware-loads=%u",
                 nabu_touch_stats[1], nabu_touch_stats[2], nabu_touch_stats[3],
                 nabu_touch_stats[4], nabu_touch_stats[5], nabu_touch_stats[7]);
            nextStatus = deadlineUs(60000000);
        }
        IOSleep(8);
    }
}
void touchThread(void *, wait_result_t)
{
    runTouch();
    thread_terminate(current_thread());
}
} // namespace

extern "C" void nabu_touch_init(void)
{
    uint32_t enabled = 0;
    if (!PE_parse_boot_argn("nabu-touch", &enabled, sizeof(enabled)) || !enabled) return;
    thread_t thread;
    if (kernel_thread_start(touchThread, nullptr, &thread) == KERN_SUCCESS) {
        thread_deallocate(thread);
        TLOG("worker started");
    }
}
