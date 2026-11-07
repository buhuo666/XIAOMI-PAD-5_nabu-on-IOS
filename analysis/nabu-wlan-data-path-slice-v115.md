# Nabu WLAN configuration and CE data-path slice

This change adds executable protocol/ring machinery for the WCN399x backend. It
does not attach a network interface or claim scanning/networking works. No device
operation or shared GLINK/WLFW/modem change was made by this work.

## Implemented

- `NabuWlanConfig.h`: 559-byte WLAN_CFG 0x23 containing the actual 12 target CE
  entries, 21 service mappings (including final sentinel) and 12 shadow-register
  entries from the pinned Nabu Linux source. Struct padding/reserved members are
  not sent: QMI element widths are 20, 12 and 4 bytes, with one-byte array counts.
  After a matching successful response, produces WLAN_MODE 0x22 MISSION=0 with
  hw_debug=0 (18 bytes). Rejects stale transactions, stops on QMI error/timeout
  or instance loss. Enabling requires explicit firmware-ready and allocated
  resource prerequisites from the caller. Nothing currently supplies these flags
  or submits these packets in the production GLINK loop.
- `NabuSnocRing.h`: native 16-byte WCN399x descriptor and single-buffer source /
  receive ring operations, 35-bit DMA addresses, 12-bit transfer metadata, one
  reserved ring slot, wrap, hardware-consumer TX completion and nonzero descriptor
  length RX completion. PFR stops acceptance/completion without recycling DMA
  buffers. Scatter-gather, CE5 shared receive-context reuse, cache management,
  mapping and synchronization are not implemented here.
- `NabuSnocPipe.h`: actual host ring sizes and WCN399x CE register programming
  through caller-supplied ordered read/write access. Uses offsets 0x240000 +
  id*0x1000 in the WLAN window; restores observed producer/consumer positions,
  programs 35-bit ring bases, size/dmax/endian/watermarks, and copy-complete IRQ
  masks. Destination base-high write preserves unrelated bits. This is not bound
  to live MMIO and has not run on hardware.

## Source and verification

Existing source: `log/host/wireless-v76/source/drivers/net/wireless/ath/ath10k/`
`snoc.c`, `qmi.c`, fixed repository commit
`SeimoDev/linux-xiaomi-nabu@4e6d08bb1b467c721e19cd693e4ec7388d982d73`.
Additional files from that same commit (`ce.[ch]`, `hw.[ch]`, `htc.[ch]`,
`snoc.h`, `qmi.h`) were fetched through the configured proxy and reviewed once
as C source. Source URLs are in
`log/host/wifi-recheck-v114/data-path-source/download.json`.
WLFW descriptors are the already retained
`log/host/wireless-v95/wlan-fault-analysis/source/wlan_firmware_service_v01.[ch]`.

Important anchors: snoc.c target tables 73..487, host tables 135..239,
WLAN configuration 966..1013, power-up ordering 1073..1107;
qmi.c 379..543; ce.c source/destination operations 479..558, 681..709,
805..851 and ring init 1357..1437; hw.c WCN399x registers 190..354.
HTC service IDs are defined by htc.h 258..295.

`python tools/check_nabu_wlan_config.py --output <directory>` passes ASan/UBSan.
The initial wire oracle compiled the original three snoc.c arrays and compared
all request bytes. A frozen independent fixture with provenance is now retained
in `tools/fixtures/nabu-wlan-snoc-config.json`, so CI needs no ignored log files.
Tests cover resource/ready gating, config-before-mode, QMI mismatches/errors,
timeout/retirement, DMA high bits, fullness/wrap, device completion and held
ownership after PFR, register values/RMW and IRQ masks. The headers also compiled
with the existing arm64 kernel flags. Results are under
`log/host/wifi-recheck-v114/wlan-config-test`.

## Runtime integration that is still required

1. Establish the board SMMU stream 0x640 with the Nabu apps-SMMU geometry and a
   caller-owned IOVA allocator in 0xa0000000..0xafffffff. Reuse the existing USB
   SMMU register helpers only after adapting stream ownership and page tables;
   never enable WCN6750's hardcoded stream 0x1c00. Ring addresses are device IOVAs,
   not arbitrary host virtual or physical pointers.
2. Allocate host rings with the **host** depths in NabuSnocPipe, 16-byte
   descriptors and at least 8-byte DMA alignment. Supply coherent mappings or
   explicit release/acquire/cache operations and serialize IRQ/worker accesses.
   Allocate/map RX buffers and register the board's real CE interrupts. None of
   these may be replaced by setting resources_ready=true in the existing trial.
3. Wait for the current firmware instance's actual readiness; send CFG on KNEL,
   consume its ACK, then MODE and its ACK. Pinned ath10k sends MODE **before** CE
   hardware ring initialization, so requiring programmed rings before MODE would
   reverse the source order. Resource allocation/mapping happens earlier.
4. Initialize CE rings and interrupts, post RX buffers, and complete HTC READY /
   CONNECT_SERVICE / SETUP_COMPLETE. A QMI MODE ACK is not HTC or WMI readiness.
   WMI TLV service-ready/init/ready, scan events and BSS parsing, vdev/peer/key
   operations and HTT TX/RX are subsequent required work. CE5 receive reuse must
   be implemented separately before its HTT receive path is activated.
5. Connect successful real backend operations to existing hakios_sta_ops and
   hakios_net_link, publish the actual IO80211 interface, package wifid with its
   matching device node, then validate association, IP/DNS and packet delivery.
   The existing trial's unconditional shutdown must become a controlled service
   lifetime before these layers can remain usable. Remove readiness and link
   state on PFR; reclaim mappings only at a confirmed hardware stop boundary.

The current first firmware fault still precedes these configuration commands.
This implementation is necessary data-path work, not evidence that missing
WLAN_CFG caused that fault or that Wi-Fi now works.
