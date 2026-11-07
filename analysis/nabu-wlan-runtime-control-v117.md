# Native WLAN CE/HTC control runtime

Implementation: `NabuWlanRuntime.{h,cpp}` and `NabuWlanTransport.h`.
No constructor starts hardware. The parent integration supplies the PAS/QMI
lifecycle; the standalone transport has not been executed on the device.

## Production entry points

1. `nabu_wlan_runtime_prepare()` before PAS auth/reset: real DMA arena/page-table
   allocation, all advertised host CE resources, and real native SMMU/fault-IRQ
   attachment. Failure returns false and keeps mutated ownership until confirmed
   shutdown. It performs no WLAN CE register access.
2. `nabu_wlan_runtime_resources_ready()`: true only with a current attached DMA
   owner, prepared/running transport and no observed fault. No synthetic ready
   flag is accepted from the caller.
3. `nabu_wlan_runtime_start()` only after the current instance's actual firmware
   ready and successful WLAN_CFG/WLAN_MODE responses. It observes the owned SMMU,
   maps the board's WLAN window, programs actual CE ring/RRI registers and posts
   receive buffers.
4. `nabu_wlan_runtime_poll()` from the serialized GLINK worker: bounded CE receive
   and transmit-completion polling, real HTC control transactions and fault checks.
   Full SMMU observation occurs at start and each 1000 running ticks, not every
   millisecond. Native fault snapshots are cheap and checked on every poll.
5. `nabu_wlan_runtime_lost()` on PFR/endpoint loss: stop all submissions and retain
   buffers/mappings. `failed()` distinguishes internal DMA/CE/HTC failure.
6. `nabu_wlan_runtime_summary()` reports actual counters and separate observed
   HTC READY / assigned WMI endpoint facts. `stop()` is only valid after successful
   PAS shutdown; it unmaps aliases and disables/synchronizes/releases the DMA owner.
   Failed cleanup retains resources. This version does not automatically restart
   a retired session in the same boot.

## Actual CE resources and memory visibility

The full pinned SNOC host table is allocated: 12 nonempty source/destination
rings and 4852 packet buffers. Each descriptor array and the DDR read-index block
uses a dedicated 64KiB DMA chunk with an uncached CPU alias. No WB packet buffer
shares these aliases, and their original WB CPU aliases are not accessed after
initial publication. This avoids cleaning a stale shared cache line over a
neighboring descriptor written asynchronously by CE hardware. Packet buffers
remain separated by cache lines with explicit ownership/cache synchronization.
Total allocation fits the real 8MiB arena.

After MODE ACK, the runtime masks CE copy/error interrupts and uses bounded
polling. It programs the RRI address at WLAN offsets 0x24c004/0x24c008 and enables
the per-CE update bit19, following ath10k_ce_alloc_rri. Host rings use the pinned
WCN399x descriptors and registers. Nonempty hardware indices at first setup
abort instead of overwriting a prior queue. RX uses count-1 posted descriptors,
consumes actual nonzero completion lengths and reposts the completed buffers.
Oversized device completion aborts before reading beyond the buffer.

TX submissions publish the actual packet/descriptor and use WCN3990 shadow
doorbells at 0x32000 + CE_id*4 (for CE0/3/4/7), not the legacy CE+0x3c write.
Source completion reads actual CE SRRI (CE4 uses the configured DDR update).
The source payload buffer is only reused after the consumer advances.

## HTC/WMI control scope

Actual RX buffers feed the tested NabuHtc parser. An observed HTC READY triggers
the WMI service CONNECT request over CE0; its actual response supplies the WMI
endpoint. Received WMI payloads record event ID/length and counters. No locally
manufactured READY or endpoint response exists. Missing READY/connect response
times out in 5000 worker ticks and invalidates the transport.

HTT connection and SETUP_COMPLETE are deliberately not submitted yet: this slice
has no HTT frame decoder/host receive-ring protocol or WMI service-ready/init
implementation. It allocates the advertised CE storage but does not pretend to
support HTT data. Summary explicitly states that scanning/data remain disabled.
The next implementation can consume WMI events and complete real HTT/setup/WMI
initialization without replacing the CE/DMA transport with stubs.

## Evidence and checks

Pinned Nabu ath10k source under
`log/host/wifi-recheck-v114/data-path-source/`: ce.c 52..84 (shadow addresses),
681..709 / 805..851 (RX ownership), 1039..1110 (TX completion), 1930..1959 (RRI).
Existing snoc.c 135..239 / 966..1013 / 1073..1107 supplies host maps, configuration
and MODE-before-CE-init ordering. Core WCN3990 parameters set target_64bit,
shadow_reg_support and rri_on_ddr, with use_fw_tx_credits=false.

`tools/check_nabu_wlan_runtime.py` passes ASan/UBSan using the production transport
and a software DMA peer: resource allocation, real posted-buffer READY, exact
emitted CE0 CONNECT packet, source completion, WMI assignment/event reception,
RX repost, source shadow addresses, no fabricated READY/HTT/setup, timeout/loss
and nonempty-start refusal. Tests do not run actual MMIO.
`NabuWlanRuntime.cpp` compiled arm64 with existing kernel flags; maximum reported
stack use is 176 bytes, and descriptor bookkeeping arrays are static BSS.
Results: `log/host/wifi-recheck-v114/wlan-runtime-test`.

Link the new NabuWlanRuntime object alongside NabuWlanDma, NabuWlanController and
the four ArmSmmu4K dependencies described in the DMA owner report. Existing USB
and UFS code are unchanged. Device SMMU/IRQ availability, CE/HTC success and all
network operations remain separate hardware acceptance gates.

Native adapter allocates the zero-initialized transport control state once with IOMalloc; retaining its counters through PAS shutdown avoids expanding the existing prelinked __DATA area. DMA buffers remain separately stop/TLB gated.
