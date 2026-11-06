/* Nabu QCA lifecycle behind the original BlueTool XPC message contract. */
#include <dispatch/dispatch.h>
#include <xpc/xpc.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <syslog.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>
#include "NabuBluetoothControl.h"

/* The iPhoneOS SDK omits these public XNU control-socket structures. */
struct NabuControlInfo { uint32_t ctl_id; char ctl_name[96]; };
struct NabuControlAddress {
    uint8_t sc_len, sc_family;
    uint16_t ss_sysaddr;
    uint32_t sc_id, sc_unit, sc_reserved[5];
};
enum { NabuSystemFamily = 32, NabuControlProtocol = 2 };
#define NABU_CTLIOCGINFO _IOWR('N', 3, struct NabuControlInfo)
_Static_assert(sizeof(struct termios) == 72, "64-bit XNU termios ABI");
_Static_assert(sizeof(struct NabuControlInfo) == 100, "XNU control lookup ABI");
_Static_assert(sizeof(struct NabuControlAddress) == 32, "XNU control address ABI");

struct LifecycleResult {
    int error;
    unsigned hci_status;
    bool address_checked;
    bool ibs_idle;
    NabuBluetoothIbsState idle_state;
    char firmware[96];
};
static bool diagnose_le_family;
static bool le_family_diagnostic_done;

static void report(const char *format, ...) {
    char message[320];
    va_list arguments;
    va_start(arguments, format);
    vsnprintf(message, sizeof(message), format, arguments);
    va_end(arguments);
    fprintf(stderr, "NABU BT LIFECYCLE: %s\n", message);
    syslog(LOG_NOTICE, "NABU BT LIFECYCLE: %s", message);
}

static double seconds_now(void) {
    struct timespec value;
    clock_gettime(CLOCK_MONOTONIC, &value);
    return value.tv_sec + value.tv_nsec / 1000000000.0;
}

static int transfer(int fd, void *buffer, size_t bytes, bool sending, double deadline) {
    uint8_t *at = buffer;
    while (bytes) {
        double remaining = deadline - seconds_now();
        if (remaining <= 0) return ETIMEDOUT;
        struct pollfd descriptor = {fd, sending ? POLLOUT : POLLIN, 0};
        int ready = poll(&descriptor, 1, (int)(remaining * 1000) + 1);
        if (ready < 0) { if (errno == EINTR) continue; return errno; }
        if (!ready) return ETIMEDOUT;
        ssize_t count = sending ? write(fd, at, bytes) : read(fd, at, bytes);
        if (count < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) continue;
            return errno;
        }
        if (!count) return EPIPE;
        at += count;
        bytes -= (size_t)count;
    }
    return 0;
}

static int hci_command_data(int fd, uint16_t opcode, const uint8_t *arguments, uint8_t argument_bytes,
                           uint8_t *parameters, size_t *parameter_bytes, struct LifecycleResult *result) {
    uint8_t command[259] = {1, (uint8_t)opcode, (uint8_t)(opcode >> 8), argument_bytes};
    if (argument_bytes) memcpy(command + 4, arguments, argument_bytes);
    double deadline = seconds_now() + 3.0;
    int error = transfer(fd, command, 4u + argument_bytes, true, deadline);
    while (!error) {
        uint8_t event[258];
        error = transfer(fd, event, 1, false, deadline);
        if (error) break;
        /* Lifecycle owns a stopped controller, not a running ACL data stream. */
        if (event[0] != 4) { error = EPROTO; break; }
        error = transfer(fd, event + 1, 2, false, deadline);
        if (error) break;
        unsigned size = event[2];
        error = transfer(fd, event + 3, size, false, deadline);
        if (error) break;
        if (event[1] == 0x0f && size >= 4 &&
            event[5] == (uint8_t)opcode && event[6] == (uint8_t)(opcode >> 8)) {
            result->hci_status = event[3];
            if (event[3]) { error = EIO; break; }
        }
        if (event[1] != 0x0e || size < 4 ||
            event[4] != (uint8_t)opcode || event[5] != (uint8_t)(opcode >> 8)) continue;
        result->hci_status = event[6];
        if (event[6]) { error = EIO; break; }
        size_t received = size - 3;
        if (received > *parameter_bytes) { error = EMSGSIZE; break; }
        memcpy(parameters, event + 6, received);
        *parameter_bytes = received;
        report("opcode=%#x status=0 response-bytes=%zu", opcode, received);
        return 0;
    }
    report("opcode=%#x errno=%d hci-status=%u", opcode, error, result->hci_status);
    return error;
}

static int hci_command(int fd, uint16_t opcode, uint8_t *parameters,
                       size_t *parameter_bytes, struct LifecycleResult *result) {
    return hci_command_data(fd, opcode, NULL, 0, parameters, parameter_bytes, result);
}

