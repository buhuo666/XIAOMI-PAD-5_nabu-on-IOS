// SPDX-License-Identifier: BSD-2-Clause-Patent
// Nabu APPS/MPSS GLINK and QRTR control trial. Wire formats: Linux rpmsg/qrtr.
// A single polling owner handles IPCRTR; no cellular or WLAN data requests.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IORegistryEntry.h>
#include <libkern/c++/OSData.h>
#include "NabuSmem.h"
#include "NabuWirelessLog.h"
#include "NabuTftp.h"
#include "NabuServreg.h"
#include "NabuWlfw.h"
#include "NabuDiagFrames.h"
extern "C" bool nabu_rmtfs_available();
extern "C" unsigned nabu_rmtfs_request(const uint8_t *, unsigned, uint8_t *);
extern "C" bool nabu_msa_prepare(const NabuWlfw::Region *,unsigned);

struct GlinkMessage { uint16_t command, channel; uint32_t value; };
struct QrtrHeader { uint32_t version, type, from_node, from_port, confirm, size, to_node, to_port; };
struct QrtrControl { uint32_t command, words[4]; };
static constexpr uint32_t control_port = 0xfffffffe;
static constexpr uint32_t wlfw_service = 0x45;
static constexpr uint32_t diag_service = 0x1001;
static constexpr uint32_t diag_ports[] = {0x4005, 0x4006};
static constexpr uint32_t diag_command_port = 0x4007;
static constexpr unsigned diag_packet_limit = 3, diag_prefix_limit = 32;
static void glink_barrier() { __asm__ volatile("dsb sy" ::: "memory"); }

struct NabuGlink {
    NabuSmem memory;
    volatile uint32_t *doorbell;
    NabuSmemItem descriptor{}, tx{}, rx{};
    uint16_t remote_channel = 0;
    uint32_t features = 1, sent = 0, received = 0, peer = 0, servers = 0, wlfw_node = 0, wlfw_port = 0;
    bool agreed = false, requested = false, acknowledged = false, opened = false, broken = false;
    bool hello_queued = false, hello_replied = false, intent_requested = false, close_ack = false;
    bool peer_seen = false, closing = false;
    const uint8_t *wlan_firmware = nullptr;
    unsigned wlan_bytes = 0, tftp_requests = 0, tftp_completed = 0;
    NabuTftp transfers[2]{};
    NabuServreg registry;
    uint8_t server_check[4096]{};
    unsigned server_check_size = 0;
    bool server_check_valid = false;
    NabuWlfw wlfw;
    bool qmi_enabled = false;
    bool wlan_crash_captured = false;
    uint8_t transmit[8192]{};
    struct RemoteIntent { uint32_t id, size; bool present, used; } remote[64]{};
    struct LocalIntent { uint8_t *data; uint32_t size, fill; } local[16]{};
    unsigned local_count = 0;
    struct Pending { QrtrHeader header; QrtrControl control; } pending[16]{};
    unsigned pending_head = 0, pending_count = 0;
    struct Response { uint32_t node, port, from, bytes; uint8_t data[1024]; } responses[8]{};
    unsigned response_head = 0, response_count = 0;
    struct DiagObservation {
        unsigned packets = 0, captured_packets = 0, source_changes = 0;
        uint32_t source_node = 0, source_port = 0;
        uint64_t bytes = 0, captured_bytes = 0;
    } diag[2]{};
    unsigned diag_servers_queued = 0;
    struct DiagIdentity { char name[30]{}; uint8_t id = 0, kind = 0; } diag_ids[8]{};
    unsigned diag_id_count = 0, diag_control_records = 0, diag_control_invalid = 0;
    unsigned diag_feature_records = 0, diag_id_requests = 0, diag_id_unknown = 0;
    unsigned diag_registration_records = 0, diag_ssid_records = 0, diag_build_records = 0, diag_pd_records = 0;
    unsigned diag_replies_queued = 0, diag_replies_tx = 0, diag_reply_full = 0;
    unsigned diag_feature_mask_bytes = 0, diag_presets = 0;
    uint8_t diag_feature_mask[4]{}, diag_root_id = 0, diag_wlan_id = 0;
    uint32_t diag_control_node = 0, diag_control_port = 0;
    bool diag_feature_queued = false, diag_feature_tx = false, diag_root_id_tx = false;
    bool diag_command_server = false, diag_ulog_registered = false, ulog_route_verified = false;
    uint32_t diag_command_node = 0, diag_command_peer = 0;
    unsigned diag_command_packets = 0, diag_frame_errors = 0, ulog_version_replies = 0;
    unsigned ulog_ticks = 0, ulog_sent_tick = 0, ulog_last_read_tick = 0, ulog_gate_ticks = 0;
    unsigned ulog_stage = 0, ulog_selected = 0, ulog_reads = 0, ulog_empty = 0, ulog_saved_bytes = 0;
    unsigned ulog_first_reads = 0, ulog_overruns = 0, ulog_requests = 0, ulog_omitted_bytes = 0;
    unsigned ulog_connect_index = 0, ulog_connect_attempted = 0;
    uint32_t ulog_handles[2]{};
    uint32_t ulog_log_status[2]{};
    unsigned ulog_status_seen = 0;
    uint16_t ulog_command = 0;
    bool ulog_enabled = false, ulog_waiting = false, ulog_stopped = false, ulog_gate_reported = false;

    void capture_minidump_edge(const char *phase) {
        // Inspect only the public TOC. partition(7) would select APPS/TZ,
        // whereas the original MPSS minidump query selects MODEM/TZ.
        if (memory.length < 4096) {
            nabu_wireless_log("NABU WLAN MINIDUMP TOC: phase=%s edge=1:7 toc-valid=0; metadata only\n", phase); return;
        }
        unsigned toc = memory.length - 4096;
        if (memory.u32(toc) != 0x434f5424 || memory.u32(toc+4) != 1 || memory.u32(toc+8) > (4096-32)/48) {
            nabu_wireless_log("NABU WLAN MINIDUMP TOC: phase=%s edge=1:7 toc-valid=0; metadata only\n", phase); return;
        }
        bool present = false;
        for (unsigned i = 0; i < memory.u32(toc+8); ++i) {
            unsigned at = toc + 32 + 48*i;
            uint16_t first = memory.u16(at+12), second = memory.u16(at+14);
            if (!((first==1&&second==7)||(first==7&&second==1))) continue;
            present = true;
            nabu_wireless_log("NABU WLAN MINIDUMP TOC: phase=%s edge=1:7 toc-valid=1 present=1 entry=%u offset=%#x size=%#x; metadata only\n",
                phase, i, memory.u32(at), memory.u32(at+4));
        }
        if (!present) nabu_wireless_log("NABU WLAN MINIDUMP TOC: phase=%s edge=1:7 toc-valid=1 present=0; metadata only\n", phase);
    }

    void capture_minidump_prefixes(const char *phase) {
        capture_minidump_edge(phase);
        // These are APPS-visible prefixes only. MPSS queries host7 privately;
        // the metadata above does not authorize following that edge's offset.
        const uint16_t ids[] = {602, 618};
        const unsigned limits[] = {64, 32};
        static const char hex[] = "0123456789abcdef";
        for (unsigned which = 0; which < 2; ++which) {
            NabuSmemItem item{};
            bool present = memory.find(ids[which], &item);
            unsigned bytes = present ? (item.size < limits[which] ? item.size : limits[which]) : 0;
            uint8_t copy[64];
            glink_barrier();
            for (unsigned i = 0; i < bytes; ++i) copy[i] = memory.data[item.offset + i];
            nabu_wireless_log("NABU WLAN MINIDUMP: item=%u phase=%s present=%u offset=%#x directory-bytes=%u captured-prefix-bytes=%u prefix-limit=%u search=APPS-MODEM,COMMON\n",
                ids[which], phase, present, item.offset, item.size, bytes, limits[which]);
            for (unsigned at = 0; at < bytes; at += 16) {
                unsigned count = bytes - at < 16 ? bytes - at : 16;
                char line[49]{};
                for (unsigned i = 0; i < count; ++i) {
                    line[3*i] = hex[copy[at+i] >> 4]; line[3*i+1] = hex[copy[at+i] & 15]; line[3*i+2] = ' ';
                }
                nabu_wireless_log("NABU WLAN MINIDUMP: item=%u phase=%s prefix+%#x=%s\n", ids[which], phase, at, line);
            }
        }
    }

