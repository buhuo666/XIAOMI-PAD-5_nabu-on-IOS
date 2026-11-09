// SPDX-License-Identifier: BSD-2-Clause-Patent
// SSC wire implementation written for nabu. Protocol evidence, not imported
// implementation: Android's sns_{client,suid,std,std_type,std_sensor}.proto,
// libqmi data/qmi-service-ssc.json and libssc data/*.proto. See
// analysis/sensors-backend/README.md. No GLib, protobuf runtime, heap or waits.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace NabuSsc {
enum : uint32_t { Service = 400, Control = 0x20, ReportSmall = 0x21,
    ReportLarge = 0x22, AttrRequest = 1, AttrEvent = 128, ErrorEvent = 130,
    SuidRequest = 512, SuidEvent = 768, StreamConfig = 513, ChangeConfig = 514,
    PhysicalConfig = 768, SampleEvent = 1025, Disable = 10 };
struct Span { const uint8_t *data; size_t size; };
struct Suid { uint64_t low = 0, high = 0; };
inline bool equal(Suid a, Suid b) { return a.low == b.low && a.high == b.high; }
inline Suid lookup_suid() { Suid s; s.low = s.high = UINT64_C(0xabababababababab); return s; }
inline uint16_t u16(const uint8_t *p) { return uint16_t(p[0]) | uint16_t(p[1]) << 8; }
inline uint32_t u32(const uint8_t *p) { return uint32_t(u16(p)) | uint32_t(u16(p+2)) << 16; }
inline uint64_t u64(const uint8_t *p) { return uint64_t(u32(p)) | uint64_t(u32(p+4)) << 32; }
inline void put16(uint8_t *p, uint16_t n) { p[0] = uint8_t(n); p[1] = uint8_t(n >> 8); }
inline float as_float(uint32_t bits) { float f; memcpy(&f, &bits, 4); return f; }
inline bool finite(float f) { uint32_t n; memcpy(&n, &f, 4); return (n & 0x7f800000) != 0x7f800000; }

struct Writer {
    uint8_t *data; size_t capacity, size = 0; bool ok = true;
    Writer(uint8_t *p, size_t n) : data(p), capacity(n) {}
    void byte(uint8_t v) { if (size == capacity) { ok = false; return; } data[size++] = v; }
    void raw(const uint8_t *p, size_t n) {
        if (n > capacity - size) { ok = false; return; }
        if (n) memcpy(data + size, p, n);
        size += n;
    }
    void varint(uint64_t n) { while (n >= 128) { byte(uint8_t(n) | 128); n >>= 7; } byte(uint8_t(n)); }
    void integer(unsigned field, uint64_t n) { varint(uint64_t(field) << 3); varint(n); }
    void fixed(unsigned field, uint64_t n, unsigned bytes) {
        varint((uint64_t(field) << 3) | (bytes == 4 ? 5 : 1));
        for (unsigned i = 0; i < bytes; ++i) { byte(uint8_t(n)); n >>= 8; }
    }
    void real(unsigned field, float f) { uint32_t n; memcpy(&n, &f, 4); fixed(field, n, 4); }
    void message(unsigned field, const uint8_t *p, size_t n) {
        varint((uint64_t(field) << 3) | 2); varint(n); raw(p, n);
    }
    void string(unsigned field, const char *s) { message(field, (const uint8_t *)s, strlen(s)); }
};

struct Field { unsigned number = 0, wire = 0; uint64_t integer = 0; Span bytes{nullptr, 0}; };
struct Reader {
    Span input; size_t at = 0; bool ok = true;
    explicit Reader(Span s) : input(s) {}
    bool varint(uint64_t &out) {
        out = 0;
        for (unsigned i = 0; i < 10; ++i) {
            if (at == input.size) return ok = false;
            uint8_t b = input.data[at++];
            if (i == 9 && b > 1) return ok = false;
            out |= uint64_t(b & 127) << (i * 7);
            if (!(b & 128)) return true;
        }
        return ok = false;
    }
    bool next(Field &f) {
        f = Field{};
        if (!ok || at == input.size) return false;
        uint64_t key;
        if (!varint(key) || !(key >> 3) || key >> 3 > 0x1fffffff) return ok = false;
        f.number = unsigned(key >> 3); f.wire = unsigned(key & 7);
        size_t n = 0;
        if (f.wire == 0) return varint(f.integer);
        if (f.wire == 1) n = 8;
        else if (f.wire == 5) n = 4;
        else if (f.wire == 2) {
            uint64_t length;
            if (!varint(length) || length > input.size - at) return ok = false;
            n = size_t(length);
        } else return ok = false;
        if (n > input.size - at) return ok = false;
        f.bytes = {input.data + at, n}; at += n;
        if (f.wire == 1) f.integer = u64(f.bytes.data);
        if (f.wire == 5) f.integer = u32(f.bytes.data);
        return true;
    }
};

