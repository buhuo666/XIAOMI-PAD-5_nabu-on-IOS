/* Paired-host Bluetooth identity and bounded raw-UART validation. */
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/kern_control.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/sys_domain.h>
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

static void runHciQueries(int fd, NSMutableDictionary *result) {
    NSMutableArray *queries = [NSMutableArray array];
    const uint16_t opcodes[] = {0x1001, 0x1003, 0x1005, 0x2003, 0x1001, 0x1003, 0x1005, 0x2003};
    const unsigned chunks[] = {1, 2, 7, 31};
    uint8_t stream[1024]; size_t used = 0;
    for (unsigned query = 0; query < sizeof(opcodes) / sizeof(opcodes[0]); ++query) {
        uint16_t opcode = opcodes[query];
        uint8_t command[] = {1, (uint8_t)opcode, (uint8_t)(opcode >> 8), 0};
        NSMutableDictionary *item = [@{@"opcode": @(opcode), @"read_chunk": @(chunks[query % 4])} mutableCopy];
        ssize_t sent = write(fd, command, sizeof(command));
        item[@"written"] = @(sent);
        if (sent != (ssize_t)sizeof(command)) { item[@"write_errno"] = @(sent < 0 ? errno : 0); [queries addObject:item]; break; }
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
    result[@"queries"] = queries;
    result[@"all_responses_successful"] = @(queries.count == 8 && [queries indexOfObjectPassingTest:^BOOL(NSDictionary *item, NSUInteger index, BOOL *stop) {
        (void)index; (void)stop;
        return ![item[@"matched"] boolValue] || [item[@"status"] unsignedIntValue] != 0;
    }] == NSNotFound);
}

NSDictionary *nabuBluetoothTransportTrial(void) {
    NSMutableDictionary *result = [@{@"scope": @"Exclusive UART; repeated read-only HCI queries, no discovery or pairing"} mutableCopy];
    int fd = open("/dev/uart.bluetooth", O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (fd < 0) { result[@"open_errno"] = @(errno); return result; }
    struct termios attributes;
    int status = tcgetattr(fd, &attributes);
    result[@"tcgetattr_errno"] = @(status ? errno : 0);
    if (!status) result[@"input_speed"] = @(cfgetispeed(&attributes));
    runHciQueries(fd, result);
    close(fd);
    return result;
}

NSDictionary *nabuBluetoothSocketTrial(void) {
    NSMutableDictionary *result = [@{
        @"scope": @"Exclusive UART control socket; configure raw 115200 mode and repeat read-only HCI queries, no discovery or pairing",
        @"control_name": @"com.apple.uart.bluetooth",
        @"all_responses_successful": @NO
    } mutableCopy];
    int fd = socket(AF_SYSTEM, SOCK_STREAM, SYSPROTO_CONTROL);
    result[@"socket_errno"] = @(fd < 0 ? errno : 0);
    if (fd < 0) return result;
    do {
        struct ctl_info info = {0};
        strlcpy(info.ctl_name, "com.apple.uart.bluetooth", sizeof(info.ctl_name));
        int status = ioctl(fd, CTLIOCGINFO, &info);
        result[@"control_lookup_errno"] = @(status ? errno : 0);
        if (status) break;
        result[@"control_id"] = @(info.ctl_id);

        struct sockaddr_ctl address = {0};
        address.sc_len = sizeof(address);
        address.sc_family = AF_SYSTEM;
        address.ss_sysaddr = AF_SYS_CONTROL;
        address.sc_id = info.ctl_id;
        status = connect(fd, (const struct sockaddr *)&address, sizeof(address));
        int error = status ? errno : 0;
        result[@"connect_errno"] = @(error);
        result[@"connected"] = @(status == 0);
        if (status) {
            if (error == EBUSY) result[@"controller_in_use"] = @YES;
            break;
        }

        struct termios attributes = {0};
        socklen_t length = sizeof(attributes);
        status = getsockopt(fd, SYSPROTO_CONTROL, (int)TIOCGETA, &attributes, &length);
        result[@"get_termios_errno"] = @(status ? errno : 0);
        result[@"termios_bytes"] = @(length);
        result[@"termios_expected_bytes"] = @(sizeof(attributes));
        if (status || length != sizeof(attributes)) break;
        result[@"input_speed_before"] = @(cfgetispeed(&attributes));
        result[@"output_speed_before"] = @(cfgetospeed(&attributes));
        cfmakeraw(&attributes);
        status = cfsetspeed(&attributes, 115200);
        result[@"cfsetspeed_errno"] = @(status ? errno : 0);
        if (status) break;
        status = setsockopt(fd, SYSPROTO_CONTROL, (int)TIOCSETA, &attributes, sizeof(attributes));
        result[@"set_termios_errno"] = @(status ? errno : 0);
        if (status) break;
        result[@"configured_speed"] = @(cfgetospeed(&attributes));

        int flags = fcntl(fd, F_GETFL);
        result[@"get_flags_errno"] = @(flags < 0 ? errno : 0);
        if (flags < 0) break;
        status = fcntl(fd, F_SETFL, flags | O_NONBLOCK);
        result[@"set_nonblocking_errno"] = @(status ? errno : 0);
        if (status) break;
        runHciQueries(fd, result);
    } while (0);
    close(fd);
    return result;
}