    void capture_wlan_crash(const char *phase) {
        NabuSmemItem item{};
        // Original MPSS err_smem_log allocates item 611, 4096 bytes, for APPS.
        // PFR does not guarantee this buffer contains the user-PD exception.
        if (!memory.find(611, &item)) {
            nabu_wireless_log("NABU WLAN CRASH: SMEM item611 absent phase=%s\n", phase); return;
        }
        unsigned bytes = item.size < 4096 ? item.size : 4096;
        uint8_t *copy = (uint8_t *)IOMalloc(bytes);
        if (!copy) return;
        glink_barrier();
        for (unsigned i = 0; i < bytes; ++i) copy[i] = memory.data[item.offset + i];
        IORegistryEntry *chosen = IORegistryEntry::fromPath("/chosen", gIODTPlane);
        char property[64]; snprintf(property, sizeof(property), "nabu-wlan-crash-%s", phase);
        if (chosen) { chosen->setProperty(property, copy, bytes); chosen->release(); }
        nabu_wireless_log("NABU WLAN CRASH: SMEM item611 offset=%#x bytes=%u phase=%s; producer not yet attributed\n", item.offset, bytes, phase);
        for (unsigned at = 0; at < bytes;) {
            unsigned start = at;
            while (at < bytes && copy[at] >= 32 && copy[at] < 127 && at - start < 160) ++at;
            if (at - start >= 5) nabu_wireless_log("NABU WLAN CRASH: item611+%#x text=%.*s\n", start, (int)(at - start), copy + start);
            if (at == start || (at < bytes && (copy[at] < 32 || copy[at] >= 127))) ++at;
        }
        IOFree(copy, bytes);
    }

