// SPDX-License-Identifier: BSD-2-Clause-Patent
// MiCode diagfwd_peripheral.c: non-HDLC records when APPS_HDLC_ENCODE is set.
// The caller has already removed QRTR/GLINK framing. PKT_HEADER_UNTAG must be off.
#pragma once
#include <stdint.h>

struct NabuDiagFrames {
    enum Error { none, incomplete_header, incomplete_frame, bad_control, bad_version, bad_tail };
    struct Result {
        Error error = none;
        unsigned records = 0, payload_bytes = 0, consumed = 0, error_offset = 0;
        bool complete() const { return error == none; }
        bool incomplete() const { return error == incomplete_header || error == incomplete_frame; }
    };
    using Record = void (*)(void *context, const uint8_t *payload, unsigned bytes);

    // Each callback points into the input and is valid only while the caller retains it.
    // Empty payloads remain empty; the command parser validates its own minimum header.
    // Only whole records in this datagram are delivered. There is no cross-datagram
    // reassembly or recovery scan after an invalid record.
    static Result parse(const uint8_t *data, unsigned bytes, Record record, void *context) {
        Result result;
        while (result.consumed < bytes) {
            unsigned at = result.consumed, left = bytes - at;
            result.error_offset = at;
            if (left < 4) { result.error = incomplete_header; return result; }
            if (data[at] != 0x7e) { result.error = bad_control; return result; }
            if (data[at + 1] != 1) {
                result.error = bad_version; result.error_offset = at + 1; return result;
            }
            unsigned length = (unsigned)data[at + 2] | (unsigned)data[at + 3] << 8;
            if (left < 5 || length > left - 5) { result.error = incomplete_frame; return result; }
            unsigned tail = at + 4 + length;
            if (data[tail] != 0x7e) {
                result.error = bad_tail; result.error_offset = tail; return result;
            }
            record(context, data + at + 4, length);
            ++result.records; result.payload_bytes += length; result.consumed = tail + 1;
        }
        result.error_offset = result.consumed;
        return result;
    }
};
