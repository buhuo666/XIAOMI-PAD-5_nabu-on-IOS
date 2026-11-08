/* Explicit paired-host trials of the native Apple80211 ioctl boundary. */
#import <Foundation/Foundation.h>
#include <errno.h>
#include <dlfcn.h>
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

/* Read the same MobileWiFi properties used by 20F66 SpringBoard; never copy network identity. */
static NSDictionary *mobileWiFiSignalSnapshot(void) {
    void *library = dlopen("/System/Library/PrivateFrameworks/MobileWiFi.framework/MobileWiFi", RTLD_NOW);
    if (!library) return @{@"error": @"MobileWiFi unavailable"};
    CFTypeRef (*create)(CFAllocatorRef, uint32_t) = dlsym(library, "WiFiManagerClientCreate");
    CFArrayRef (*copyDevices)(CFTypeRef) = dlsym(library, "WiFiManagerClientCopyDevices");
    CFTypeRef (*currentNetwork)(CFTypeRef) = dlsym(library, "WiFiDeviceClientCopyCurrentNetwork");
    CFTypeRef (*copyProperty)(CFTypeRef, CFStringRef) = dlsym(library, "WiFiDeviceClientCopyProperty");
    if (!create || !copyDevices || !currentNetwork || !copyProperty) {
        dlclose(library); return @{@"error": @"MobileWiFi read API unavailable"};
    }
    CFTypeRef manager = create(NULL, 0);
    CFArrayRef devices = manager ? copyDevices(manager) : NULL;
    NSMutableArray *rows = [NSMutableArray array];
    for (CFIndex i = 0; devices && i < CFArrayGetCount(devices); ++i) {
        CFTypeRef device = CFArrayGetValueAtIndex(devices, i);
        CFTypeRef network = currentNetwork(device);
        NSMutableDictionary *row = [@{@"index": @(i), @"current_network_present": @(network != NULL)} mutableCopy];
        if (network) CFRelease(network);
        CFTypeRef scaled = copyProperty(device, CFSTR("ScaledRSSI"));
        double value;
        if (scaled && CFGetTypeID(scaled) == CFNumberGetTypeID() &&
            CFNumberGetValue((CFNumberRef)scaled, kCFNumberDoubleType, &value)) row[@"scaled_rssi"] = @(value);
        if (scaled) CFRelease(scaled);
        CFTypeRef rssi = copyProperty(device, CFSTR("RSSI"));
        if (rssi && CFGetTypeID(rssi) == CFDictionaryGetTypeID()) {
            for (NSString *key in @[@"RSSI_CTL_AGR", @"RSSI_UNIT"]) {
                CFTypeRef number = CFDictionaryGetValue((CFDictionaryRef)rssi, (__bridge CFStringRef)key);
                int32_t raw;
                if (number && CFGetTypeID(number) == CFNumberGetTypeID() &&
                    CFNumberGetValue((CFNumberRef)number, kCFNumberSInt32Type, &raw)) row[key] = @(raw);
            }
        }
        if (rssi) CFRelease(rssi);
        [rows addObject:row];
    }
    NSDictionary *out = @{@"manager_created": @(manager != NULL), @"devices_returned": @(devices != NULL),
        @"devices": rows, @"read_only": @YES};
    if (devices) CFRelease(devices);
    if (manager) CFRelease(manager);
    dlclose(library);
    return out;
}

NSDictionary *nabuWiFiControlTrial(NSString *action) {
    NSMutableDictionary *out = [@{@"action": action, @"interface": @"en0",
        @"source": @"paired diagnostic process, not wifid", @"uid": @(getuid())} mutableCopy];
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) { out[@"socket_errno"] = @(errno); return out; }
    out[@"power_before"] = powerSnapshot(fd);
    if ([action isEqual:@"WirelessNativeSignal"]) {
        out[@"read_only"] = @YES;
        NSMutableDictionary *snapshots = [NSMutableDictionary dictionary];
        const int types[] = {16, 17, 106};
        const unsigned counts[] = {13, 13, 4};
        NSArray *names = @[@"rssi", @"noise", @"rssi_bounds"];
        for (unsigned i = 0; i < 3; ++i) {
            int32_t words[13] = {0};
            int error = request(fd, NO, types[i], words, counts[i] * sizeof(words[0]), NULL);
            NSMutableArray *raw = [NSMutableArray array];
            if (!error) for (unsigned j = 0; j < counts[i]; ++j) [raw addObject:@(words[j])];
            snapshots[names[i]] = @{@"type": @(types[i]), @"errno": @(error), @"raw_words_i32": raw};
        }
        out[@"signal"] = snapshots;
        out[@"mobilewifi"] = mobileWiFiSignalSnapshot();
        out[@"interpretation"] = @"Raw Apple80211 replies only. Failed queries carry no valid measurements; no synthetic noise or signal level is substituted.";
    } else if ([action isEqual:@"WirelessNativeScan"]) {
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