    bool datagram(unsigned type, unsigned from, unsigned node, unsigned port, const void *data, unsigned size) {
        unsigned total = (sizeof(QrtrHeader) + size + 3) & ~3u;
        if (total > sizeof(transmit)) return false;
        int selected = -1;
        for (unsigned i = 0; i < 64; ++i)
            if (remote[i].present && !remote[i].used && remote[i].size >= total) { selected = i; break; }
        if (selected < 0) {
            if (!intent_requested) { command(7, 1, total); intent_requested = true; }
            return false;
        }
        QrtrHeader qrtr{1, type, 1, from, 0, size, node, port};
        memcpy(transmit, &qrtr, sizeof(qrtr)); memcpy(transmit + sizeof(qrtr), data, size);
        for (unsigned i = sizeof(qrtr) + size; i < total; ++i) transmit[i] = 0;
        struct { GlinkMessage message; uint32_t size, left; } header{{9, 1, remote[selected].id}, total, 0};
        if (!send(&header, sizeof(header), transmit, total)) return false;
        remote[selected].used = true; return true;
    }
    void announce_tftp(unsigned node) {
        if (nabu_rmtfs_available()) { uint32_t server[4] = {14, 1, 1, 0x4001}; queue_control(4, node, control_port, server); }
        if (registry.records) { uint32_t server[4] = {64, 257, 1, 0x4002}; queue_control(4,node,control_port,server); }
        if (!wlan_firmware) return;
        uint32_t server[4] = {4096, 1, 1, 0x4000}; queue_control(4, node, control_port, server);
    }
    void announce_diag(unsigned node) {
        if (!qmi_enabled) return;
        // MiCode diagfwd_socket: APPS serves MODEM control/data packed instances 0/2.
        for (unsigned which = 0; which < 2; ++which) {
            uint32_t server[4] = {diag_service, which * 2, 1, diag_ports[which]};
            queue_control(4, node, control_port, server);
            if (broken) return;
            ++diag_servers_queued;
        }
    }
    void observe_diag(unsigned which, const QrtrHeader &header, const uint8_t *data) {
        DiagObservation &d = diag[which];
        if (d.packets && (d.source_node != header.from_node || d.source_port != header.from_port)) ++d.source_changes;
        d.source_node = header.from_node; d.source_port = header.from_port;
        ++d.packets; d.bytes += header.size;
        if (which == 0) receive_diag_control(header, data);
        if (d.captured_packets == diag_packet_limit) return;
        ++d.captured_packets;
        unsigned bytes = header.size < diag_prefix_limit ? header.size : diag_prefix_limit;
        d.captured_bytes += bytes;
        static const char hex[] = "0123456789abcdef";
        char raw[2 * diag_prefix_limit + 1]{}, first_header[64]{};
        for (unsigned i = 0; i < bytes; ++i) { raw[2*i] = hex[data[i] >> 4]; raw[2*i+1] = hex[data[i] & 15]; }
        if (which == 0) {
            if (header.size >= 8) {
                NabuSmem body{data, header.size};
                snprintf(first_header, sizeof(first_header), "id=%u len=%u fits=%u ", body.u32(0), body.u32(4), body.u32(4) <= header.size - 8);
            } else snprintf(first_header, sizeof(first_header), "header=short ");
        }
        nabu_wireless_log("NABU DIAG: inst=%u packet=%u from=%u:%u bytes=%u %sraw[%u]=%s\n",
            which * 2, d.packets, header.from_node, header.from_port, header.size, first_header, bytes, raw);
    }
    bool queue_diag_reply(const QrtrHeader &header, const uint8_t *data, unsigned bytes) {
        if (response_count == 8) { ++diag_reply_full; return false; }
        Response &r = responses[(response_head + response_count) % 8];
        r.node = header.from_node; r.port = header.from_port; r.from = diag_ports[0]; r.bytes = bytes;
        memcpy(r.data, data, bytes); ++response_count; ++diag_replies_queued; return true;
    }
    static unsigned diag_identity_kind(const char *name, unsigned bytes) {
        const char *names[] = {"modem/root_pd", "wlan_pd", "audio_pd", "sensor_pd"};
        for (unsigned which = 0; which < 4; ++which) {
            unsigned n = strlen(names[which]);
            for (unsigned at = 0; at + n <= bytes; ++at)
                if (!memcmp(name + at, names[which], n)) return which + 1;
        }
        return 0;
    }
    void receive_diag_control(const QrtrHeader &header, const uint8_t *data) {
        NabuSmem packet{data, header.size};
        for (unsigned at = 0; at < header.size;) {
            if (!packet.span(at, 8)) { ++diag_control_invalid; break; }
            unsigned id = packet.u32(at), bytes = packet.u32(at + 4);
            if (!packet.span(at + 8, bytes)) { ++diag_control_invalid; break; }
            NabuSmem body{data + at + 8, bytes}; ++diag_control_records;
            if (id == 8) {
                if (bytes < 4 || body.u32(0) == 0 || body.u32(0) > bytes - 4) { ++diag_control_invalid; }
                else {
                    ++diag_feature_records;
                    bool changed = diag_feature_queued &&
                        (diag_control_node != header.from_node || diag_control_port != header.from_port);
                    if (changed) {
                        bzero(diag_ids, sizeof(diag_ids)); diag_id_count = 0;
                        diag_feature_queued = diag_feature_tx = diag_root_id_tx = false;
                        diag_root_id = diag_wlan_id = 0;
                        diag_ulog_registered = false; retire_ulog();
                        nabu_wireless_log("NABU ULOG: control endpoint changed; old handles retired\n");
                    }
                    diag_control_node = header.from_node; diag_control_port = header.from_port;
                    diag_feature_mask_bytes = body.u32(0); bzero(diag_feature_mask, sizeof(diag_feature_mask));
                    unsigned keep = diag_feature_mask_bytes < 4 ? diag_feature_mask_bytes : 4;
                    for (unsigned i = 0; i < keep; ++i) diag_feature_mask[i] = data[at + 12 + i];
                    if (!diag_feature_queued) {
                        // Original APPS bits 0/4/6/13/15: feature, command channel,
                        // raw frames, sockets and dynamic IDs. No PD chunk tags or F3 masks.
                        const uint8_t reply[] = {8,0,0,0,8,0,0,0,4,0,0,0,0x51,0xa0,0,0};
                        diag_feature_queued = queue_diag_reply(header, reply, sizeof(reply));
                        nabu_wireless_log("NABU DIAG CTRL: feature from=%u:%u remote-bytes=%u remote=%02x%02x%02x%02x local=51a00000 queued=%u; no message masks\n",
                            header.from_node, header.from_port, diag_feature_mask_bytes, diag_feature_mask[0], diag_feature_mask[1],
                            diag_feature_mask[2], diag_feature_mask[3], diag_feature_queued);
                    }
                }
            } else if (id == 12) {
                if (bytes != 1) ++diag_control_invalid;
                else diag_presets = data[at + 8];
            } else if (id == 33) {
                ++diag_id_requests;
                if (bytes < 9 || body.u32(0) != 1) { ++diag_control_invalid; }
                else {
                    unsigned n = 0, capacity = bytes - 8 < 30 ? bytes - 8 : 30;
                    const char *name = (const char *)(data + at + 16);
                    while (n < capacity && name[n]) ++n;
                    if (n == 0 || n == capacity) { ++diag_control_invalid; }
                    else {
                        unsigned kind = diag_identity_kind(name, n), index = 0;
                        while (index < diag_id_count && strcmp(diag_ids[index].name, name)) ++index;
                        if (!kind) {
                            if (++diag_id_unknown <= 4) nabu_wireless_log("NABU DIAG CTRL: diag-id unknown-name=%.*s; not assigned\n", (int)n, name);
                        } else if (diag_feature_queued && header.from_node == diag_control_node && header.from_port == diag_control_port) {
                            if (index == diag_id_count && diag_id_count == 8) { ++diag_reply_full; }
                            else {
                                uint8_t assigned = index < diag_id_count ? diag_ids[index].id : diag_id_count + 2;
                                uint8_t reply[46]{}; uint32_t words[] = {33, 8 + n + 1, 1, assigned};
                                memcpy(reply, words, sizeof(words)); memcpy(reply + 16, name, n + 1);
                                if (queue_diag_reply(header, reply, 16 + n + 1)) {
                                    bool fresh = index == diag_id_count;
                                    if (fresh) {
                                        DiagIdentity &identity = diag_ids[diag_id_count++];
                                        memcpy(identity.name, name, n + 1); identity.id = assigned; identity.kind = kind;
                                        if (kind == 1) diag_root_id = assigned;
                                        if (kind == 2) diag_wlan_id = assigned;
                                        nabu_wireless_log("NABU DIAG CTRL: diag-id queued id=%u kind=%u name=%s root-already-known=%u; assignment only\n",
                                            assigned, kind, identity.name, kind == 1 || diag_root_id != 0);
                                    }
                                }
                            }
                        }
                    }
                }
            } else if (id == 1) {
                ++diag_registration_records;
                bool valid = bytes >= 12 && body.u16(8) == (bytes - 12) / 8 && (bytes - 12) % 8 == 0;
                if (!valid) ++diag_control_invalid;
                if (valid && body.u32(0) == 1 && body.u16(6) == 0x4d &&
                    (body.u16(4) == 0x4b || body.u16(4) == 0xff) &&
                    header.from_node == diag_control_node && header.from_port == diag_control_port) {
                    for (unsigned i = 0; i < body.u16(8); ++i) {
                        unsigned first = body.u16(12 + 8*i), last = body.u16(14 + 8*i);
                        if (first <= 0x900 && last >= 0x905) {
                            diag_ulog_registered = true;
                            nabu_wireless_log("NABU ULOG: WLAN registration cmd=%#x subsys=0x4d range=%#x..%#x port=%u\n",
                                body.u16(4), first, last, body.u16(10));
                        }
                    }
                }
                if (valid && diag_registration_records <= 3)
                    nabu_wireless_log("NABU DIAG CTRL: registration version=%u cmd=%u subsys=%u ranges=%u port=%u; observe only\n",
                        body.u32(0), body.u16(4), body.u16(6), body.u16(8), body.u16(10));
            } else if (id == 27) {
                // Original packed DEREG body has no REG port or per-range data word.
                bool valid = bytes >= 10 && (bytes - 10) % 4 == 0 && body.u16(8) == (bytes - 10) / 4;
                if (!valid) ++diag_control_invalid;
                else if (body.u32(0) == 1 && body.u16(6) == 0x4d &&
                    (body.u16(4) == 0x4b || body.u16(4) == 0xff) &&
                    header.from_node == diag_control_node && header.from_port == diag_control_port) {
                    const uint16_t used[] = {0x900, 0x901, 0x904, 0x905};
                    for (unsigned i = 0; i < body.u16(8); ++i) for (auto command : used) {
                        if (body.u16(10 + i*4) <= command && body.u16(12 + i*4) >= command) {
                            diag_ulog_registered = false; retire_ulog();
                        }
                    }
                    if (ulog_stopped) nabu_wireless_log("NABU ULOG: command range deregistered; retire read handles\n");
                }
            } else if (id == 24 || id == 25) {
                unsigned &records = id == 24 ? diag_ssid_records : diag_build_records; ++records;
                if (bytes < 8) { ++diag_control_invalid; }
                else {
                    unsigned count = body.u32(4), position = 8, valid_ranges = 0;
                    for (; valid_ranges < count; ++valid_ranges) {
                        if (!body.span(position, 4)) break;
                        unsigned first = body.u16(position), last = body.u16(position + 2); position += 4;
                        if (last < first) break;
                        unsigned masks = id == 25 ? last - first + 1 : 0;
                        if (!body.span(position, masks * 4)) break;
                        if (records <= 2 && valid_ranges < 4)
                            nabu_wireless_log("NABU DIAG CTRL: report=%u version=%u range=%u/%u ssid=%u..%u masks=%u first-mask=%#x last-mask=%#x; observe only\n",
                                id, body.u32(0), valid_ranges, count, first, last, masks,
                                masks ? body.u32(position) : 0, masks ? body.u32(position + (masks - 1) * 4) : 0);
                        position += masks * 4;
                    }
                    if (valid_ranges != count || position != bytes) ++diag_control_invalid;
                }
            } else if (id == 30) {
                ++diag_pd_records;
                if (bytes != 9) ++diag_control_invalid;
                else if (diag_pd_records <= 4)
                    nabu_wireless_log("NABU DIAG CTRL: pd-status version=%u pd=%u status=%u; observe only\n", body.u32(0), body.u32(4), data[at + 16]);
            }
            at += 8 + bytes;
        }
    }
    void retire_ulog() {
        ulog_stopped = true; ulog_waiting = false; ulog_route_verified = false;
        bzero(ulog_handles, sizeof(ulog_handles));
    }
    static void ulog_payload_callback(void *context, const uint8_t *data, unsigned bytes) {
        ((NabuGlink *)context)->receive_ulog_payload(data, bytes);
    }
    void dump_ulog_bytes(const uint8_t *data, unsigned bytes, const char *kind, unsigned sequence) {
        static const char hex[] = "0123456789abcdef";
        for (unsigned at = 0; at < bytes; at += 128) {
            unsigned n = bytes - at < 128 ? bytes - at : 128;
            char raw[257];
            for (unsigned i = 0; i < n; ++i) { raw[i*2] = hex[data[at+i] >> 4]; raw[i*2+1] = hex[data[at+i] & 15]; }
            raw[n*2] = 0;
            // Keep bulk records in the persistent console, outside the 32 KiB inventory property.
            IOLog("NABU ULOG DATA: kind=%s sequence=%u at=%u bytes=%u raw=%s\n", kind, sequence, at, n, raw);
        }
    }
    void receive_ulog_payload(const uint8_t *data, unsigned bytes) {
        NabuSmem reply{data, bytes};
        if (!ulog_waiting || ulog_stopped) return;
        if (bytes < 4 || data[0] != 0x4b || data[1] != 0x4d || reply.u16(2) != ulog_command) {
            nabu_wireless_log("NABU ULOG: unexpected reply bytes=%u first=%#x expected=%#x; stopped\n",
                bytes, bytes ? data[0] : 0, ulog_command);
            dump_ulog_bytes(data, bytes < 64 ? bytes : 64, "unexpected", ulog_requests);
            ulog_stopped = true; ulog_waiting = false; return;
        }
        ulog_waiting = false;
        if (bytes < 12) { ulog_stopped = true; return; }
        if (ulog_command == 0x900) {
            nabu_wireless_log("NABU ULOG: version=%u status=%u\n", reply.u32(4), reply.u32(8));
            if (reply.u32(4) != 1 || reply.u32(8)) { ulog_stopped = true; return; }
            ulog_route_verified = true;
            ++ulog_version_replies;
            ulog_stage = 1;
        } else if (ulog_command == 0x904) {
            if (bytes < 20) { ulog_stopped = true; return; }
            nabu_wireless_log("NABU ULOG: list status=%u registered=%u offset=%u names=%u bytes=%u\n",
                reply.u32(4), reply.u32(8), reply.u32(12), reply.u32(16), bytes - 20);
            unsigned saved = bytes - 20 < 1024 ? bytes - 20 : 1024;
            dump_ulog_bytes(data + 20, saved, "names", 0);
            if (saved != bytes - 20) nabu_wireless_log("NABU ULOG: names omitted-bytes=%u\n", bytes - 20 - saved);
            ulog_stage = 2;
        } else if (ulog_command == 0x901) {
            unsigned index = ulog_connect_index;
            if (ulog_stage < 4 || reply.u32(8) != 13 || ulog_requests % 64 == 0)
                nabu_wireless_log("NABU ULOG: connect log=%u handle=%u status=%u step=%u\n",
                    index, reply.u32(4), reply.u32(8), wlfw.step);
            if (!reply.u32(8)) ulog_handles[index] = reply.u32(4);
            ulog_connect_attempted |= 1u << index;
            if (ulog_stage < 4) ++ulog_stage;
            ulog_selected = index ^ 1;
        } else if (ulog_command == 0x905) {
            unsigned status = reply.u32(4), count = reply.u32(8);
            ++ulog_reads;
            if ((status != 1 && status != 3) || count > 1024 || count > bytes - 12) {
                nabu_wireless_log("NABU ULOG: read failed log=%u type=%u count=%u reply-bytes=%u\n", ulog_selected, status, count, bytes);
                ulog_stopped = true; return;
            }
            ulog_first_reads |= 1u << ulog_selected;
            if (status == 3) ++ulog_overruns;
            bool save = count > 4 || status == 3;
            if (count >= 4) {
                unsigned bit = 1u << ulog_selected;
                uint32_t log_status = reply.u32(12);
                save |= !(ulog_status_seen & bit) || ulog_log_status[ulog_selected] != log_status;
                ulog_status_seen |= bit; ulog_log_status[ulog_selected] = log_status;
            }
            if (count <= 4) ++ulog_empty;
            if (save && count > 65536 - ulog_saved_bytes) {
                ulog_omitted_bytes += count; ulog_stopped = true;
                nabu_wireless_log("NABU ULOG: capture budget reached; omitted-bytes=%u\n", count); return;
            }
            if (save) {
                nabu_wireless_log("NABU ULOG: read=%u log=%u type=%u bytes=%u step=%u pfr=%u\n",
                    ulog_reads, ulog_selected, status, count, wlfw.step, wlan_crash_captured);
                dump_ulog_bytes(data + 12, count, "read", ulog_reads); ulog_saved_bytes += count;
            }
            ulog_selected ^= 1;
            if (ulog_saved_bytes >= 65536) ulog_stopped = true;
        }
    }
    void receive_diag_command(const QrtrHeader &header, const uint8_t *data) {
        if (!diag_command_server || header.from_node != diag_command_node || header.from_port != diag_command_peer) return;
        ++diag_command_packets;
        auto result = NabuDiagFrames::parse(data, header.size, ulog_payload_callback, this);
        if (!result.complete()) {
            ++diag_frame_errors; ulog_waiting = false; ulog_stopped = true;
            nabu_wireless_log("NABU ULOG: raw frame error=%u at=%u bytes=%u records=%u; no cross-datagram reassembly\n",
                (unsigned)result.error, result.error_offset, header.size, result.records);
        }
    }
    void send_ulog_command() {
        if (!ulog_enabled || ulog_stopped || ulog_waiting || !diag_command_server ||
            !diag_feature_tx || !diag_root_id_tx || (diag_feature_mask[0] & 0x50) != 0x50) return;
        // Original MPSS dispatches a registered internal handler even before REG is
        // advertised to APPS. Probe only its constant version reply after WLAN QMI
        // appears; later commands require the actual version response or observed REG.
        if (!diag_ulog_registered && !ulog_route_verified && (ulog_stage != 0 || !wlfw_port)) return;
        if (ulog_stage >= 4 && ulog_ticks - ulog_last_read_tick < 5) return;
        if (ulog_requests >= 1024) { ulog_stopped = true; return; }
        uint8_t request[32] = {0x4b, 0x4d}; unsigned bytes = 4;
        if (ulog_stage == 0) ulog_command = 0x900;
        else if (ulog_stage == 1) { ulog_command = 0x904; bytes = 8; }
        else if (ulog_stage < 4 || !ulog_handles[ulog_selected]) {
            ulog_connect_index = ulog_stage < 4 ? ulog_stage - 2 : ulog_selected;
            const char *name = ulog_connect_index == 0 ? "CCPM User LOG" : "CCPM User DEBUG LOG";
            ulog_command = 0x901; bytes = 28; memcpy(request + 4, name, strlen(name) + 1);
        } else {
            ulog_command = 0x905; bytes = 12;
            uint32_t parameters[] = {ulog_handles[ulog_selected], 1};
            memcpy(request + 4, parameters, sizeof(parameters));
        }
        request[2] = ulog_command; request[3] = ulog_command >> 8;
        if (datagram(1, diag_command_port, diag_command_node, diag_command_peer, request, bytes)) {
            ulog_waiting = true; ulog_sent_tick = ulog_ticks; ulog_last_read_tick = ulog_ticks;
            ++ulog_requests;
            if (ulog_stage < 4) nabu_wireless_log("NABU ULOG: request=%#x bytes=%u step=%u registered=%u route-verified=%u\n",
                ulog_command, bytes, wlfw.step, diag_ulog_registered, ulog_route_verified);
        }
    }
    bool hold_cal_for_ulog() {
        if (!ulog_enabled || wlfw.step != 7 || wlfw.rejuvenate_count) return false;
        if (!ulog_gate_ticks) ulog_gate_ticks = ulog_ticks + 1;
        unsigned handles = (ulog_handles[0] ? 1u : 0u) | (ulog_handles[1] ? 2u : 0u);
        bool attempted = ulog_connect_attempted == 3 && (ulog_first_reads & handles) == handles;
        bool release = attempted || ulog_stopped || ulog_ticks + 1 - ulog_gate_ticks >= 2000;
        if (release && !ulog_gate_reported) {
            ulog_gate_reported = true;
            nabu_wireless_log("NABU ULOG: CAL release attempted=%u handles=%u initial-read-mask=%u stopped=%u waited-ticks=%u\n",
                attempted, handles, ulog_first_reads, ulog_stopped, ulog_ticks + 1 - ulog_gate_ticks);
        }
        // A missing ring can depend on CAL itself. A status13 attempt releases CAL;
        // later bounded connect requests can discover a ring created during initialization.
        return !release;
    }
    void tick_ulog() {
        ++ulog_ticks;
        if (ulog_waiting && ulog_ticks - ulog_sent_tick >= 1000) {
            nabu_wireless_log("NABU ULOG: request=%#x timeout; stop capture\n", ulog_command);
            ulog_waiting = false; ulog_stopped = true;
        }
    }
    void diag_summary() {
        nabu_wireless_log("NABU DIAG: service=%u server-queues=%u ports=%#x/%#x packet-limit=%u prefix-limit=%u; bounded transport samples\n",
            diag_service, diag_servers_queued, diag_ports[0], diag_ports[1], diag_packet_limit, diag_prefix_limit);
        nabu_wireless_log("NABU DIAG CTRL: records=%u invalid=%u feature-rx=%u feature-queued=%u feature-tx=%u presets=%u ids=%u id-requests=%u unknown-names=%u root-id=%u root-reply-tx=%u wlan-id=%u replies-queued=%u replies-tx=%u queue-full=%u; command raw frames enabled, PD tags disabled\n",
            diag_control_records, diag_control_invalid, diag_feature_records, diag_feature_queued, diag_feature_tx, diag_presets,
            diag_id_count, diag_id_requests, diag_id_unknown, diag_root_id, diag_root_id_tx, diag_wlan_id,
            diag_replies_queued, diag_replies_tx, diag_reply_full);
        nabu_wireless_log("NABU ULOG: registered=%u command-server=%u replies=%u frame-errors=%u stage=%u stopped=%u reads=%u empty=%u overruns=%u saved-bytes=%u; raw local-log capture\n",
            diag_ulog_registered, diag_command_server, diag_command_packets, diag_frame_errors,
            ulog_stage, ulog_stopped, ulog_reads, ulog_empty, ulog_overruns, ulog_saved_bytes);
        nabu_wireless_log("NABU ULOG: requests=%u omitted-bytes=%u request-limit=1024 capture-limit=65536; repeated empty-ring status suppressed\n",
            ulog_requests, ulog_omitted_bytes);
        nabu_wireless_log("NABU ULOG: route-verified=%u successful-version-replies=%u; only real WLAN 0900 version1/status0 reply qualifies\n",
            ulog_route_verified, ulog_version_replies);
        nabu_wireless_log("NABU DIAG CTRL: registration-records=%u ssid-records=%u build-mask-records=%u pd-status-records=%u; no F3/log/event masks sent\n",
            diag_registration_records, diag_ssid_records, diag_build_records, diag_pd_records);
        for (unsigned which = 0; which < 2; ++which) {
            const DiagObservation &d = diag[which];
            nabu_wireless_log("NABU DIAG: inst=%u packets=%u captured=%u omitted=%u bytes=%llu raw-bytes=%llu omitted-bytes=%llu last=%u:%u changes=%u\n",
                which * 2, d.packets, d.captured_packets, d.packets - d.captured_packets,
                (unsigned long long)d.bytes, (unsigned long long)d.captured_bytes, (unsigned long long)(d.bytes - d.captured_bytes),
                d.source_node, d.source_port, d.source_changes);
        }
    }
    void tftp(unsigned node, unsigned from, unsigned to, const uint8_t *data, unsigned bytes) {
        if (to == 0x4000) {
            for (unsigned i = 0; i < 2; ++i) if (!transfers[i].active && !transfers[i].pending) {
                // Reset in place: aggregate assignment puts a 4 KiB temporary on the kernel stack.
                NabuTftp &t = transfers[i]; bzero(&t, sizeof(t)); t.block_size = 512;
                t.node = node; t.peer_port = from; t.local_port = 0x4010 + i;
                t.write_buffer=server_check;t.write_capacity=sizeof(server_check);
                bool check=bytes>2+strlen("/readwrite/server_check.txt") && !memcmp(data+2,"/readwrite/server_check.txt",strlen("/readwrite/server_check.txt")+1);
                const uint8_t *file=check?(server_check_valid?server_check:nullptr):wlan_firmware;
                unsigned file_bytes=check?server_check_size:wlan_bytes;
                if (t.begin(data, bytes, file, file_bytes)) {
                    ++tftp_requests;
                    if(tftp_requests<=40)nabu_wireless_log("NABU TFTP: request file=%s opcode=%u seek=%u rsize=%u block=%u offered=%u\n", t.name, data[1], t.seek, t.requested, t.block_size, t.file != nullptr || t.writing);
                }
                return;
            }
        } else if (to >= 0x4010 && to < 0x4012) {
            NabuTftp &t = transfers[to - 0x4010];
            if (node == t.node && from == t.peer_port) {
                bool was_complete = t.complete; t.acknowledge(data, bytes);
                if (t.complete && !was_complete) { ++tftp_completed; nabu_wireless_log("NABU TFTP: completed file=%s seek=%u bytes=%u\n", t.name, t.seek, t.delivered); }
            }
        }
    }
    void tftp_flush() {
        if (!opened || broken || closing) return;
        while (response_count) {
            Response &r = responses[response_head];
            if (r.from == diag_ports[0] && (r.node != diag_control_node || r.port != diag_control_port)) {
                response_head = (response_head+1)%8; --response_count; continue;
            }
            if (!datagram(1, r.from, r.node, r.port, r.data, r.bytes)) break;
            if (r.from == diag_ports[0]) {
                ++diag_replies_tx; NabuSmem reply{r.data, r.bytes};
                if (reply.u32(0) == 8) diag_feature_tx = true;
                if (reply.u32(0) == 33 && reply.u32(12) == diag_root_id) diag_root_id_tx = true;
                if (diag_replies_tx <= 4) {
                    nabu_wireless_log("NABU DIAG CTRL TX: sequence=%u to=%u:%u from=%u id=%u bytes=%u; locally transmitted\n",
                        diag_replies_tx, r.node, r.port, r.from, reply.u32(0), r.bytes);
                    dump_ulog_bytes(r.data, r.bytes, "control-tx", diag_replies_tx);
                }
            }
            response_head = (response_head+1)%8; --response_count;
        }
        send_ulog_command();
        for (auto &t : transfers) {
            if (t.pending && datagram(1, t.local_port, t.node, t.peer_port, t.payload, t.payload_bytes)) {
                bool complete=t.complete;t.sent();
                if(t.writing && t.complete && !complete) {
                    server_check_size=t.written;server_check_valid=true;++tftp_completed;
                    nabu_wireless_log("NABU TFTP: server_check saved in RAM bytes=%u\n",server_check_size);
                }
            }
        }
        if(qmi_enabled&&wlfw_port&&!wlfw.waiting&&!wlfw.failed&&!wlfw.complete&&!wlfw.rejuvenate_ack_finished){
            if (hold_cal_for_ulog()) return;
            if(!wlfw.rejuvenate_count&&wlfw.activate&&wlfw.step==3&&!wlfw.permissions_ready){
                wlfw.permissions_ready=nabu_msa_prepare(wlfw.regions,wlfw.region_count);
                if(!wlfw.permissions_ready){wlfw.failed=true;return;}
            }
            if(!wlfw.bytes)wlfw.prepare();
            if(datagram(1,wlfw.local_port(),wlfw_node,wlfw_port,wlfw.request,wlfw.bytes)){
                wlfw.sent();nabu_wireless_log("NABU WLFW: request message=%#x transaction=%u bytes=%u client-port=%#x\n",wlfw.message,wlfw.transaction,wlfw.bytes,wlfw.local_port());
            }
        }
    }