static int diagnose_command_family(int fd) {
    /* No scan-enable or advertising-enable command is issued. Reuse exactly
     * the same passive scan parameters in separate Reset intervals, so the
     * baseline legacy command cannot select the family for the capacity query.
     */
    const uint8_t scan[] = {0, 0xe0, 1, 0x30, 0, 0, 0}; // 300ms interval, 30ms window, public address.
    const char *names[] = {"legacy-before", "periodic-list-size", "legacy-after"};
    int preparation_error = 0;
    for (unsigned step = 0; step < 3; ++step) {
        uint8_t response[32]; size_t size = sizeof(response);
        struct LifecycleResult observed = {0};
        if (step == 1) {
            preparation_error = hci_command(fd, 0x0c03, response, &size, &observed);
            report("LE family diagnostic separator-reset errno=%d hci-status=%u", preparation_error, observed.hci_status);
            if (!preparation_error && size != 1) preparation_error = EPROTO;
            if (preparation_error) break;
            size = sizeof(response);
            observed = (struct LifecycleResult){0};
        }
        int error = step == 1 ? hci_command(fd, 0x204a, response, &size, &observed) :
            hci_command_data(fd, 0x200b, scan, sizeof(scan), response, &size, &observed);
        report("LE family diagnostic phase=%s errno=%d hci-status=%u", names[step], error, observed.hci_status);
        /* A command-status failure still leaves a synchronized event stream.
         * Other I/O failures stop the experiment before its reset/revalidation.
         */
        if (error && error != EIO) break;
    }
    uint8_t response[8]; size_t size = sizeof(response);
    struct LifecycleResult reset = {0};
    int error = hci_command(fd, 0x0c03, response, &size, &reset);
    report("LE family diagnostic final-reset errno=%d hci-status=%u", error, reset.hci_status);
    return error ? error : size == 1 ? preparation_error : EPROTO;
}

static int connect_controller(void) {
    int fd = socket(NabuSystemFamily, SOCK_STREAM, NabuControlProtocol);
    if (fd < 0) return -1;
    struct NabuControlInfo info = {0};
    strlcpy(info.ctl_name, "com.apple.uart.bluetooth", sizeof(info.ctl_name));
    if (ioctl(fd, NABU_CTLIOCGINFO, &info)) goto fail;
    struct NabuControlAddress address = {0};
    address.sc_len = sizeof(address);
    address.sc_family = NabuSystemFamily;
    address.ss_sysaddr = NabuControlProtocol;
    address.sc_id = info.ctl_id;
    if (connect(fd, (struct sockaddr *)&address, sizeof(address))) goto fail;
    if (fcntl(fd, F_SETFL, O_NONBLOCK)) goto fail;
    int enabled = 1;
    if (setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &enabled, sizeof(enabled))) goto fail;
    struct termios attributes;
    socklen_t size = sizeof(attributes);
    if (getsockopt(fd, NabuControlProtocol, (int)TIOCGETA, &attributes, &size)) goto fail;
    cfmakeraw(&attributes);
    cfsetispeed(&attributes, B115200);
    cfsetospeed(&attributes, B115200);
    attributes.c_cc[VMIN] = 1;
    attributes.c_cc[VTIME] = 0;
    if (setsockopt(fd, NabuControlProtocol, (int)TIOCSETA, &attributes, sizeof(attributes))) goto fail;
    return fd;
fail: {
    int error = errno;
    close(fd);
    errno = error;
    return -1;
}
}

static int verify_controller(int fd, const char *expected, struct LifecycleResult *result) {
    uint8_t response[32];
    size_t size = sizeof(response);
    int error = hci_command(fd, 0x1001, response, &size, result);
    if (error) return error;
    if (size != 9) return EPROTO;
    unsigned manufacturer = response[5] | response[6] << 8;
    unsigned subversion = response[7] | response[8] << 8;
    /* This board's original crbtfw32 firmware, verified in runs 78 and 97. */
    if (manufacturer != 0x001d || subversion != 0x373f) return ENODEV;
    snprintf(result->firmware, sizeof(result->firmware),
             "QCA WCN3991 HCI %u LMP %u subversion 0x%04x", response[1], response[4], subversion);
    size = sizeof(response);
    error = hci_command(fd, 0x1009, response, &size, result);
    if (error) return error;
    if (size != 7) return EPROTO;
    if (expected) {
        unsigned char octets[6];
        if (strlen(expected) != 17 ||
            sscanf(expected, "%2hhx:%2hhx:%2hhx:%2hhx:%2hhx:%2hhx", octets, octets+1,
                   octets+2, octets+3, octets+4, octets+5) != 6) return EINVAL;
        for (unsigned i = 0; i < 6; ++i)
            if (octets[i] != response[6-i]) return ENXIO;
        result->address_checked = true;
    }
    report("verified firmware=%s requested-address-checked=%u", result->firmware, result->address_checked);
    return 0;
}