inline size_t encode_request(uint8_t *out, size_t capacity, uint16_t transaction,
    Suid suid, uint32_t message_id, Span payload) {
    uint8_t uid[24], request[256], body[320], suspend[8];
    Writer u(uid, sizeof uid), r(request, sizeof request), b(body, sizeof body), s(suspend, sizeof suspend);
    u.fixed(1, suid.low, 8); u.fixed(2, suid.high, 8);
    s.integer(1, 1); s.integer(2, 0); // APSS, wakeup delivery; no batching.
    if (payload.size) r.message(2, payload.data, payload.size);
    b.message(1, uid, u.size); b.fixed(2, message_id, 4);
    b.message(3, suspend, s.size); b.message(4, request, r.size);
    if (!u.ok || !r.ok || !s.ok || !b.ok || b.size + 16 > capacity) return 0;
    // QMI-over-QRTR has no QMUX header. TLV data includes its uint16 length.
    out[0] = 0; put16(out+1, transaction); put16(out+3, Control);
    put16(out+5, uint16_t(b.size + 9));
    out[7] = 1; put16(out+8, uint16_t(b.size + 2)); put16(out+10, uint16_t(b.size));
    memcpy(out+12, body, b.size);
    out[12+b.size] = 0x10; put16(out+13+b.size, 1); out[15+b.size] = 1; // large reports
    return b.size + 16;
}
inline size_t encode_lookup(uint8_t *out, size_t capacity, uint16_t transaction,
    const char *type, bool updates = false, bool default_only = false) {
    uint8_t data[192]; Writer w(data, sizeof data);
    w.string(1, type); w.integer(2, updates); w.integer(3, default_only);
    return w.ok ? encode_request(out, capacity, transaction, lookup_suid(), SuidRequest, {data, w.size}) : 0;
}
inline size_t encode_attributes(uint8_t *out, size_t capacity, uint16_t transaction, Suid suid) {
    const uint8_t data[] = {0x10, 0}; // register_updates=false
    return encode_request(out, capacity, transaction, suid, AttrRequest, {data, sizeof data});
}
inline size_t encode_configure(uint8_t *out, size_t capacity, uint16_t transaction,
    Suid suid, bool on_change, float hz) {
    uint8_t data[5]; Writer w(data, sizeof data);
    if (!on_change) { if (!finite(hz) || hz <= 0) return 0; w.real(1, hz); }
    return encode_request(out, capacity, transaction, suid, on_change ? ChangeConfig : StreamConfig, {data, w.size});
}
inline size_t encode_disable(uint8_t *out, size_t capacity, uint16_t transaction, Suid suid) {
    return encode_request(out, capacity, transaction, suid, Disable, {nullptr, 0});
}