    uint32_t word(unsigned at) { return memory.u32(descriptor.offset + at); }
    void store(unsigned at, uint32_t value) {
        glink_barrier();
        *(volatile uint32_t *)(memory.data + descriptor.offset + at) = value;
        glink_barrier();
    }
    void ring() { *doorbell = 1u << 12; glink_barrier(); }
    unsigned waiting() {
        unsigned head = word(12), tail = word(8);
        if (head >= rx.size || tail >= rx.size) { broken = true; return 0; }
        glink_barrier();
        return (head + rx.size - tail) % rx.size;
    }
    void peek(void *to, unsigned offset, unsigned bytes) {
        unsigned tail = word(8);
        for (unsigned i = 0; i < bytes; ++i) ((uint8_t *)to)[i] = memory.data[rx.offset + (tail + offset + i) % rx.size];
    }
    void advance(unsigned bytes) { store(8, (word(8) + bytes) % rx.size); }
    bool send(const void *header, unsigned header_bytes, const void *data = nullptr, unsigned bytes = 0) {
        unsigned head = word(4), tail = word(0), total = (header_bytes + bytes + 7) & ~7u;
        if (head >= tx.size || tail >= tx.size) { broken = true; return false; }
        unsigned room = tail <= head ? tx.size - head + tail : tail - head;
        if (room < total + 16) return false;
        volatile uint8_t *fifo = const_cast<volatile uint8_t *>(memory.data) + tx.offset;
        for (unsigned i = 0; i < total; ++i)
            fifo[(head + i) % tx.size] = i < header_bytes ? ((const uint8_t *)header)[i] :
                i < header_bytes + bytes ? ((const uint8_t *)data)[i - header_bytes] : 0;
        store(4, (head + total) % tx.size); ring(); sent++;
        return true;
    }
    bool command(uint16_t command, uint16_t channel, uint32_t value, const void *data = nullptr, unsigned bytes = 0) {
        GlinkMessage message{command, channel, value};
        bool ok = send(&message, sizeof(message), data, bytes);
        if (!ok) { broken = true; nabu_wireless_log("NABU GLINK: command=%u could not be queued\n", command); }
        return ok;
    }
    bool offer(unsigned size) {
        if (!size || size > 65536 || local_count == 16) return false;
        uint8_t *data = (uint8_t *)IOMalloc(size);
        if (!data) return false;
        unsigned slot = local_count++;
        local[slot] = {data, size, 0};
        uint32_t pair[2] = {size, slot + 1};
        return command(5, 1, 1, pair, sizeof(pair));
    }
    void queue_control(unsigned command, unsigned node, unsigned port, const uint32_t *words = nullptr, unsigned from_port = control_port) {
        if (pending_count == 16) { broken = true; return; }
        Pending &p = pending[(pending_head + pending_count++) % 16];
        p.header = {1, command, 1, from_port, 0, sizeof(QrtrControl), node, port};
        p.control = {command, {0, 0, 0, 0}};
        if (words) memcpy(p.control.words, words, sizeof(p.control.words));
    }
    void flush() {
        while (opened && pending_count && !broken) {
            int selected = -1;
            for (unsigned i = 0; i < 64; ++i)
                if (remote[i].present && !remote[i].used && remote[i].size >= sizeof(Pending)) { selected = i; break; }
            if (selected < 0) {
                if (!intent_requested) { command(7, 1, sizeof(Pending)); intent_requested = true; }
                return;
            }
            struct { GlinkMessage message; uint32_t size, left; } header{{9, 1, remote[selected].id}, sizeof(Pending), 0};
            if (!send(&header, sizeof(header), &pending[pending_head], sizeof(Pending))) return;
            remote[selected].used = true;
            pending_head = (pending_head + 1) % 16; pending_count--;
        }
    }
    void qrtr(const uint8_t *data, unsigned size) {
        NabuSmem packet{data, size}; QrtrHeader header{}; unsigned at;
        if (size >= 32 && packet.u32(0) == 1) { memcpy(&header, data, 32); at = 32; }
        else if (size >= 16 && data[0] == 3) {
            header.type = data[1]; header.confirm = data[2] & 1; header.size = packet.u32(4);
            header.from_node = packet.u16(8); header.from_port = packet.u16(10);
            header.to_node = packet.u16(12); header.to_port = packet.u16(14); at = 16 + data[3];
            if (header.from_port == 0xfffe) header.from_port = control_port;
            if (header.to_port == 0xfffe) header.to_port = control_port;
        } else { nabu_wireless_log("NABU QRTR: unsupported packet bytes=%u\n", size); return; }
        bool diag_packet = qmi_enabled && header.type == 1 &&
            (header.to_port == diag_ports[0] || header.to_port == diag_ports[1] || header.to_port == diag_command_port);
        if (!packet.span(at, header.size) || (header.size < 4 && !diag_packet)) return;
        if (!peer_seen) { peer = header.from_node; peer_seen = true; }
        if (header.confirm) {
            uint32_t words[4] = {header.to_node, header.to_port, 0, 0};
            queue_control(7, header.from_node, header.from_port, words, header.to_port);
        }
        if (diag_packet) {
            if (header.to_port == diag_command_port) receive_diag_command(header, data + at);
            else observe_diag(header.to_port == diag_ports[1], header, data + at);
            return;
        }
        unsigned command = packet.u32(at);
        if (header.to_port != control_port && header.type == 1) {
            if(qmi_enabled&&(header.to_port==0x4003||header.to_port==0x4004)&&header.from_node==wlfw_node&&header.from_port==wlfw_port){
                const uint8_t *qmi=data+at;
                if(header.size>=7&&qmi[0]==4){
                    unsigned pin_count=wlfw.pin_result_count;
                    unsigned rejuvenate_count=wlfw.rejuvenate_count;
                    wlfw.receive(qmi,header.size);
                    nabu_wireless_log("NABU WLFW: indication message=%#x bytes=%u\n",NabuRmtfs::u16(qmi+3),header.size);
                    if(wlfw.pin_result_count!=pin_count)nabu_wireless_log("NABU WLFW: pin-connect count=%u step=%u request=%#x waiting=%u client-port=%#x pwr-valid=%u pwr=%#x phy-io-valid=%u phy-io=%#x rf-valid=%u rf=%#x\n",
                        wlfw.pin_result_count,wlfw.pin_result_step,wlfw.message,wlfw.waiting,header.to_port,
                        wlfw.pin_result_valid[0],wlfw.pin_result[0],wlfw.pin_result_valid[1],wlfw.pin_result[1],wlfw.pin_result_valid[2],wlfw.pin_result[2]);
                    if(wlfw.rejuvenate_count!=rejuvenate_count)nabu_wireless_log("NABU WLFW: rejuvenate count=%u step=%u client-port=%#x cause-valid=%u cause=%#x subsystem-valid=%u subsystem=%#x line-valid=%u line=%u function-valid=%u function=%s; initialization stopped, KNEL ACK pending\n",
                        wlfw.rejuvenate_count,wlfw.rejuvenate_step,header.to_port,wlfw.rejuvenate_valid[0],wlfw.rejuvenate_cause,wlfw.rejuvenate_valid[1],wlfw.rejuvenate_subsystem,
                        wlfw.rejuvenate_valid[2],wlfw.rejuvenate_line,wlfw.rejuvenate_valid[3],wlfw.rejuvenate_function);
                }
                else if(wlfw.receive(qmi,header.size)){
                    unsigned n=0;const uint8_t *result=NabuRmtfs::tlv(qmi,header.size,2,n);
                    nabu_wireless_log("NABU WLFW: response message=%#x result=%u error=%u\n",NabuRmtfs::u16(qmi+3),result?NabuRmtfs::u16(result):65535,result?NabuRmtfs::u16(result+2):65535);
                    if(wlfw.message==0x2d)for(unsigned i=0;i<wlfw.region_count;++i)nabu_wireless_log("NABU WLFW: MSA region=%u address=%#llx size=%#x secure=%u\n",i,wlfw.regions[i].address,wlfw.regions[i].size,wlfw.regions[i].secure);
                    if(wlfw.message==0x24&&wlfw.capability_valid)nabu_wireless_log("NABU WLFW: chip=%#x family=%#x board=%#x soc=%#x fw=%#x build=%s\n",wlfw.chip_id,wlfw.chip_family,wlfw.board_id,wlfw.soc_id,wlfw.fw_version,wlfw.build_id);
                    if(wlfw.message==0x24)nabu_wireless_log("NABU WLFW: board-id-valid=%u\n",wlfw.board_id_valid);
                    if(wlfw.board_sent)nabu_wireless_log("NABU WLFW: board-data acknowledged=%u/%u segments=%u\n",wlfw.board_sent,wlfw.board_bytes,wlfw.board_segment);
                    if(wlfw.message==0x20)nabu_wireless_log("NABU WLFW: status valid=%u flags=%#llx\n",wlfw.status_valid,wlfw.fw_status);
                    if(wlfw.message==0x3b)nabu_wireless_log("NABU WLFW: dynamic-feature requested=0x1 previous-valid=%u previous=%#llx current-valid=%u current=%#llx\n",
                        wlfw.dynamic_prev_valid,wlfw.dynamic_prev,wlfw.dynamic_current_valid,wlfw.dynamic_current);
                    if(wlfw.message==0x3a)nabu_wireless_log("NABU WLFW: rejuvenate ACK finished=%u success=%u; ending trial without data-path restart\n",wlfw.rejuvenate_ack_finished,wlfw.rejuvenate_ack_success);
                }
                return;
            }
            if (header.to_port == 0x4001 && nabu_rmtfs_available()) {
                if (response_count == 8) { broken = true; return; }
                Response &r = responses[(response_head+response_count)%8]; r.node = header.from_node; r.port = header.from_port;r.from=0x4001;
                r.bytes = nabu_rmtfs_request(data+at, header.size, r.data); if (r.bytes) ++response_count;
                return;
            }
            if(header.to_port==0x4002 && registry.records) {
                if(response_count==8){broken=true;return;}
                Response &r=responses[(response_head+response_count)%8];r.node=header.from_node;r.port=header.from_port;r.from=0x4002;
                r.bytes=registry.answer(data+at,header.size,r.data);if(r.bytes)++response_count;
                unsigned name_bytes=0;const uint8_t *name=NabuRmtfs::tlv(data+at,header.size,1,name_bytes);
                nabu_wireless_log("NABU SERVREG: request=%#x service=%.*s reply-bytes=%u\n",NabuRmtfs::u16(data+at+3),name?(int)name_bytes:0,name?(const char*)name:"",r.bytes);
                if(NabuRmtfs::u16(data+at+3)==0x24){
                    unsigned reason_bytes=0;const uint8_t *reason=NabuRmtfs::tlv(data+at,header.size,2,reason_bytes);
                    nabu_wireless_log("NABU SERVREG: PFR from=%u:%u service=%.*s reason=%.*s\n",header.from_node,header.from_port,name?(int)name_bytes:0,name?(const char*)name:"",reason?(int)reason_bytes:0,reason?(const char*)reason:"");
                    if(name && name_bytes == 12 && !memcmp(name, "wlan_process", 12) && !wlan_crash_captured) {
                        retire_ulog();
                        nabu_wireless_log("NABU ULOG: WLAN PFR; retire read handles and stop new commands\n");
                        wlan_crash_captured = true; capture_wlan_crash("pfr");
                        capture_minidump_prefixes("pfr");
                    }
                }
                return;
            }
            if (wlan_firmware && header.to_port >= 0x4000 && header.to_port <= 0x4011) {
                tftp(header.from_node, header.from_port, header.to_port, data + at, header.size); return;
            }
            nabu_wireless_log("NABU QRTR: data from=%u:%u to-port=%u bytes=%u\n", header.from_node, header.from_port, header.to_port, header.size);
            return;
        }
        if (command == 2 && !hello_replied) {
            hello_replied = true; queue_control(2, header.from_node, control_port);
            announce_tftp(header.from_node);
            announce_diag(header.from_node);
            nabu_wireless_log("NABU QRTR: HELLO from node=%u\n", header.from_node);
        } else if ((command == 4 || command == 5) && header.size >= 20) {
            uint32_t service = packet.u32(at + 4), instance = packet.u32(at + 8);
            uint32_t node = packet.u32(at + 12), port = packet.u32(at + 16);
            if (service && command == 4) servers++;
            nabu_wireless_log("NABU QRTR: %s service=%u version=%u instance=%u node=%u port=%u\n", command == 4 ? "server" : "removed", service, instance & 255, instance >> 8, node, port);
            if (service == diag_service && instance == 1) {
                if (command == 4) {
                    if (diag_command_server && (diag_command_node != node || diag_command_peer != port)) retire_ulog();
                    diag_command_server = true; diag_command_node = node; diag_command_peer = port;
                } else if (diag_command_node == node && diag_command_peer == port) {
                    diag_command_server = false; retire_ulog();
                }
            }
            if (service == wlfw_service && command == 4) {
                if(wlfw_port&&(wlfw_node!=node||wlfw_port!=port)) {
                    nabu_wireless_log("NABU WLFW: endpoint changed old=%u:%u new=%u:%u step=%u complete=%u\n",wlfw_node,wlfw_port,node,port,wlfw.step,wlfw.complete);
                    if(wlan_crash_captured) { capture_wlan_crash("restart"); retire_ulog(); }
                    if(wlfw.rejuvenate_count){wlfw.failed=true;wlfw.waiting=false;wlfw.bytes=0;nabu_wireless_log("NABU WLFW: rejuvenate ACK cancelled after endpoint change; ending trial\n");}
                }
                wlfw_node = node; wlfw_port = port;
            } else if(service==wlfw_service&&command==5&&node==wlfw_node&&port==wlfw_port&&wlfw.rejuvenate_count) {
                wlfw.failed=true;wlfw.waiting=false;wlfw.bytes=0;wlfw_port=0;
                nabu_wireless_log("NABU WLFW: rejuvenate ACK cancelled after endpoint removal; ending trial\n");
            }
        } else if (command == 10 && header.size >= 20) {
            nabu_wireless_log("NABU QRTR: peer lookup service=%u instance=%#x\n", packet.u32(at + 4), packet.u32(at + 8));
            if (packet.u32(at+4) == 0 || packet.u32(at+4) == 4096 || packet.u32(at+4) == 14 || packet.u32(at+4)==64) announce_tftp(header.from_node);
            if (packet.u32(at+4) == 0 || packet.u32(at+4) == diag_service) announce_diag(header.from_node);
            queue_control(4, header.from_node, header.from_port);
        } else if (command == 3) {
            nabu_wireless_log("NABU QRTR: peer BYE\n"); broken = true;
        }
    }
    void pump() {
        for (unsigned round = 0; round < 512 && !broken; ++round) {
            unsigned available = waiting();
            if (available < 8) break;
            GlinkMessage message; peek(&message, 0, 8);
            unsigned bytes = 8; uint32_t fragment[2]{};
            if (message.command == 2) {
                unsigned name_bytes = message.value & 0xffff;
                if (name_bytes > rx.size - 16) { broken = true; break; }
                bytes += name_bytes;
            } else if (message.command == 5) {
                if (message.value > (rx.size - 16) / 8) { broken = true; break; }
                bytes += 8 * message.value;
            } else if (message.command == 9 || message.command == 12) {
                if (available < 16) break;
                peek(fragment, 8, 8);
                if (fragment[0] > rx.size - 24) { broken = true; break; }
                bytes = 16 + fragment[0];
            }
            bytes = (bytes + 7) & ~7u;
            if (available < bytes) break;
            received++;
            if (message.command != 9 && message.command != 12 && message.command != 14 && received <= 80)
                nabu_wireless_log("NABU GLINK: RX command=%u channel=%u value=%#x\n", message.command, message.channel, message.value);
            switch (message.command) {
            case 0:
                features &= message.value; advance(bytes); command(1, 1, features); break;
            case 1:
                advance(bytes);
                if (message.channel == 1 && message.value == features) agreed = true;
                else if (message.channel) { features &= message.value; command(0, 1, features); }
                break;
            case 2: {
                char name[64]{}; unsigned length = message.value & 0xffff;
                peek(name, 8, length < sizeof(name) - 1 ? length : sizeof(name) - 1); advance(bytes);
                nabu_wireless_log("NABU GLINK: remote OPEN name=%s channel=%u\n", name, message.channel);
                if (!strcmp(name, "IPCRTR")) { remote_channel = message.channel; command(4, remote_channel, 0); }
                break;
            }
            case 4:
                advance(bytes); if (message.channel == 1) acknowledged = true; break;
            case 5:
                if (message.channel == remote_channel) for (unsigned i = 0; i < message.value; ++i) {
                    uint32_t pair[2]; peek(pair, 8 + 8 * i, 8);
                    for (unsigned n = 0; n < 64; ++n) if (!remote[n].present || remote[n].id == pair[1]) {
                        remote[n] = {pair[1], pair[0], true, false}; break;
                    }
                }
                advance(bytes); intent_requested = false; break;
            case 6: case 14:
                if (message.channel == remote_channel) for (auto &intent : remote) if (intent.present && intent.id == message.value) {
                    intent.used = false; intent.present = message.command == 14;
                }
                advance(bytes); break;
            case 7: {
                advance(bytes);
                if (message.channel == remote_channel) { bool granted = offer(message.value); command(8, 1, granted); }
                break;
            }
            case 8:
                advance(bytes); if (!message.value) { broken = true; nabu_wireless_log("NABU GLINK: remote refused TX intent\n"); } break;
            case 9: case 12: {
                unsigned id = message.value;
                if (message.channel != remote_channel || !id || id > local_count || fragment[0] > local[id-1].size - local[id-1].fill) {
                    broken = true; nabu_wireless_log("NABU GLINK: invalid RX fragment channel=%u intent=%u bytes=%u\n", message.channel, id, fragment[0]); break;
                }
                LocalIntent &intent = local[id-1]; peek(intent.data + intent.fill, 16, fragment[0]); intent.fill += fragment[0]; advance(bytes);
                if (!fragment[1]) {
                    qrtr(intent.data, intent.fill); intent.fill = 0;
                    command(features & 1 ? 14 : 6, 1, id);
                    if (!(features & 1)) { uint32_t pair[2] = {intent.size, id}; command(5, 1, 1, pair, 8); }
                }
                break;
            }
            case 13: advance(bytes); ring(); break;
            case 3:
                advance(bytes); command(11, message.channel, 0);
                if (message.channel == remote_channel) { opened = false; if (!closing) broken = true; } break;
            case 11: advance(bytes); if (message.channel == 1) close_ack = true; break;
            case 15: advance(bytes); break;
            default:
                nabu_wireless_log("NABU GLINK: unsupported command=%u\n", message.command); broken = true; break;
            }
            if (agreed && !requested) { command(2, 1, 7, "IPCRTR", 7); requested = true; }
            if (remote_channel && acknowledged && !opened && !broken && !closing) {
                opened = true; nabu_wireless_log("NABU GLINK: IPCRTR open local=1 remote=%u\n", remote_channel);
                for (unsigned i = 0; i < 4; ++i) if (!offer(8192)) { broken = true; break; }
                if (!hello_queued) { queue_control(2, 0xffffffff, control_port); hello_queued = true; }
            }
            flush();
            tftp_flush();
        }
        flush();
        tftp_flush();
    }
    void release() { for (unsigned i = 0; i < local_count; ++i) IOFree(local[i].data, local[i].size); }
};

