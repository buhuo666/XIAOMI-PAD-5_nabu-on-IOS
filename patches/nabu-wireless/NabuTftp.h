// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
#ifdef KERNEL
#include <libkern/libkern.h>
#else
#include <string.h>
#include <stdio.h>
#endif

// One read-only, stop-and-wait TFTP transfer. Qualcomm seek/rsize are byte offsets.
struct NabuTftp {
    const uint8_t *file = nullptr;
    uint32_t size = 0, seek = 0, requested = 0, block_size = 512, block = 0;
    uint32_t node = 0, peer_port = 0, local_port = 0, payload_bytes = 0, delivered = 0;
    uint8_t payload[4004]{};
    bool active = false, pending = false, options = false, last = false, complete = false;
    bool started = false;
    unsigned retries = 0, since_send = 0;
    char name[160]{};

    static const char *field(const uint8_t *data, unsigned bytes, unsigned &at) {
        if (at >= bytes) return nullptr;
        const char *value = (const char *)data + at;
        while (at < bytes && data[at]) ++at;
        if (at == bytes) return nullptr;
        ++at; return value;
    }
    static unsigned number(const char *text) {
        unsigned value = 0;
        for (; *text >= '0' && *text <= '9'; ++text) value = value * 10 + *text - '0';
        return value;
    }
    void option(const char *key, unsigned value) {
        payload_bytes += snprintf((char *)payload + payload_bytes, sizeof(payload) - payload_bytes, "%s", key) + 1;
        payload_bytes += snprintf((char *)payload + payload_bytes, sizeof(payload) - payload_bytes, "%u", value) + 1;
    }
    void error(unsigned code) {
        payload[0] = 0; payload[1] = 5; payload[2] = 0; payload[3] = code;
        const char *text = code == 2 ? "read only" : "file not found";
        memcpy(payload + 4, text, strlen(text) + 1); payload_bytes = 5 + strlen(text);
        pending = true; last = true;
    }
    bool begin(const uint8_t *data, unsigned bytes, const uint8_t *firmware, unsigned firmware_bytes) {
        if (bytes < 4 || data[0] || (data[1] != 1 && data[1] != 2)) return false;
        unsigned at = 2; const char *path = field(data, bytes, at), *mode = field(data, bytes, at);
        if (!path || !mode || strlen(path) >= sizeof(name)) return false;
        memcpy(name, path, strlen(path) + 1); active = true;
        if (data[1] == 2) { error(2); return true; }
        bool size_option = false, seek_option = false, range_option = false;
        while (at < bytes) {
            const char *key = field(data, bytes, at), *value = field(data, bytes, at);
            if (!key || !value) { active = false; return false; }
            options = true;
            unsigned n = number(value);
            if (!strcmp(key, "blksize")) block_size = n < 8 ? 8 : n > 4000 ? 4000 : n;
            else if (!strcmp(key, "seek")) { seek = n; seek_option = true; }
            else if (!strcmp(key, "rsize")) { requested = n; range_option = true; }
            else if (!strcmp(key, "tsize")) size_option = true;
        }
        if (strcmp(name, "/readonly/firmware/image/wlanmdsp.mbn") || !firmware || seek > firmware_bytes) { error(1); return true; }
        file = firmware; size = firmware_bytes - seek;
        if (requested && requested < size) size = requested;
        if (options) {
            payload[0] = 0; payload[1] = 6; payload_bytes = 2;
            option("blksize", block_size); option("timeoutms", 1000); option("wsize", 1);
            if (size_option) option("tsize", firmware_bytes);
            if (seek_option) option("seek", seek);
            if (range_option) option("rsize", requested);
            pending = true;
        } else next();
        return true;
    }
    void next() {
        ++block; unsigned offset = (block - 1) * block_size;
        unsigned bytes = offset >= size ? 0 : size - offset < block_size ? size - offset : block_size;
        payload[0] = 0; payload[1] = 3; payload[2] = block >> 8; payload[3] = block;
        if (bytes) memcpy(payload + 4, file + seek + offset, bytes);
        payload_bytes = 4 + bytes; last = bytes < block_size || (requested && offset + bytes == size);
        pending = true; retries = since_send = 0; started = false;
    }
    void acknowledge(const uint8_t *data, unsigned bytes) {
        if (!active || bytes < 4 || data[0]) return;
        unsigned op = data[1], value = (unsigned)data[2] << 8 | data[3];
        if (op == 5) { active = false; pending = false; return; }
        if (op != 4 || value != block || pending) return;
        if (block) delivered += payload_bytes - 4;
        if (last) { complete = true; active = false; return; }
        next();
    }
    void sent() {
        pending = false; started = true; since_send = 0;
        if (payload[1] == 5) active = false;
    }
    void tick() {
        if (!active || pending || !started) return;
        if (++since_send == 1000) {
            if (++retries > 3) active = false;
            else { pending = true; since_send = 0; }
        }
    }
};