struct QmiPacket {
    uint8_t kind = 0; uint16_t transaction = 0, message_id = 0;
    bool has_result = false, has_client = false, has_response = false;
    uint16_t result = 0, error = 0; uint32_t response = 0; uint64_t client = 0;
    Span protobuf{nullptr, 0};
};
inline bool decode_qmi(const uint8_t *data, size_t size, QmiPacket &packet) {
    packet = QmiPacket{};
    if (size < 7 || u16(data+5) != size - 7) return false;
    packet.kind = data[0]; packet.transaction = u16(data+1); packet.message_id = u16(data+3);
    bool report = packet.kind == 4 && (packet.message_id == ReportSmall || packet.message_id == ReportLarge);
    bool response = packet.kind == 2 && packet.message_id == Control;
    if (!report && !response) return false;
    for (size_t at = 7; at < size;) {
        if (size - at < 3) return false;
        uint8_t type = data[at]; size_t n = u16(data+at+1); at += 3;
        if (n > size - at) return false;
        const uint8_t *v = data+at;
        if (response && type == 2) {
            if (n != 4) return false;
            packet.has_result = true; packet.result = u16(v); packet.error = u16(v+2);
        } else if ((report && type == 1) || (response && type == 0x10)) {
            if (n != 8) return false;
            packet.has_client = true; packet.client = u64(v);
        } else if (response && type == 0x11) {
            if (n != 4) return false;
            packet.has_response = true; packet.response = u32(v);
        } else if (report && type == 2) {
            if (n < 2 || u16(v) != n - 2) return false;
            packet.protobuf = {v+2, n-2};
        }
        at += n;
    }
    return report ? packet.has_client && packet.protobuf.data : packet.has_result;
}
inline bool parse_uid(Span data, Suid &suid) {
    Reader r(data); Field f; unsigned seen = 0; suid = Suid{};
    while (r.next(f)) {
        if (f.number == 1) { if (f.wire != 1) return false; suid.low = f.integer; seen |= 1; }
        if (f.number == 2) { if (f.wire != 1) return false; suid.high = f.integer; seen |= 2; }
    }
    return r.ok && seen == 3;
}
typedef void (*EventCallback)(Suid, uint32_t, uint64_t, Span, void *);
inline bool for_each_event(const QmiPacket &packet, EventCallback callback, void *context) {
    Reader top(packet.protobuf); Field f; Suid suid; bool has_uid = false;
    // Protobuf fields need not be ordered; discover sender before dispatching events.
    while (top.next(f)) if (f.number == 1) {
        if (f.wire != 2 || !parse_uid(f.bytes, suid)) return false;
        has_uid = true;
    }
    if (!top.ok || !has_uid) return false;
    // Validate the entire batch before delivering any event from it.
    for (unsigned pass = 0; pass != 2; ++pass) {
        Reader events(packet.protobuf);
        while (events.next(f)) if (f.number == 2) {
            if (f.wire != 2) return false;
            Reader event(f.bytes); Field e; unsigned seen = 0; uint32_t id = 0; uint64_t ticks = 0;
            Span payload{nullptr, 0};
            while (event.next(e)) {
                if (e.number == 1) { if (e.wire != 5) return false; id = uint32_t(e.integer); seen |= 1; }
                if (e.number == 2) { if (e.wire != 1) return false; ticks = e.integer; seen |= 2; }
                if (e.number == 3) { if (e.wire != 2) return false; payload = e.bytes; seen |= 4; }
            }
            if (!event.ok || seen != 7) return false;
            if (pass) callback(suid, id, ticks, payload, context);
        }
        if (!events.ok) return false;
    }
    return true;
}
inline bool copy_string(char *out, size_t capacity, Span value) {
    size_t n = value.size;
    // Firmware commonly includes a terminal NUL inside its protobuf string.
    if (n && !value.data[n-1]) --n;
    if (n >= capacity || (n && memchr(value.data, 0, n))) return false;
    if (n) memcpy(out, value.data, n);
    out[n] = 0; return true;
}
struct SuidList { char data_type[64]{}; Suid ids[16]{}; unsigned count = 0; };
inline bool parse_suids(Span data, SuidList &list) {
    list = SuidList{}; Reader r(data); Field f; bool has_type = false;
    while (r.next(f)) {
        if (f.number == 1) {
            if (f.wire != 2 || !copy_string(list.data_type, sizeof list.data_type, f.bytes)) return false;
            has_type = true;
        } else if (f.number == 2) {
            if (f.wire != 2 || list.count == 16 || !parse_uid(f.bytes, list.ids[list.count])) return false;
            ++list.count;
        }
    }
    return r.ok && has_type;
}