static struct LifecycleResult run_lifecycle(const char *stage, const char *address) {
    struct LifecycleResult result = {0};
    bool boot = !strcmp(stage, "boot"), init = !strcmp(stage, "init");
    bool sleep = !strcmp(stage, "deepsleep");
    if (!boot && !init && !sleep) { result.error = ENOTSUP; return result; }
    report("begin stage=%s", stage);
    int fd = connect_controller();
    if (fd < 0) { result.error = errno; goto done; }
    if (boot || sleep) {
        uint8_t response[8];
        size_t size = sizeof(response);
        result.error = hci_command(fd, 0x0c03, response, &size, &result);
        if (!result.error && size != 1) result.error = EPROTO;
    }
    if (!result.error && boot && diagnose_le_family && !le_family_diagnostic_done) {
        le_family_diagnostic_done = true;
        result.error = diagnose_command_family(fd);
    }
    if (!result.error && !sleep) result.error = verify_controller(fd, address, &result);
    if (!result.error && sleep) {
        /* Implemented by the Nabu backend: drain, TX FE, actual RX asleep. */
        uint32_t request = NABU_BT_CONTROL_VERSION;
        if (setsockopt(fd, NabuControlProtocol, NABU_BT_OPT_IBS_IDLE, &request, sizeof(request)))
            result.error = errno;
        else {
            socklen_t size = sizeof(result.idle_state);
            if (getsockopt(fd, NabuControlProtocol, NABU_BT_OPT_IBS_STATE, &result.idle_state, &size))
                result.error = errno;
            else if (size != sizeof(result.idle_state) || !(result.idle_state.flags & NABU_BT_IDLE_CONFIRMED))
                result.error = EIO;
            else result.ibs_idle = true;
        }
    }
    /* Release exclusive UART ownership before bluetoothd starts its H4 stack. */
    close(fd);
done:
    report("end stage=%s errno=%d status=%u ibs-idle=%u shared-rails-retained=1",
           stage, result.error, result.hci_status, result.ibs_idle);
    if (result.ibs_idle) report("idle host-sleep-count=%llu controller-sleep-count=%llu",
        (unsigned long long)result.idle_state.host_sleep_count,
        (unsigned long long)result.idle_state.controller_sleep_count);
    return result;
}

static void handle_message(xpc_connection_t peer, xpc_object_t message) {
    if (xpc_get_type(message) != XPC_TYPE_DICTIONARY) return;
    const char *kind = xpc_dictionary_get_string(message, "kMsgId");
    xpc_object_t args = xpc_dictionary_get_value(message, "kMsgArgs");
    const char *stage = NULL, *address = NULL;
    if (args && xpc_get_type(args) == XPC_TYPE_DICTIONARY) {
        stage = xpc_dictionary_get_string(args, "script");
        address = xpc_dictionary_get_string(args, "btaddress");
    }
    struct LifecycleResult result = {.error = ENOTSUP};
    xpc_object_t reply = xpc_dictionary_create_reply(message);
    if (!reply) return;
    if (kind && !strcmp(kind, "RunBuiltinScript") && stage)
        result = run_lifecycle(stage, address);
    xpc_dictionary_set_int64(reply, "result", result.error ? 1 : 0);
    /* Original field is a module-vendor code, not the HCI SIG manufacturer. */
    xpc_dictionary_set_int64(reply, "manufacturer", -1);
    xpc_dictionary_set_string(reply, "firmware", result.firmware);
    xpc_dictionary_set_int64(reply, "nabu_errno", result.error);
    xpc_dictionary_set_uint64(reply, "nabu_hci_status", result.hci_status);
    xpc_dictionary_set_bool(reply, "nabu_ibs_idle", result.ibs_idle);
    xpc_dictionary_set_uint64(reply, "nabu_host_sleep_count", result.idle_state.host_sleep_count);
    xpc_dictionary_set_uint64(reply, "nabu_controller_sleep_count", result.idle_state.controller_sleep_count);
    xpc_connection_send_message(peer, reply);
    xpc_release(reply);
}

int main(int argc, char **argv) {
    diagnose_le_family = argc == 2 && !strcmp(argv[1], "--diagnose-le-family");
    openlog("nabu-bluetooth-lifecycle", LOG_PID, LOG_DAEMON);
    dispatch_queue_t queue = dispatch_queue_create("nabu.bluetooth.lifecycle", DISPATCH_QUEUE_SERIAL);
    /* Present in the original 20F66 BlueTool, but unavailable to SDK iOS apps. */
    xpc_connection_t (*create_service)(const char *, dispatch_queue_t, uint64_t) =
        dlsym(RTLD_DEFAULT, "xpc_connection_create_mach_service");
    if (!create_service) { report("native Mach-service entry unavailable"); return 1; }
    xpc_connection_t listener = create_service(
        "com.apple.BlueTool", queue, XPC_CONNECTION_MACH_SERVICE_LISTENER);
    if (!listener) { report("listener creation failed"); return 1; }
    xpc_connection_set_event_handler(listener, ^(xpc_object_t peer) {
        if (xpc_get_type(peer) != XPC_TYPE_CONNECTION) return;
        xpc_retain(peer);
        xpc_connection_set_target_queue(peer, queue);
        xpc_connection_set_event_handler(peer, ^(xpc_object_t message) {
            if (message == XPC_ERROR_CONNECTION_INVALID) { xpc_release(peer); return; }
            handle_message(peer, message);
        });
        xpc_connection_resume(peer);
    });
    report("listening for native lifecycle requests; original QCA firmware already loaded by kernel");
    xpc_connection_resume(listener);
    dispatch_main();
}
