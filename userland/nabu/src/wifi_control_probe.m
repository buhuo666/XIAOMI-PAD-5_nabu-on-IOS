/* Explicit paired-host trials of the native Apple80211 ioctl boundary. */
#import <Foundation/Foundation.h>
#include <errno.h>
#include <stddef.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <unistd.h>

struct nabu_wifi_request {
    char name[16];
    int32_t type, value;
    uint32_t length;
    void *data __attribute__((aligned(8)));
};
_Static_assert(sizeof(struct nabu_wifi_request) == 40, "native ioctl request");

static int request(int fd, BOOL set, int type, void *data, uint32_t length, int *value) {
    struct nabu_wifi_request r = {.name = "en0", .type = type, .length = length, .data = data};
    int rc = ioctl(fd, set ? 0x802869c8u : 0xc02869c9u, &r);
    int error = rc == 0 ? 0 : errno;
    if (value) *value = r.value;
    return error;
}

static NSDictionary *powerSnapshot(int fd) {
    uint32_t power[6] = {0};
    int error = request(fd, NO, 19, power, sizeof(power), NULL);
    return @{@"errno": @(error), @"version": @(power[0]), @"radios": @(power[1]), @"on": @(power[2])};
}

NSDictionary *nabuWiFiControlTrial(NSString *action) {
    NSMutableDictionary *out = [@{@"action": action, @"interface": @"en0",
        @"source": @"paired diagnostic process, not wifid", @"uid": @(getuid())} mutableCopy];
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) { out[@"socket_errno"] = @(errno); return out; }
    out[@"power_before"] = powerSnapshot(fd);
    if ([action isEqual:@"WirelessNativeScan"]) {
        // Layout from this kernel's apple80211_scan_request; no SSID, passive, all channels.
        uint8_t scan[5456] __attribute__((aligned(8))) = {0};
        uint32_t version = 1, passive = 2;
        memcpy(scan, &version, 4);
        memcpy(scan + 52, &passive, 4);
        int error = request(fd, YES, 10, scan, sizeof(scan), NULL);
        out[@"request_errno"] = @(error);
        if (!error) {
            BOOL seen = NO, complete = NO;
            unsigned ticks = 0;
            for (; ticks < 450; ++ticks) {
                int state = 0;
                error = request(fd, NO, 13, NULL, 0, &state);
                if (error) break;
                if (state == 1) seen = YES;
                if (seen && state != 1) { complete = YES; break; }
                usleep(100000);
            }
            out[@"state_errno"] = @(error);
            out[@"scanning_observed"] = @(seen);
            out[@"scanning_ended"] = @(complete);
            out[@"elapsed_ms"] = @(ticks * 100);
            if (complete && !error) {
                NSMutableArray *results = [NSMutableArray array];
                for (unsigned i = 0; i < 128; ++i) {
                    uint8_t bss[1164] __attribute__((aligned(8))) = {0};
                    error = request(fd, NO, 11, bss, sizeof(bss), NULL);
                    if (error) break;
                    uint32_t channel; int16_t rssi;
                    memcpy(&channel, bss + 8, 4); memcpy(&rssi, bss + 22, 2);
                    [results addObject:@{@"channel": @(channel), @"rssi": @(rssi)}];
                }
                out[@"results"] = results;
                out[@"result_terminal_errno"] = @(error);
            }
            out[@"interpretation"] = @"State transition and returned BSS are observations; correlate kernel scan return and completion event. Empty results alone do not establish scan success.";
        }
    } else {
        BOOL on = [action isEqual:@"WirelessNativePowerOn"];
        uint32_t power[6] = {1, 1, on, 0, 0, 0};
        int error = request(fd, YES, 19, power, sizeof(power), NULL);
        out[@"request_errno"] = @(error);
        if (!error) {
            for (unsigned i = 0; i < 300; ++i) {
                NSDictionary *state = powerSnapshot(fd);
                if ([state[@"errno"] intValue] || [state[@"on"] boolValue] == on) break;
                usleep(100000);
            }
        }
    }
    out[@"power_after"] = powerSnapshot(fd);
    close(fd);
    return out;
}