struct Attributes {
    uint32_t present = 0;
    char name[128]{}, vendor[128]{}, type[64]{};
    bool available = false, physical = false;
    int64_t version = 0, stream_type = 0, fifo = 0, hardware_id = 0;
    float rates[32]{}, resolutions[32]{}, ranges[64]{}, placement[12]{};
    unsigned rate_count = 0, resolution_count = 0, range_values = 0, placement_count = 0;
    float selected_resolution = 0, selected_range[2]{}; unsigned selected_range_count = 0;
    bool has(unsigned id) const { return id < 32 && (present & (uint32_t(1) << id)); }
};
inline bool append(float *array, unsigned &count, unsigned capacity, float v) {
    if (count == capacity || !finite(v)) return false;
    array[count++] = v; return true;
}
inline bool attr_values(Span input, unsigned id, Attributes &a, unsigned depth = 0) {
    Reader values(input); Field v;
    while (values.next(v)) if (v.number == 1) {
        if (v.wire != 2) return false;
        Reader value(v.bytes); Field f;
        while (value.next(f)) {
            if (f.number == 1) {
                if (f.wire != 2 || depth == 2 || !attr_values(f.bytes, id, a, depth+1)) return false;
            } else if (f.number == 2) {
                if (f.wire != 2) return false;
                if (id == 0 && !copy_string(a.name, sizeof a.name, f.bytes)) return false;
                if (id == 1 && !copy_string(a.vendor, sizeof a.vendor, f.bytes)) return false;
                if (id == 2 && !copy_string(a.type, sizeof a.type, f.bytes)) return false;
                if (id <= 2) a.present |= uint32_t(1) << id;
            } else if (f.number == 3) {
                if (f.wire != 5) return false;
                float x = as_float(uint32_t(f.integer)); bool ok = true;
                if (id == 6) ok = append(a.rates, a.rate_count, 32, x);
                if (id == 7) ok = append(a.resolutions, a.resolution_count, 32, x);
                if (id == 11) ok = append(a.ranges, a.range_values, 64, x);
                if (id == 20) ok = append(a.placement, a.placement_count, 12, x);
                if (id == 23) { ok = finite(x); a.selected_resolution = x; }
                if (id == 24) ok = append(a.selected_range, a.selected_range_count, 2, x);
                if (!ok) return false;
                if (id < 32) a.present |= uint32_t(1) << id;
            } else if (f.number == 4) {
                if (f.wire != 1) return false;
                int64_t x; memcpy(&x, &f.integer, 8);
                if (id == 4) a.version = x;
                if (id == 8) a.fifo = x;
                if (id == 16) a.stream_type = x;
                if (id == 18) a.hardware_id = x;
                if (id < 32) a.present |= uint32_t(1) << id;
            } else if (f.number == 5) {
                if (f.wire != 0 || f.integer > 1) return false;
                if (id == 3) a.available = f.integer != 0;
                if (id == 21) a.physical = f.integer != 0;
                if (id < 32) a.present |= uint32_t(1) << id;
            }
        }
        if (!value.ok) return false;
    }
    return values.ok;
}
inline bool parse_attributes(Span data, Attributes &a) {
    a = Attributes{}; Reader r(data); Field f;
    while (r.next(f)) if (f.number == 1) {
        if (f.wire != 2) return false;
        Reader attr(f.bytes); Field v; unsigned id = 0; bool has_id = false, has_value = false;
        Span value{nullptr, 0};
        while (attr.next(v)) {
            if (v.number == 1) { if (v.wire != 0 || v.integer > 0x7fffffff) return false; id = unsigned(v.integer); has_id = true; }
            if (v.number == 2) { if (v.wire != 2) return false; value = v.bytes; has_value = true; }
        }
        if (!attr.ok || !has_id || !has_value || !attr_values(value, id, a)) return false;
    }
    return r.ok;
}

