// SPDX-License-Identifier: BSD-2-Clause-Patent
// Bounded Nabu host-2 GLINK/APR core readiness/version probe. No AFE or PCM commands.
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace NabuAdspGlink {
enum Error : uint32_t { NoError, InvalidQueues, InvalidPointer, InvalidFrame,
    UnknownCommand, TxFull, VersionRejected, IntentUnavailable, FragmentMismatch, Aborted };
enum IntentInvalidReason : uint32_t { IntentValid = 0, IntentZeroSize = 2 };
struct ServiceVersion { uint32_t id, api, branch; };
struct Result {
    bool negotiated, opened, remote_open, local_open_ack, apr_sent, apr_response, apr_ready;
    bool close_sent, close_ack, remote_closed, broken, timeout;
    uint32_t features, lcid, rcid, token, apr_state, tx, rx, unknown_channels, error;
    uint32_t queries, apr_packets, apr_ignored, basic_responses, basic_status;
    uint32_t last_command, last_cid, last_value;
    uint32_t apr_field, apr_type, matched_opcode, matched_token;
    uint32_t peer_intents, last_peer_iid, last_peer_size, intent_invalid_reason;
    uint32_t peer_uncached, peer_replaced;
    bool version_sent, version_response, version_basic_response, version_timeout;
    uint32_t version_token, version_status, version_field, version_type, version_invalid;
    uint32_t build_version[4], service_count;
    ServiceVersion services[25];
    bool map_sent, map_response, map_basic_response, map_timeout;
    bool unmap_sent, unmap_response, unmap_timeout;
    uint32_t map_token, map_handle, map_status, unmap_token, unmap_status;
};

template<class IO> class Link {
    struct LocalIntent { uint8_t data[512]; uint32_t fill, remaining; };
    struct RemoteIntent { uint32_t id, size; bool present, used; };
    enum Phase { Idle, Opening, Querying, VersionQuerying, Mapping, Unmapping, Closing, Finished };
    IO &io;
    Result r{};
    LocalIntent local[20]{};
    // A bounded cache for this GET_STATE probe, not a peer protocol limit.
    RemoteIntent remote[64]{};
    static constexpr uint32_t QueryBytes = 20;
    Phase phase = Idle;
    uint32_t descriptor = 0, tx = 0, tx_bytes = 0, rx = 0, rx_bytes = 0;
    uint32_t now = 0, phase_start = 0, query_start = 0, query_due = 0, next_token = 1;
    bool requested_open = false, offered = false, channel_open = false;
    bool waiting_query = false, requested_intent = false;
    bool include_versions = false;
    uint32_t active_token = 0, active_opcode = 0;
    uint32_t active_service = 3, map_bytes = 0;
    uint64_t map_address = 0;
    uint32_t needed_bytes() const { return phase == Mapping ? 40 : phase == Unmapping ? 24 : QueryBytes; }

    static uint16_t get16(const uint8_t *p) { return uint16_t(p[0]) | uint16_t(p[1]) << 8; }
    static uint32_t get32(const uint8_t *p) { return uint32_t(get16(p)) | uint32_t(get16(p + 2)) << 16; }
    static void set16(uint8_t *p, uint16_t v) { p[0] = uint8_t(v); p[1] = uint8_t(v >> 8); }
    static void set32(uint8_t *p, uint32_t v) { set16(p, uint16_t(v)); set16(p + 2, uint16_t(v >> 16)); }
    static uint32_t align8(uint32_t n) { return (n + 7) & ~7u; }
    void fail(Error error) { r.broken = true; r.error = error; phase = Finished; channel_open = false; }
    uint32_t word(uint32_t at) { return io.read32(descriptor + at); }
    void store(uint32_t at, uint32_t value) { io.write32(descriptor + at, value); }
    uint32_t available() {
        uint32_t head = word(12), tail = word(8);
        if (head >= rx_bytes || tail >= rx_bytes || ((head | tail) & 7)) { fail(InvalidPointer); return 0; }
        return (head + rx_bytes - tail) % rx_bytes;
    }
    void peek(uint8_t *out, uint32_t offset, uint32_t bytes) {
        uint32_t tail = word(8);
        for (uint32_t i = 0; i < bytes; ++i) out[i] = io.read8(rx + (tail + offset + i) % rx_bytes);
    }
    void advance(uint32_t bytes) { store(8, (word(8) + bytes) % rx_bytes); }
    bool send(uint16_t command, uint16_t cid, uint32_t value,
        const uint8_t *extra = nullptr, uint32_t extra_bytes = 0) {
        uint32_t head = word(4), tail = word(0), bytes = align8(8 + extra_bytes);
        if (head >= tx_bytes || tail >= tx_bytes || ((head | tail) & 7)) { fail(InvalidPointer); return false; }
        uint32_t room = tail <= head ? tx_bytes - head + tail : tail - head;
        if (bytes + 16 > room) { fail(TxFull); return false; }
        uint8_t header[8]; set16(header, command); set16(header + 2, cid); set32(header + 4, value);
        for (uint32_t i = 0; i < bytes; ++i)
            io.write8(tx + (head + i) % tx_bytes, i < 8 ? header[i] : i - 8 < extra_bytes ? extra[i - 8] : 0);
        store(4, (head + bytes) % tx_bytes); io.ring(); ++r.tx; return true;
    }
    void offer_all() {
        uint8_t pairs[160];
        for (unsigned i = 0; i < 20; ++i) { set32(pairs + i * 8, 512); set32(pairs + i * 8 + 4, i + 1); }
        offered = send(5, uint16_t(r.lcid), 20, pairs, sizeof(pairs));
    }
    void finish_rx(uint32_t id) {
        LocalIntent &intent = local[id - 1]; intent.fill = intent.remaining = 0;
        send(r.features & 1 ? 14 : 6, uint16_t(r.lcid), id);
        if (!(r.features & 1) && !r.broken) {
            uint8_t pair[8]; set32(pair, 512); set32(pair + 4, id);
            send(5, uint16_t(r.lcid), 1, pair, sizeof(pair));
        }
    }
    void apr(const uint8_t *data, uint32_t bytes) {
        ++r.apr_packets;
        if (bytes < 20) { ++r.apr_ignored; return; }
        uint16_t field = get16(data), packet_bytes = get16(data + 2);
        uint32_t header_bytes = ((field >> 4) & 15) * 4, token = get32(data + 12), opcode = get32(data + 16);
        if ((field & 15) > 1 || header_bytes < 20 || packet_bytes < header_bytes || packet_bytes > bytes ||
            data[4] != active_service || data[5] != 4 || get16(data + 6) != 0 ||
            data[8] != active_service || data[9] != 5 || get16(data + 10) != 0 ||
            !waiting_query || token != active_token) { ++r.apr_ignored; return; }
        uint32_t payload = packet_bytes - header_bytes;
        if (phase == Querying && opcode == 0x1290d && payload >= 4) {
            r.apr_field = field; r.apr_type = (field >> 8) & 3; r.matched_opcode = opcode; r.matched_token = token;
            r.apr_state = get32(data + header_bytes); r.apr_response = true; r.apr_ready = r.apr_state != 0;
            waiting_query = false; query_due = now + 50;
        } else if (phase == VersionQuerying && opcode == 0x1292d) {
            r.version_field = field; r.version_type = (field >> 8) & 3;
            waiting_query = false;
            // Original AVCS layout: four build words, count, then triples.
            // The vendor exposes at most 25 services; preserve unknown IDs.
            if (payload < 20) { r.version_invalid = 1; return; }
            uint32_t count = get32(data + header_bytes + 16);
            if (count > 25) { r.version_invalid = 2; return; }
            if (payload < 20 + count * 12) { r.version_invalid = 3; return; }
            for (unsigned i = 0; i < 4; ++i) r.build_version[i] = get32(data + header_bytes + i * 4);
            r.service_count = count;
            for (unsigned i = 0; i < count; ++i) {
                const uint8_t *entry = data + header_bytes + 20 + i * 12;
                r.services[i] = {get32(entry), get32(entry + 4), get32(entry + 8)};
            }
            r.version_response = true;
        } else if (phase == Mapping && opcode == 0x10d93 && payload >= 4) {
            r.map_handle = get32(data + header_bytes);
            if (r.map_handle) { r.map_response = true; waiting_query = false; }
            else ++r.apr_ignored;
        } else if (opcode == 0x110e8 && payload >= 8 && get32(data + header_bytes) == active_opcode) {
            if (phase == Mapping) {
                r.map_basic_response = true; r.map_status = get32(data + header_bytes + 4);
                // Basic success does not supply the required mapping handle.
                if (!r.map_status) return;
            } else if (phase == Unmapping) {
                r.unmap_status = get32(data + header_bytes + 4); r.unmap_response = true;
            } else if (phase == VersionQuerying) {
                r.version_field = field; r.version_type = (field >> 8) & 3;
                r.version_basic_response = true; r.version_status = get32(data + header_bytes + 4);
            } else {
                r.apr_field = field; r.apr_type = (field >> 8) & 3; r.matched_opcode = opcode; r.matched_token = token;
                ++r.basic_responses; r.basic_status = get32(data + header_bytes + 4);
            }
            // A basic response is neither a ready answer nor a service list.
            waiting_query = false; query_due = now + 50;
        } else ++r.apr_ignored;
    }
    void start_close() {
        if (phase == Closing || phase == Finished) return;
        phase = Closing; phase_start = now; waiting_query = false; channel_open = false;
        if (requested_open) r.close_sent = send(3, uint16_t(r.lcid), 0);
        else phase = Finished;
    }
    void pump() {
        for (unsigned round = 0; round < 64 && !r.broken; ++round) {
            uint32_t avail = available(); if (r.broken || avail < 8) return;
            uint8_t header[16]{}; peek(header, 0, 8);
            uint16_t command = get16(header), cid = get16(header + 2);
            uint32_t value = get32(header + 4), bytes = 8, chunk = 0, left = 0;
            if (command == 2) {
                if (!value || value > rx_bytes - 16) { fail(InvalidFrame); return; }
                bytes += value;
            } else if (command == 5) {
                if (value > (rx_bytes - 16) / 8) { fail(InvalidFrame); return; }
                bytes += value * 8;
            } else if (command == 9 || command == 12) {
                if (avail < 16) return;
                peek(header + 8, 8, 8); chunk = get32(header + 8); left = get32(header + 12);
                if (chunk > rx_bytes - 24) { fail(InvalidFrame); return; }
                bytes = 16 + chunk;
            }
            bytes = align8(bytes); if (avail < bytes) return;
            ++r.rx; r.last_command = command; r.last_cid = cid; r.last_value = value;
            switch (command) {
            case 0:
                advance(bytes);
                if (!cid) { fail(VersionRejected); return; }
                if (cid == 1) r.features &= value;
                send(1, 1, r.features); break;
            case 1:
                advance(bytes);
                if (!cid) { fail(VersionRejected); return; }
                if (cid == 1 && value == r.features) r.negotiated = true;
                else { r.features &= value; send(0, 1, r.features); }
                break;
            case 2: {
                const char name[] = "apr_audio_svc"; uint8_t actual[14]{};
                if (value == sizeof(name)) peek(actual, 8, sizeof(actual));
                bool match = value == sizeof(name);
                for (unsigned i = 0; i < sizeof(name) && match; ++i) match = actual[i] == uint8_t(name[i]);
                advance(bytes);
                if (!match) { ++r.unknown_channels; break; }
                if (!cid || (r.remote_open && r.rcid != cid)) { fail(InvalidFrame); return; }
                r.rcid = cid; r.remote_open = true;
                send(4, cid, 0); break;
            }
            case 4:
                advance(bytes); if (cid == r.lcid) r.local_open_ack = true; break;
            case 5:
                if (cid == r.rcid && r.remote_open) for (unsigned i = 0; i < value; ++i) {
                    uint8_t pair[8]; peek(pair, 8 + i * 8, 8);
                    uint32_t size = get32(pair), id = get32(pair + 4); int slot = -1;
                    ++r.peer_intents; r.last_peer_iid = id; r.last_peer_size = size;
                    r.intent_invalid_reason = IntentValid;
                    // Remote IID zero is valid: vendor stores [id,id+1) in its
                    // riids tree. Our local IDs starting at one are independent.
                    if (!size) {
                        r.intent_invalid_reason = IntentZeroSize;
                        fail(InvalidFrame); return;
                    }
                    for (unsigned j = 0; j < 64; ++j) if (remote[j].present && remote[j].id == id) { slot = int(j); break; }
                    // An advertisement cannot complete an outstanding send.
                    // Only RX_DONE / RX_DONE_W_REUSE releases its ownership.
                    if (slot >= 0 && remote[slot].used) continue;
                    if (slot < 0) for (unsigned j = 0; j < 64; ++j) if (!remote[j].present) { slot = int(j); break; }
                    if (slot < 0 && size >= needed_bytes()) for (unsigned j = 0; j < 64; ++j)
                        if (!remote[j].used && remote[j].size < needed_bytes()) {
                            slot = int(j); ++r.peer_replaced; break;
                        }
                    // INTENT needs no acknowledgement. Consume surplus
                    // advertisements without using their buffers. Keep every
                    // in-flight entry until its completion; never send a
                    // synthetic RX_DONE for a buffer we have not used.
                    if (slot < 0) { ++r.peer_uncached; continue; }
                    remote[slot] = {id, size, true, false}; requested_intent = false;
                }
                advance(bytes); break;
            case 6: case 14:
                if (cid == r.rcid) for (auto &intent : remote) if (intent.present && intent.id == value) {
                    intent.used = false; intent.present = command == 14;
                }
                advance(bytes); break;
            case 7:
                advance(bytes);
                // The twenty announced buffers are the entire bounded receive pool.
                if (cid == r.rcid) send(8, uint16_t(r.lcid), 0);
                break;
            case 8:
                advance(bytes);
                if (cid == r.rcid && requested_intent && !value) { r.error = IntentUnavailable; start_close(); }
                break;
            case 9: case 12: {
                if (cid != r.rcid || !r.remote_open) { advance(bytes); break; }
                if (!offered || !value || value > 20) { fail(InvalidFrame); return; }
                LocalIntent &intent = local[value - 1];
                if ((command == 9 && intent.fill) || (command == 12 && !intent.fill) ||
                    chunk > sizeof(intent.data) - intent.fill || left > sizeof(intent.data) - intent.fill - chunk ||
                    (command == 12 && intent.remaining != chunk + left)) { fail(FragmentMismatch); return; }
                peek(intent.data + intent.fill, 16, chunk); intent.fill += chunk; intent.remaining = left;
                advance(bytes);
                if (!left) { apr(intent.data, intent.fill); finish_rx(value); }
                break;
            }
            case 13: advance(bytes); io.ring(); break;
            case 3:
                advance(bytes); send(11, cid, 0);
                if (cid == r.rcid) { r.remote_closed = true; channel_open = false; start_close(); }
                break;
            case 11:
                advance(bytes); if (cid == r.lcid && r.close_sent) r.close_ack = true; break;
            case 15: advance(bytes); break;
            default: fail(UnknownCommand); return;
            }
            if (r.broken) return;
            if (phase == Opening && r.negotiated && !requested_open) {
                const uint8_t name[] = "apr_audio_svc";
                requested_open = send(2, uint16_t(r.lcid), sizeof(name), name, sizeof(name));
            }
            if (phase == Opening && r.negotiated && r.remote_open && r.local_open_ack && !offered) {
                channel_open = true; r.opened = true; offer_all();
                if (r.broken) return;
                phase = Querying; phase_start = now; query_due = now + 100;
            }
        }
    }
    void query(uint32_t opcode) {
        uint32_t packet_bytes = needed_bytes();
        int chosen = -1;
        for (unsigned i = 0; i < 64; ++i) if (remote[i].present && !remote[i].used && remote[i].size >= packet_bytes &&
            (chosen < 0 || remote[i].size < remote[chosen].size)) chosen = int(i);
        if (chosen < 0) {
            if (!requested_intent) requested_intent = send(7, uint16_t(r.lcid), packet_bytes);
            return;
        }
        uint8_t data[48]{}; set32(data, packet_bytes); // GLINK chunk_size, left_size=0
        set16(data + 8, 0x250); set16(data + 10, uint16_t(packet_bytes));
        uint8_t service = (phase == Mapping || phase == Unmapping) ? 7 : 3;
        data[12] = service; data[13] = 5; data[16] = service; data[17] = 4;
        uint32_t token = next_token++;
        set32(data + 20, token); set32(data + 24, opcode);
        if (phase == Mapping) {
            set16(data + 28, 3); set16(data + 30, 1); // SHMEM8_4K pool, one region; property_flags=0
            set32(data + 36, uint32_t(map_address)); set32(data + 40, uint32_t(map_address >> 32));
            set32(data + 44, map_bytes);
        } else if (phase == Unmapping) set32(data + 28, r.map_handle);
        if (send(9, uint16_t(r.lcid), remote[chosen].id, data, packet_bytes + 8)) {
            remote[chosen].used = true; active_token = token; active_opcode = opcode; active_service = service;
            if (opcode == 0x1290c) { r.token = token; r.apr_sent = true; ++r.queries; }
            else if (opcode == 0x1292c) { r.version_token = token; r.version_sent = true; }
            else if (opcode == 0x10d92) { r.map_token = token; r.map_sent = true; }
            else { r.unmap_token = token; r.unmap_sent = true; }
            waiting_query = true; query_start = now;
        }
    }
public:
    constexpr explicit Link(IO &operations) : io(operations) {}
    bool begin(uint32_t desc, uint32_t tx_offset, uint32_t tx_size, uint32_t rx_offset, uint32_t rx_size,
        bool discover_services = false, uint64_t dma_address = 0, uint32_t dma_bytes = 0) {
        descriptor = desc; tx = tx_offset; tx_bytes = tx_size; rx = rx_offset; rx_bytes = rx_size;
        include_versions = discover_services;
        map_address = dma_address; map_bytes = dma_bytes;
        if (phase != Idle || tx_size < 256 || rx_size < 256 || ((tx_size | rx_size) & 7)) { fail(InvalidQueues); return false; }
        r.features = 1; r.lcid = 2; phase = Opening; phase_start = 0;
        return send(0, 1, r.features);
    }
    void step(uint32_t elapsed_ms) {
        if (phase == Idle || phase == Finished) return;
        now = elapsed_ms; pump(); if (r.broken) return;
        if (phase == Opening && now - phase_start >= 5000) { r.timeout = true; start_close(); }
        if (phase == Querying) {
            if (r.apr_ready) {
                if (include_versions) { phase = VersionQuerying; phase_start = now; query_due = now; }
                else start_close();
            }
            else if (now - phase_start >= 3000) { r.timeout = true; start_close(); }
            else {
                if (waiting_query && now - query_start >= 500) { waiting_query = false; query_due = now + 50; }
                if (!waiting_query && channel_open && now >= query_due) query(0x1290c);
            }
        }
        if (phase == VersionQuerying) {
            if (r.version_response) {
                bool asm_present = false;
                for (unsigned i = 0; i < r.service_count; ++i)
                    if (r.services[i].id == 7 && r.services[i].api == 2) asm_present = true;
                if (asm_present && map_bytes) { phase = Mapping; phase_start = now; }
                else start_close();
            } else if (r.version_basic_response || r.version_invalid) start_close();
            else if (now - phase_start >= 1000 || (waiting_query && now - query_start >= 500)) {
                r.version_timeout = true; start_close();
            } else if (!waiting_query && channel_open && now >= query_due) query(0x1292c);
        }
        if (phase == Mapping) {
            if (r.map_response) { phase = Unmapping; phase_start = now; }
            else if (r.map_basic_response && r.map_status) start_close();
            else if (now - phase_start >= 1000) { r.map_timeout = true; start_close(); }
            else if (!waiting_query && channel_open) query(0x10d92);
        }
        if (phase == Unmapping) {
            if (r.unmap_response) start_close();
            else if (now - phase_start >= 1000) { r.unmap_timeout = true; start_close(); }
            else if (!waiting_query && channel_open) query(0x10d94);
        }
        if (phase == Closing) {
            if (r.close_ack) phase = Finished;
            else if (now - phase_start >= 1000) { r.timeout = true; phase = Finished; }
        }
    }
    void abort() { fail(Aborted); }
    bool done() const { return phase == Finished; }
    const Result &result() const { return r; }
};
} // namespace NabuAdspGlink
