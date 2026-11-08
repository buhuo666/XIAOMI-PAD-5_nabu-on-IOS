// SPDX-License-Identifier: BSD-2-Clause-Patent
// Bounded Nabu host-2 GLINK/APR core probe. No QRTR, AFE or PCM commands.
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace NabuAdspGlink {
enum Error : uint32_t { NoError, InvalidQueues, InvalidPointer, InvalidFrame,
    UnknownCommand, TxFull, VersionRejected, IntentUnavailable, FragmentMismatch, Aborted };
enum IntentInvalidReason : uint32_t { IntentValid, IntentCapacity, IntentZeroSize };
struct Result {
    bool negotiated, opened, remote_open, local_open_ack, apr_sent, apr_response, apr_ready;
    bool close_sent, close_ack, remote_closed, broken, timeout;
    uint32_t features, lcid, rcid, token, apr_state, tx, rx, unknown_channels, error;
    uint32_t queries, apr_packets, apr_ignored, basic_responses, basic_status;
    uint32_t last_command, last_cid, last_value;
    uint32_t apr_field, apr_type, matched_opcode, matched_token;
    uint32_t peer_intents, last_peer_iid, last_peer_size, intent_invalid_reason;
};

template<class IO> class Link {
    struct LocalIntent { uint8_t data[512]; uint32_t fill, remaining; };
    struct RemoteIntent { uint32_t id, size; bool present, used; };
    enum Phase { Idle, Opening, Querying, Closing, Finished };
    IO &io;
    Result r{};
    LocalIntent local[20]{};
    RemoteIntent remote[64]{};
    Phase phase = Idle;
    uint32_t descriptor = 0, tx = 0, tx_bytes = 0, rx = 0, rx_bytes = 0;
    uint32_t now = 0, phase_start = 0, query_start = 0, query_due = 0, next_token = 1;
    bool requested_open = false, offered = false, channel_open = false;
    bool waiting_query = false, requested_intent = false;

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
            data[4] != 3 || data[5] != 4 || get16(data + 6) != 0 ||
            data[8] != 3 || data[9] != 5 || get16(data + 10) != 0 ||
            !waiting_query || token != r.token) { ++r.apr_ignored; return; }
        uint32_t payload = packet_bytes - header_bytes;
        if (opcode == 0x1290d && payload >= 4) {
            r.apr_field = field; r.apr_type = (field >> 8) & 3; r.matched_opcode = opcode; r.matched_token = token;
            r.apr_state = get32(data + header_bytes); r.apr_response = true; r.apr_ready = r.apr_state != 0;
            waiting_query = false; query_due = now + 50;
        } else if (opcode == 0x110e8 && payload >= 8 && get32(data + header_bytes) == 0x1290c) {
            r.apr_field = field; r.apr_type = (field >> 8) & 3; r.matched_opcode = opcode; r.matched_token = token;
            ++r.basic_responses; r.basic_status = get32(data + header_bytes + 4);
            // A basic success/unsupported response is not an audio-ready answer.
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
                    for (unsigned j = 0; j < 64; ++j) if (remote[j].present && remote[j].id == id) { slot = int(j); break; }
                    if (slot < 0) for (unsigned j = 0; j < 64; ++j) if (!remote[j].present) { slot = int(j); break; }
                    // Remote IID zero is valid: vendor stores [id,id+1) in its
                    // riids tree. Our local IDs starting at one are independent.
                    if (slot < 0 || !size) {
                        r.intent_invalid_reason = slot < 0 ? IntentCapacity : IntentZeroSize;
                        fail(InvalidFrame); return;
                    }
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
    void query() {
        int chosen = -1;
        for (unsigned i = 0; i < 64; ++i) if (remote[i].present && !remote[i].used && remote[i].size >= 20 &&
            (chosen < 0 || remote[i].size < remote[chosen].size)) chosen = int(i);
        if (chosen < 0) {
            if (!requested_intent) requested_intent = send(7, uint16_t(r.lcid), 20);
            return;
        }
        uint8_t data[28]{}; set32(data, 20); // GLINK chunk_size, left_size=0
        set16(data + 8, 0x250); set16(data + 10, 20);
        data[12] = 3; data[13] = 5; data[16] = 3; data[17] = 4;
        uint32_t token = next_token++;
        set32(data + 20, token); set32(data + 24, 0x1290c);
        if (send(9, uint16_t(r.lcid), remote[chosen].id, data, sizeof(data))) {
            remote[chosen].used = true; r.token = token; r.apr_sent = true; ++r.queries;
            waiting_query = true; query_start = now;
        }
    }
public:
    constexpr explicit Link(IO &operations) : io(operations) {}
    bool begin(uint32_t desc, uint32_t tx_offset, uint32_t tx_size, uint32_t rx_offset, uint32_t rx_size) {
        descriptor = desc; tx = tx_offset; tx_bytes = tx_size; rx = rx_offset; rx_bytes = rx_size;
        if (phase != Idle || tx_size < 256 || rx_size < 256 || ((tx_size | rx_size) & 7)) { fail(InvalidQueues); return false; }
        r.features = 1; r.lcid = 2; phase = Opening; phase_start = 0;
        return send(0, 1, r.features);
    }
    void step(uint32_t elapsed_ms) {
        if (phase == Idle || phase == Finished) return;
        now = elapsed_ms; pump(); if (r.broken) return;
        if (phase == Opening && now - phase_start >= 5000) { r.timeout = true; start_close(); }
        if (phase == Querying) {
            if (r.apr_ready) start_close();
            else if (now - phase_start >= 3000) { r.timeout = true; start_close(); }
            else {
                if (waiting_query && now - query_start >= 500) { waiting_query = false; query_due = now + 50; }
                if (!waiting_query && channel_open && now >= query_due) query();
            }
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