struct Sample { float values[16]{}; unsigned count = 0; uint32_t status = 0; bool has_status = false; };
inline bool parse_sample(Span data, Sample &sample) {
    sample = Sample{}; Reader r(data); Field f;
    while (r.next(f)) {
        if (f.number == 1) {
            if (f.wire == 5) {
                if (!append(sample.values, sample.count, 16, as_float(uint32_t(f.integer)))) return false;
            } else if (f.wire == 2) {
                if (f.bytes.size % 4) return false;
                for (size_t i = 0; i < f.bytes.size; i += 4)
                    if (!append(sample.values, sample.count, 16, as_float(u32(f.bytes.data+i)))) return false;
            } else return false;
        } else if (f.number == 2) {
            if (f.wire != 0 || f.integer > 3) return false;
            sample.status = uint32_t(f.integer); sample.has_status = true;
        }
    }
    return r.ok && sample.has_status && sample.count;
}
struct Configuration {
    bool has_rate = false, has_resolution = false;
    float rate = 0, resolution = 0, range[2]{}; unsigned range_count = 0;
    char mode[64]{};
};
inline bool parse_config(Span data, Configuration &config) {
    config = Configuration{}; Reader r(data); Field f;
    while (r.next(f)) {
        if (f.number == 1 || f.number == 4) {
            if (f.wire != 5) return false;
            float x = as_float(uint32_t(f.integer)); if (!finite(x)) return false;
            if (f.number == 1) { config.has_rate = true; config.rate = x; }
            else { config.has_resolution = true; config.resolution = x; }
        } else if (f.number == 3) {
            if (f.wire == 5) {
                if (!append(config.range, config.range_count, 2, as_float(uint32_t(f.integer)))) return false;
            } else if (f.wire == 2) {
                if (f.bytes.size % 4) return false;
                for (size_t i = 0; i < f.bytes.size; i += 4)
                    if (!append(config.range, config.range_count, 2, as_float(u32(f.bytes.data+i)))) return false;
            } else return false;
        } else if (f.number == 5) {
            if (f.wire != 2 || !copy_string(config.mode, sizeof config.mode, f.bytes)) return false;
        }
    }
    return r.ok;
}

enum class State : uint8_t { Idle, Lookup, Attributes, Ready, Absent, Unavailable, Timeout, Incomplete };
struct Candidate { Suid suid; State state = State::Idle; Attributes attributes; };
// One instance per requested data type. A missing type cannot block another.
// Ready means discovered+available physical hardware; a stream needs a separate
// first real sample before its readings can be published to an OS consumer.
struct Discovery {
    char data_type[64]{}; Candidate candidates[16]{}; unsigned count = 0;
    State state = State::Idle; uint64_t deadline_ms = 0;
    bool start(const char *type, uint64_t now_ms, uint32_t timeout_ms) {
        if (strlen(type) >= sizeof data_type || !timeout_ms) return false;
        *this = Discovery{}; strcpy(data_type, type); deadline_ms = now_ms + timeout_ms;
        state = State::Lookup; return true;
    }
    void summarize() {
        bool pending = false, incomplete = false, timed_out = false;
        for (unsigned i = 0; i < count; ++i) {
            if (candidates[i].state == State::Ready) { state = State::Ready; return; }
            pending |= candidates[i].state == State::Attributes;
            incomplete |= candidates[i].state == State::Incomplete;
            timed_out |= candidates[i].state == State::Timeout;
        }
        state = pending ? State::Attributes : timed_out ? State::Timeout : incomplete ? State::Incomplete : State::Unavailable;
    }
    bool accept_suids(const SuidList &list) {
        if (state != State::Lookup || strcmp(data_type, list.data_type)) return false;
        count = list.count;
        for (unsigned i = 0; i < count; ++i) { candidates[i].suid = list.ids[i]; candidates[i].state = State::Attributes; }
        state = count ? State::Attributes : State::Absent; return true;
    }
    bool accept_attributes(Suid suid, const Attributes &a) {
        for (unsigned i = 0; i < count; ++i) if (equal(suid, candidates[i].suid)) {
            Candidate &c = candidates[i]; c.attributes = a;
            if (c.state == State::Timeout) return false;
            if (!a.has(0) || !a.has(2) || !a.has(3) || !a.has(21) || !a.has(16)) c.state = State::Incomplete;
            else if (strcmp(a.type, data_type) || !a.available || !a.physical) c.state = State::Unavailable;
            else if (a.stream_type == 0 && !a.rate_count) c.state = State::Incomplete;
            else c.state = State::Ready;
            summarize(); return true;
        }
        return false;
    }
    void expire(uint64_t now_ms) {
        if (now_ms < deadline_ms) return;
        if (state == State::Lookup) { state = State::Timeout; return; }
        bool changed = false;
        for (unsigned i = 0; i < count; ++i) if (candidates[i].state == State::Attributes) {
            candidates[i].state = State::Timeout; changed = true;
        }
        if (changed) summarize();
    }
};
} // namespace NabuSsc
