/* Paired-host Bluetooth identity and bounded raw-UART validation. */
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>

NSDictionary *nabuBluetoothSnapshot(void) {
    NSMutableDictionary *result = [NSMutableDictionary dictionary];
    void *library = dlopen("/usr/lib/libMobileGestalt.dylib", RTLD_NOW);
    CFTypeRef (*answer)(CFStringRef) = library ? dlsym(library, "MGCopyAnswer") : NULL;
    NSMutableDictionary *capabilities = [NSMutableDictionary dictionary];
    for (NSString *key in @[@"bluetooth", @"bluetooth-le", @"BluetoothAddress"]) {
        id value = answer ? CFBridgingRelease(answer((__bridge CFStringRef)key)) : nil;
        capabilities[key] = value ?: NSNull.null;
    }
    if (library) dlclose(library);
    result[@"capabilities"] = capabilities;
    NSMutableArray *nodes = [NSMutableArray array];
    for (NSString *path in @[@"/dev/uart.bluetooth", @"/dev/cu.bluetooth", @"/dev/btreset", @"/dev/btwake", @"/dev/btpoweroff"]) {
        struct stat st;
        int status = stat(path.fileSystemRepresentation, &st), error = status ? errno : 0;
        [nodes addObject:@{@"path": path, @"exists": @(status == 0), @"errno": @(error),
                          @"character_device": @(status == 0 && S_ISCHR(st.st_mode))}];
    }
    result[@"nodes"] = nodes;
    return result;
}

static double monotonicSeconds(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return now.tv_sec + now.tv_nsec / 1e9;
}

NSDictionary *nabuBluetoothTransportTrial(void) {
    NSMutableDictionary *result = [@{@"scope": @"Exclusive UART; repeated read-only HCI queries, no discovery or pairing"} mutableCopy];
    int fd = open("/dev/uart.bluetooth", O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (fd < 0) { result[@"open_errno"] = @(errno); return result; }
    struct termios attributes;
    int status = tcgetattr(fd, &attributes);
    result[@"tcgetattr_errno"] = @(status ? errno : 0);
    if (!status) result[@"input_speed"] = @(cfgetispeed(&attributes));
    NSMutableArray *queries = [NSMutableArray array];
    const uint16_t opcodes[] = {0x1001, 0x1003, 0x1005, 0x2003, 0x1001, 0x1003, 0x1005, 0x2003};
    const unsigned chunks[] = {1, 2, 7, 31};
    for (unsigned query = 0; query < sizeof(opcodes) / sizeof(opcodes[0]); ++query) {
        uint16_t opcode = opcodes[query];
        uint8_t command[] = {1, (uint8_t)opcode, (uint8_t)(opcode >> 8), 0};
        NSMutableDictionary *item = [@{@"opcode": @(opcode), @"read_chunk": @(chunks[query % 4])} mutableCopy];
        ssize_t sent = write(fd, command, sizeof(command));
        item[@"written"] = @(sent);
        if (sent != (ssize_t)sizeof(command)) { item[@"write_errno"] = @(sent < 0 ? errno : 0); [queries addObject:item]; break; }
        uint8_t stream[1024]; size_t used = 0;
        BOOL matched = NO;
        double deadline = monotonicSeconds() + 3.0;
        while (monotonicSeconds() < deadline && !matched) {
            size_t wanted = MIN((size_t)chunks[query % 4], sizeof(stream) - used);
            ssize_t count = read(fd, stream + used, wanted);
            if (count < 0) {
                if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) { usleep(2000); continue; }
                item[@"read_errno"] = @(errno); break;
            }
            if (!count) { item[@"eof"] = @YES; break; }
            used += (size_t)count;
            while (used >= 3) {
                if (stream[0] != 4) { item[@"unexpected_h4_type"] = @(stream[0]); break; }
                size_t frame = 3u + stream[2];
                if (used < frame) break;
                if (frame >= 7 && stream[1] == 0x0e && stream[4] == command[1] && stream[5] == command[2]) {
                    item[@"status"] = @(stream[6]);
                    item[@"event_base64"] = [[NSData dataWithBytes:stream length:frame] base64EncodedStringWithOptions:0];
                    matched = YES;
                }
                memmove(stream, stream + frame, used - frame); used -= frame;
            }
            if (item[@"unexpected_h4_type"]) break;
        }
        item[@"matched"] = @(matched);
        [queries addObject:item];
        if (!matched) break;
    }
    close(fd);
    result[@"queries"] = queries;
    result[@"all_responses_successful"] = @(queries.count == 8 && [queries indexOfObjectPassingTest:^BOOL(NSDictionary *item, NSUInteger index, BOOL *stop) {
        (void)index; (void)stop;
        return ![item[@"matched"] boolValue] || [item[@"status"] unsignedIntValue] != 0;
    }] == NSNotFound);
    return result;
}
