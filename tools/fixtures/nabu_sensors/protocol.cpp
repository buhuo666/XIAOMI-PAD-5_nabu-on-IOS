// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "../../../patches/nabu-sensors/NabuSscProtocol.h"
#include <assert.h>
#include <stdio.h>
using namespace NabuSsc;

static unsigned callbacks;
static void event(Suid sender, uint32_t id, uint64_t ticks, Span data, void *) {
    ++callbacks;
    assert(equal(sender, lookup_suid()));
    assert(id == SuidEvent && ticks == UINT64_C(318579842210));
    SuidList list;
    assert(parse_suids(data, list));
    assert(!strcmp(list.data_type, "gravity") && list.count == 1);
    assert(list.ids[0].low == UINT64_C(0xa74398c0f65bf52e));
    assert(list.ids[0].high == UINT64_C(0xc5d45a2d6850a6a5));
}
static size_t unhex(const char *s, uint8_t *out) {
    size_t n = 0; unsigned value;
    while (*s) {
        if (*s == ' ') { ++s; continue; }
        assert(sscanf(s, "%2x", &value) == 1); out[n++] = uint8_t(value); s += 2;
    }
    return n;
}
static Attributes available(const char *type) {
    Attributes a; strcpy(a.name, "Observed sensor"); strcpy(a.type, type);
    a.available = a.physical = true; a.stream_type = 0;
    a.present = (1u << 0) | (1u << 2) | (1u << 3) | (1u << 16) | (1u << 21) | (1u << 6);
    a.rates[0] = 50; a.rate_count = 1; return a;
}
static void discover(Discovery &d, const char *type, Suid id) {
    assert(d.start(type, 100, 3000));
    SuidList list; strcpy(list.data_type, type); list.ids[0] = id; list.count = 1;
    assert(d.accept_suids(list));
}
static void real_capture(const char *path) {
    FILE *file = fopen(path, "r"); assert(file);
    char line[8192]; uint8_t bytes[4096]; unsigned rows = 0, attrs = 0, samples = 0, absent = 0, incomplete = 0;
    while (fgets(line, sizeof line, file)) {
        if (line[0] == '#') continue;
        char *kind = strtok(line, "\t"), *type = strtok(nullptr, "\t"), *hex = strtok(nullptr, "\r\n");
        assert(kind && type && hex);
        size_t n = unhex(hex, bytes); Span payload{bytes, n};
        if (!strcmp(kind, "attr")) {
            Attributes a; assert(parse_attributes(payload, a)); ++attrs;
            assert(a.has(3) && a.available && a.has(21) && a.physical && !strcmp(a.type, type));
            if (!strcmp(type,"accel")) {
                assert(!strcmp(a.name,"lsm6dso") && a.selected_range_count == 2);
                assert(a.selected_range[0] == -8 && a.selected_range[1] == 8);
                assert(a.range_values == 8 && a.ranges[4] == -8 && a.ranges[5] == -8);
                assert(a.rate_count == 5 && a.rates[0] == 26 && a.rates[4] == 416);
            } else if (!strcmp(type,"gyro")) {
                assert(!strcmp(a.name,"lsm6dso") && a.selected_range[1] == 1000);
            } else if (!strcmp(type,"mag")) {
                assert(!strcmp(a.name,"ak0991x") && a.selected_range[1] == 4912);
            } else if (!strcmp(type,"ambient_light")) {
                assert(!strcmp(a.name,"tcs3701") && a.range_values == 2);
                assert(a.ranges[0] == 0 && a.ranges[1] == 65535 && a.stream_type == 1);
                assert(!a.has(23) && !a.has(24));
            } else assert(false);
            Discovery d; Suid id; id.low = 1; discover(d, type, id);
            assert(d.accept_attributes(id,a) && d.state == State::Ready);
        } else if (!strcmp(kind, "sample")) {
            Sample s; assert(parse_sample(payload,s)); ++samples;
            if (!strcmp(type,"gyro")) assert(s.status == 0);
            else assert(s.status == 3);
            if (!strcmp(type,"ambient_light")) assert(s.count == 4 && s.values[0] == 16);
            else assert(s.count == 3);
        } else if (!strcmp(kind,"incomplete")) {
            Attributes a; assert(parse_attributes(payload,a)); ++incomplete;
            assert(!strcmp(type,"ambient_light_back") && !strcmp(a.type,type));
            assert(!strcmp(a.name,"rohm_bu27030_back") && a.has(3) && a.available);
            assert(!a.has(21) && !a.physical); // false default, not a reported nonphysical device
            Discovery d; Suid id; id.low = 2; discover(d, type, id);
            assert(d.accept_attributes(id,a) && d.state == State::Incomplete);
            d.expire(3100); assert(d.state == State::Incomplete);
        } else if (!strcmp(kind,"absent")) {
            SuidList list; assert(parse_suids(payload,list)); ++absent;
            assert(!strcmp(list.data_type,type) && !list.count);
            Discovery d; assert(d.start(type,100,3000));
            assert(d.accept_suids(list) && d.state == State::Absent);
            d.expire(3100); assert(d.state == State::Absent);
        } else assert(false);
        ++rows;
    }
    fclose(file);
    assert(rows == 11 && attrs == 4 && samples == 4 && absent == 2 && incomplete == 1);
}
int main(int argc, char **argv) {
    assert(argc == 2);
    uint8_t expected[512], got[512];
    // Independent wire fixture: QMI Control, txn 17, all accel SUIDs,
    // no update registration, APSS wakeup delivery and large reports.
    size_t n = unhex("00 1100 2000 3700 01 3000 2e00 "
        "0a12 09 abababababababab 11 abababababababab "
        "1500020000 1a04 0801 1000 220d 120b 0a05 616363656c 1000 1800 "
        "10 0100 01", expected);
    size_t count = encode_lookup(got, sizeof got, 17, "accel");
    assert(count == n && !memcmp(got, expected, n));
    for (size_t cap = 0; cap < n; ++cap) assert(encode_lookup(got, cap, 17, "accel") == 0);
    assert(encode_configure(got, sizeof got, 2, lookup_suid(), false, 0) == 0);
    assert(encode_configure(got, sizeof got, 2, lookup_suid(), true, 0));

    // Historical response bytes documented by libssc's protocol investigation.
    // This is a decoder fixture, not device evidence for nabu.
    n = unhex("04 0000 2200 5300 01 0800 9100000000000000 02 4500 4300 "
        "0a12 09 abababababababab 11 abababababababab "
        "122d 0d00030000 11a29cd62c4a000000 1a1d "
        "0a07 67726176697479 1212 092ef55bf6c09843a7 11a5a650682d5ad4c5", expected);
    QmiPacket packet;
    assert(decode_qmi(expected, n, packet));
    assert(packet.client == 0x91 && packet.kind == 4);
    assert(for_each_event(packet, event, nullptr) && callbacks == 1);
    for (size_t len = 0; len < n; ++len) assert(!decode_qmi(expected, len, packet));
    expected[0] = 2; assert(!decode_qmi(expected, n, packet));

    // Attribute fixture with nested {min,max} range and unavailable retained as false.
    // IDs: name 0, type 2, available 3, ranges 11, resolution 23, physical 21, stream 16.
    n = unhex("0a110800120d0a0b120973656e736f722d3100 "
        "0a0e0802120a0a081206616363656c00 "
        "0a08080312040a022800 "
        "0a16080b12120a100a0e0a051d000020c10a051d00002041 "
        "0a0b081712070a051d0000803e "
        "0a08081512040a022801 "
        "0a0f0810120b0a09210000000000000000", expected);
    Attributes a;
    assert(parse_attributes({expected, n}, a));
    assert(!strcmp(a.name, "sensor-1") && !strcmp(a.type, "accel"));
    assert(a.has(3) && !a.available && a.has(21) && a.physical);
    assert(a.range_values == 2 && a.ranges[0] == -10 && a.ranges[1] == 10);
    assert(a.has(23) && a.selected_resolution == 0.25f);
    assert(!a.has(6) && !a.rate_count); // no invented frequency

    const uint8_t sample_data[] = {0x0d,0,0,0x80,0x3f,0x0d,0,0,0,0x40,0x0d,0,0,0x40,0x40,0x10,3};
    Sample sample;
    assert(parse_sample({sample_data,sizeof sample_data},sample));
    assert(sample.count == 3 && sample.values[2] == 3 && sample.status == 3);
    assert(!parse_sample({sample_data,sizeof sample_data-1},sample));

    Suid first; first.low = 1; first.high = 2;
    Discovery accel, gyro, pressure, no_reply;
    discover(accel, "accel", first); discover(gyro, "gyro", first);
    assert(pressure.start("pressure",100,3000));
    assert(no_reply.start("proximity",100,3000));
    SuidList absent; strcpy(absent.data_type,"pressure");
    assert(pressure.accept_suids(absent) && pressure.state == State::Absent);
    a = available("accel"); assert(accel.accept_attributes(first,a));
    assert(accel.state == State::Ready && gyro.state == State::Attributes);
    gyro.expire(3100); no_reply.expire(3100); pressure.expire(3100); accel.expire(3100);
    assert(gyro.state == State::Timeout && no_reply.state == State::Timeout);
    assert(pressure.state == State::Absent && accel.state == State::Ready);
    a.available = false; assert(accel.accept_attributes(first,a));
    assert(accel.state == State::Unavailable);
    discover(accel,"accel",first); a = available("accel"); a.physical = false;
    assert(accel.accept_attributes(first,a) && accel.state == State::Unavailable);
    discover(accel,"accel",first); a = available("accel"); a.present &= ~(1u<<21);
    assert(accel.accept_attributes(first,a) && accel.state == State::Incomplete);
    real_capture(argv[1]);
    puts("SSC: wire/state checks and 11 actual Android payloads passed (including rear ALS missing physical flag)");
}