extern "C" void nabu_glink_trial(vm_offset_t smem, vm_offset_t ipc) {
    NabuGlink *link = (NabuGlink *)IOMalloc(sizeof(NabuGlink));
    if (!link) return;
    // All state belongs to this one bounded trial; no interrupt callback retains it.
    // The remaining nonzero WLFW default is board_id; avoid a 6 KiB temporary.
    bzero(link, sizeof(*link)); link->features = 1; link->wlfw.board_id = 0xff;
    link->memory = {(const volatile uint8_t *)smem, 0x200000}; link->doorbell = (volatile uint32_t *)ipc;
    IORegistryEntry *chosen = IORegistryEntry::fromPath("/chosen", gIODTPlane);
    if(chosen){
        OSData *mac=OSDynamicCast(OSData,chosen->getProperty("mac-address-wifi0"));
        if(mac&&mac->getLength()==6){memcpy(link->wlfw.mac_address,mac->getBytesNoCopy(),6);link->wlfw.mac_available=true;}
        chosen->release();
    }
    IORegistryEntry *firmware_entry = IORegistryEntry::fromPath("/nabu-modem", gIODTPlane);
    if (firmware_entry) {
        OSData *firmware = OSDynamicCast(OSData, firmware_entry->getProperty("wlanmdsp"));
        if (firmware) { link->wlan_firmware = (const uint8_t *)firmware->getBytesNoCopy(); link->wlan_bytes = firmware->getLength(); }
        OSData *registry=OSDynamicCast(OSData,firmware_entry->getProperty("servreg"));
        if(registry)link->registry.load((const uint8_t*)registry->getBytesNoCopy(),registry->getLength());
        link->qmi_enabled=firmware_entry->getProperty("wlfw-qmi")!=nullptr;
        link->wlfw.activate=firmware_entry->getProperty("wlfw-msa")!=nullptr;
        OSData *board=OSDynamicCast(OSData,firmware_entry->getProperty("wlfw-board"));
        if(board){link->wlfw.board_data=(const uint8_t*)board->getBytesNoCopy();link->wlfw.board_bytes=board->getLength();}
        link->ulog_enabled = link->qmi_enabled && link->wlfw.board_data;
    }
    if(link->qmi_enabled) link->capture_minidump_prefixes("pre-glink");
    if (!link->memory.find(478, &link->descriptor) || link->descriptor.size != 32 ||
        !link->memory.find(479, &link->tx) || !link->memory.find(480, &link->rx) ||
        link->tx.size != 16384 || link->rx.size != 16384) {
        nabu_wireless_log("NABU GLINK: descriptor or 16 KiB queues unavailable\n");
        if (firmware_entry) firmware_entry->release(); IOFree(link, sizeof(*link)); return;
    }
    nabu_wireless_log("NABU GLINK: queues ready tx-head=%u rx-head=%u; begin version1\n", link->word(4), link->word(12));
    link->command(0, 1, 1);
    for (unsigned i = 0; i < 30000 && !link->broken; ++i) {
        link->pump(); for (auto &t : link->transfers) t.tick(); link->wlfw.tick(); link->tick_ulog(); IOSleep(1);
        if(link->wlfw.rejuvenate_count&&(link->wlfw.rejuvenate_ack_finished||link->wlfw.failed))break;
    }
    bool was_open = link->opened;
    if (link->opened && !link->broken) {
        link->closing = true;
        link->command(3, 1, 0);
        for (unsigned i = 0; i < 100 && !link->close_ack && !link->broken; ++i) { link->pump(); IOSleep(10); }
    }
    nabu_wireless_log("NABU GLINK: trial complete agreed=%u open=%u broken=%u tx=%u rx=%u close-ack=%u\n", link->agreed, was_open, link->broken, link->sent, link->received, link->close_ack);
    nabu_wireless_log("NABU QRTR: inventory peer=%u servers=%u WLFW-node=%u WLFW-port=%u; WLAN data path not started\n", link->peer, link->servers, link->wlfw_node, link->wlfw_port);
    if (link->qmi_enabled) link->diag_summary();
    nabu_wireless_log("NABU TFTP: requests=%u completed=%u firmware-bytes=%u\n", link->tftp_requests, link->tftp_completed, link->wlan_bytes);
    nabu_wireless_log("NABU SERVREG: records=%u requests=%u\n",link->registry.count,link->registry.requests);
    if(link->qmi_enabled)nabu_wireless_log("NABU WLFW: complete=%u failed=%u waiting=%u step=%u regions=%u permissions=%u msa-ready=%u\n",link->wlfw.complete,link->wlfw.failed,link->wlfw.waiting,link->wlfw.step,link->wlfw.region_count,link->wlfw.permissions_ready,link->wlfw.msa_ready);
    if(link->wlfw.board_data)nabu_wireless_log("NABU WLFW: board-bytes=%u fw-ready-indication=%u init-done=%u registration-status=%#llx\n",link->wlfw.board_sent,link->wlfw.fw_ready,link->wlfw.init_done,link->wlfw.fw_status);
    if(link->wlfw.board_data)nabu_wireless_log("NABU WLFW: board-MAC available=%u applied=%u\n",link->wlfw.mac_available,link->wlfw.mac_set);
    if(link->qmi_enabled)nabu_wireless_log("NABU WLFW: pin-connect indications=%u last-step=%u\n",link->wlfw.pin_result_count,link->wlfw.pin_result_step);
    if(link->qmi_enabled)nabu_wireless_log("NABU WLFW: dynamic-feature-complete=%u rejuvenate=%u ack-finished=%u ack-success=%u\n",link->wlfw.dynamic_feature_complete,link->wlfw.rejuvenate_count,link->wlfw.rejuvenate_ack_finished,link->wlfw.rejuvenate_ack_success);
    if(link->wlan_crash_captured) link->capture_wlan_crash("end");
    if(link->qmi_enabled) link->capture_minidump_prefixes("end");
    if (firmware_entry) firmware_entry->release();
    link->release(); IOFree(link, sizeof(*link));
}
