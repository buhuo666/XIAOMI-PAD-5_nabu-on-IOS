/* Owns the real NabuSensorSource queues and the 20F66 HID bridge on one queue.
 * No constructor or launch job. Explicit axes remain a six-face-test candidate.
 * A source, a HID client, or successful signing is not proof of HID permission.
 */
#import <Foundation/Foundation.h>
#import <IOKit/IOKitLib.h>
#import <IOKit/IODataQueueClient.h>
#import <dispatch/dispatch.h>
#import <mach/mach.h>
#import <mach/mach_time.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "sensor_bridge.h"
#include "NabuSensorHid.h"

extern IOHIDEventSystemClientRef IOHIDEventSystemClientCreateWithType(CFAllocatorRef, int, CFDictionaryRef);
extern void IOHIDEventSystemClientScheduleWithDispatchQueue(IOHIDEventSystemClientRef, dispatch_queue_t);
extern void IOHIDEventSystemClientUnscheduleFromDispatchQueue(IOHIDEventSystemClientRef, dispatch_queue_t);

_Static_assert(sizeof(struct NabuSensorStatus) == 224, "sensor status ABI");
_Static_assert(sizeof(struct NabuSensorRecord) == 64, "sensor record ABI");

@class NabuSensorEndpoint;
@interface NabuSensorDaemon : NSObject
@property(nonatomic, strong) dispatch_queue_t queue;
@property(nonatomic, strong) NSMutableDictionary<NSNumber *, NabuSensorEndpoint *> *sources;
@property(nonatomic, strong) NSMutableSet<NSString *> *failedGenerations;
@property(nonatomic, strong) dispatch_source_t timer;
@property(nonatomic, strong) dispatch_source_t interruptSignal;
@property(nonatomic, strong) dispatch_source_t terminateSignal;
@property(nonatomic) FILE *output;
@property(nonatomic) uint64_t started;
@property(nonatomic) uint64_t deadline;
@property(nonatomic) uint64_t nextDiscovery;
@property(nonatomic) int8_t axisX;
@property(nonatomic) int8_t axisY;
@property(nonatomic) int8_t axisZ;
@property(nonatomic) BOOL stopping;
@property(nonatomic) int exitStatus;
- (void)record:(NSDictionary *)record;
- (void)discover;
- (void)stop:(int)status reason:(NSString *)reason;
- (void)retired:(NabuSensorEndpoint *)source;
@end

@interface NabuSensorEndpoint : NSObject
@property(nonatomic, weak) NabuSensorDaemon *owner;
@property(nonatomic, strong) NSString *identity;
@property(nonatomic) uint64_t registryID;
@property(nonatomic) uint32_t kind;
@property(nonatomic) struct NabuSensorStatus status;
@property(nonatomic) io_connect_t connection;
@property(nonatomic) mach_vm_address_t address;
@property(nonatomic) mach_vm_size_t mappedBytes;
@property(nonatomic) IODataQueueMemory *memory;
@property(nonatomic) mach_port_t port;
@property(nonatomic, strong) dispatch_source_t notification;
@property(nonatomic) IOHIDEventSystemClientRef hid;
@property(nonatomic) struct nabu_sensor_bridge *bridge;
@property(nonatomic) uint64_t sequence;
@property(nonatomic) uint64_t lastSampleMach;
@property(nonatomic) uint64_t pendingSince;
@property(nonatomic) uint64_t samples;
@property(nonatomic) uint64_t dispatched;
@property(nonatomic) BOOL pending;
@property(nonatomic) BOOL closing;
- (IOReturn)open:(io_service_t)service;
- (BOOL)refreshStatus;
- (void)drain;
- (void)tick:(uint64_t)now;
- (void)retire:(NSString *)reason code:(int64_t)code blockGeneration:(BOOL)block;
- (BOOL)control:(enum nabu_sensor_control)control microseconds:(uint64_t)microseconds;
@end

static mach_timebase_info_data_t timebase;
static uint64_t nanoseconds(uint64_t ticks)
{
    return (uint64_t)((__uint128_t)ticks * timebase.numer / timebase.denom);
}

static uint64_t stale_limit_ns(const struct NabuSensorStatus *status)
{
    /* Backend expiry is 2s + accepted report + accepted batch. Allow another
     * second for delivery and status polling; neither interval is assumed zero. */
    __uint128_t limit = 3ULL * NSEC_PER_SEC +
        ((__uint128_t)status->report_interval_us + status->batch_interval_us) * 1000;
    return limit > UINT64_MAX ? UINT64_MAX : (uint64_t)limit;
}

static bool apply_control(void *context, enum nabu_sensor_control control, uint64_t microseconds)
{
    return [(__bridge NabuSensorEndpoint *)context control:control microseconds:microseconds];
}

@implementation NabuSensorEndpoint
- (void)log:(NSString *)event values:(NSDictionary *)values
{
    NSMutableDictionary *record = [values mutableCopy];
    record[@"event"] = event;
    record[@"kind"] = @(_kind);
    record[@"registry_id"] = @(_registryID);
    record[@"generation"] = @(_status.generation);
    [self.owner record:record];
}

- (IOReturn)open:(io_service_t)service
{
    IOReturn result = IOServiceOpen(service, mach_task_self(), NabuSensorSourceOpenType, &_connection);
    if (result) return result;
    size_t size = sizeof(_status);
    result = IOConnectCallStructMethod(_connection, NabuSensorSourceGetStatus, NULL, 0, &_status, &size);
    if (result) return result;
    if (size != sizeof(_status) || _status.description.abi_version != NabuSensorSourceAbi ||
        _status.description.kind != _kind || !_status.active) return kIOReturnNotReady;
    result = IORegistryEntryGetRegistryEntryID(service, &_registryID);
    if (result || !_registryID) return result ? result : kIOReturnNotFound;

    result = IOConnectMapMemory64(_connection, NabuSensorSourceQueueMemory, mach_task_self(),
                                 &_address, &_mappedBytes, kIOMapAnywhere);
    if (result) return result;
    _memory = (IODataQueueMemory *)(uintptr_t)_address;
    if (_mappedBytes < DATA_QUEUE_MEMORY_HEADER_SIZE ||
        _memory->queueSize > _mappedBytes - DATA_QUEUE_MEMORY_HEADER_SIZE) return kIOReturnUnderrun;

    _port = IODataQueueAllocateNotificationPort();
    if (_port == MACH_PORT_NULL) return kIOReturnNoResources;
    result = IOConnectSetNotificationPort(_connection, NabuSensorSourceQueueNotification, _port, 0);
    if (result) return result;
    _notification = dispatch_source_create(DISPATCH_SOURCE_TYPE_MACH_RECV, _port, 0, self.owner.queue);
    if (!_notification) return kIOReturnNoResources;
    __weak NabuSensorEndpoint *weakSelf = self;
    dispatch_source_set_event_handler(_notification, ^{
        NabuSensorEndpoint *source = weakSelf;
        if (!source || source.closing) return;
        struct { mach_msg_header_t header; mach_msg_max_trailer_t trailer; } message;
        mach_msg_return_t received;
        do {
            received = mach_msg(&message.header, MACH_RCV_MSG | MACH_RCV_TIMEOUT,
                                0, sizeof(message), source.port, 0, MACH_PORT_NULL);
        } while (received == MACH_MSG_SUCCESS);
        if (received != MACH_RCV_TIMED_OUT) {
            [source retire:@"notification_receive_failed" code:received blockGeneration:YES];
            return;
        }
        [source drain];
    });
    dispatch_source_set_cancel_handler(_notification, ^{
        if (self.port != MACH_PORT_NULL) mach_port_destroy(mach_task_self(), self.port);
        self.port = MACH_PORT_NULL;
        self.notification = nil;
    });
    dispatch_resume(_notification);

    /* Type 4 is the sender client used by the existing input bridge. This
     * independent process still needs the real server's registration authority. */
    _hid = IOHIDEventSystemClientCreateWithType(kCFAllocatorDefault, 4, NULL);
    if (!_hid) return kIOReturnNotPrivileged;
    IOHIDEventSystemClientScheduleWithDispatchQueue(_hid, self.owner.queue);
    struct nabu_sensor_description description = {
        .kind = (enum nabu_sensor_kind)_kind,
        .product = _status.description.product,
        .manufacturer = _status.description.manufacturer,
        .physical_suid = {_status.description.physical_suid[0], _status.description.physical_suid[1]},
        .axes = {self.owner.axisX, self.owner.axisY, self.owner.axisZ},
        .source_registry_id = _registryID,
        .source_generation = _status.generation,
    };
    _bridge = nabu_sensor_bridge_create(_hid, &description, apply_control, (__bridge void *)self);
    if (!_bridge) return kIOReturnNoResources;
    [self log:@"source_opened" values:@{@"active":@(_status.active),
        @"queue_bytes":@(_mappedBytes), @"product":@(_status.description.product),
        @"report_interval_us":@(_status.report_interval_us),
        @"batch_interval_us":@(_status.batch_interval_us),
        @"virtual_service_registration_verified":@NO}];
    /* start() enqueues the first snapshot before the notification port is set.
     * Drain it now; an on-change sensor might never cause another notification. */
    [self drain];
    return kIOReturnSuccess;
}

- (BOOL)refreshStatus
{
    if (_closing) return NO;
    struct NabuSensorStatus status;
    size_t size = sizeof(status);
    IOReturn result = IOConnectCallStructMethod(_connection, NabuSensorSourceGetStatus,
                                               NULL, 0, &status, &size);
    if (result || size != sizeof(status)) {
        [self retire:@"status_read_failed" code:result ? result : kIOReturnUnderrun blockGeneration:YES];
        return NO;
    }
    if (!status.active || status.generation != _status.generation ||
        memcmp(status.description.physical_suid, _status.description.physical_suid,
               sizeof(status.description.physical_suid))) {
        [self retire:@"source_invalidated" code:status.invalidation_reason blockGeneration:NO];
        return NO;
    }
    if (status.dropped_records != _status.dropped_records)
        [self log:@"source_queue_drops" values:@{@"dropped_records":@(status.dropped_records)}];
    _status = status;
    return YES;
}

- (void)drain
{
    if (![self refreshStatus]) return;
    while (!_closing && IODataQueueDataAvailable(_memory)) {
        struct NabuSensorRecord record;
        uint32_t size = sizeof(record);
        IOReturn result = IODataQueueDequeue(_memory, &record, &size);
        if (result || size != sizeof(record) || record.kind != _kind) {
            [self retire:@"queue_record_failed" code:result ? result : kIOReturnBadArgument blockGeneration:YES];
            return;
        }
        if (record.record_type == NabuSensorRecordInvalidated) {
            [self retire:@"source_invalidation_record" code:record.reason blockGeneration:NO];
            return;
        }
        if (record.record_type != NabuSensorRecordSample || record.sequence <= _sequence ||
            record.value_count < (_kind == NabuSensorAmbientLight ? 1U : 3U) || record.value_count > 4) {
            [self retire:@"sample_record_invalid" code:kIOReturnBadArgument blockGeneration:YES];
            return;
        }
        _sequence = record.sequence;
        struct nabu_sensor_sample sample = {.mach_timestamp = record.mach_timestamp};
        for (unsigned i = 0; i < (_kind == NabuSensorAmbientLight ? 1U : 3U); ++i) {
            float value;
            memcpy(&value, &record.value_bits[i], sizeof(value));
            sample.value[i] = value;
        }
        int error = nabu_sensor_bridge_publish(_bridge, &sample);
        ++_samples;
        if (!error) { ++_dispatched; _pending = NO; _pendingSince = 0; }
        else if (error == EAGAIN) {
            if (!_pending) _pendingSince = mach_absolute_time();
            _pending = YES;
        }
        else {
            [self retire:@"hid_publish_failed" code:error blockGeneration:YES];
            return;
        }
        _lastSampleMach = record.mach_timestamp;
        if (_samples <= 3 || (_samples % 100) == 0 || (record.flags & NabuSensorRecordCurrentSnapshot)) {
            [self log:@"sample" values:@{@"sequence":@(record.sequence), @"ssc_ticks":@(record.ssc_ticks),
                @"mach_timestamp":@(record.mach_timestamp), @"ssc_accuracy":@(record.accuracy),
                @"source_flags":@(record.flags), @"bridge_result":@(error),
                @"values":@[@(sample.value[0]), @(sample.value[1]), @(sample.value[2])],
                @"received":@(_samples), @"dispatched":@(_dispatched)}];
        }
    }
}

- (BOOL)control:(enum nabu_sensor_control)control microseconds:(uint64_t)microseconds
{
    struct NabuSensorControlRequest request = {
        .control = control == NABU_SENSOR_REPORT_INTERVAL_US ? NabuSensorReportIntervalUs : NabuSensorBatchIntervalUs,
        .microseconds = microseconds,
    };
    IOReturn result = _closing ? kIOReturnNotReady :
        IOConnectCallStructMethod(_connection, NabuSensorSourceSetControl, &request, sizeof(request), NULL, NULL);
    [self log:@"control" values:@{@"control":@(request.control), @"microseconds":@(microseconds),
        @"ioreturn":@((uint32_t)result), @"accepted":@(result == kIOReturnSuccess)}];
    if (!result) {
        if (request.control == NabuSensorReportIntervalUs) _status.report_interval_us = microseconds;
        else _status.batch_interval_us = microseconds;
    }
    return result == kIOReturnSuccess;
}

- (void)tick:(uint64_t)now
{
    if (![self refreshStatus]) return;
    if (_pending) {
        int result = nabu_sensor_bridge_flush(_bridge);
        if (!result) {
            _pending = NO; _pendingSince = 0; ++_dispatched;
            [self log:@"hid_pending_dispatched" values:@{@"dispatched":@(_dispatched)}];
        } else if (result != EAGAIN || nanoseconds(now - _pendingSince) > 5 * NSEC_PER_SEC) {
            [self retire:@"hid_open_or_flush_failed" code:result blockGeneration:YES];
            return;
        }
    }
    if (_kind != NabuSensorAmbientLight && _lastSampleMach && now >= _lastSampleMach) {
        uint64_t staleNs = stale_limit_ns(&_status);
        if (nanoseconds(now - _lastSampleMach) > staleNs)
            [self retire:@"continuous_sample_stale" code:kIOReturnTimeout blockGeneration:YES];
    }
}

- (void)retire:(NSString *)reason code:(int64_t)code blockGeneration:(BOOL)block
{
    if (_closing) return;
    _closing = YES; _pending = NO;
    if (block) [self.owner.failedGenerations addObject:self.identity];
    int removed = _bridge ? nabu_sensor_bridge_invalidate(_bridge) : 0;
    [self log:@"retiring" values:@{@"reason":reason, @"code":@(code), @"hid_remove_result":@(removed),
        @"received":@(_samples), @"dispatched":@(_dispatched)}];
    if (_connection) IOConnectSetNotificationPort(_connection, NabuSensorSourceQueueNotification, MACH_PORT_NULL, 0);
    if (_notification) dispatch_source_cancel(_notification);
    else if (_port) { mach_port_destroy(mach_task_self(), _port); _port = MACH_PORT_NULL; }
    if (_address) {
        IOReturn result = IOConnectUnmapMemory64(_connection, NabuSensorSourceQueueMemory,
                                               mach_task_self(), _address);
        [self log:@"queue_unmapped" values:@{@"ioreturn":@((uint32_t)result)}];
        _address = 0; _memory = NULL;
    }
    if (_connection) {
        IOReturn result = IOServiceClose(_connection);
        [self log:@"source_closed" values:@{@"ioreturn":@((uint32_t)result)}];
        _connection = IO_OBJECT_NULL;
    }
    if (_hid) IOHIDEventSystemClientUnscheduleFromDispatchQueue(_hid, self.owner.queue);
    /* Unscheduling prevents new HID callbacks. This final queue item follows
     * already queued callbacks while retaining their unowned bridge context. */
    dispatch_async(self.owner.queue, ^{
        int finalRemoval = removed && self.bridge ? nabu_sensor_bridge_invalidate(self.bridge) : 0;
        int destroyed = !finalRemoval && self.bridge ? nabu_sensor_bridge_destroy(self.bridge) : finalRemoval;
        if (!destroyed) self.bridge = NULL;
        if (self.hid) { CFRelease(self.hid); self.hid = NULL; }
        if (destroyed) {
            [self log:@"hid_cleanup_failed" values:@{@"result":@(destroyed)}];
            [self.owner stop:2 reason:@"hid_cleanup_failed"];
        }
        [self.owner retired:self];
    });
}
@end

@implementation NabuSensorDaemon
- (void)record:(NSDictionary *)record
{
    NSMutableDictionary *row = [record mutableCopy];
    row[@"uptime_ns"] = @(nanoseconds(mach_absolute_time()));
    NSData *data = [NSJSONSerialization dataWithJSONObject:row options:0 error:NULL];
    if (data) { fwrite(data.bytes, 1, data.length, _output); fputc('\n', _output); fflush(_output); }
}

- (void)discover
{
    io_iterator_t iterator = IO_OBJECT_NULL;
    IOReturn result = IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("NabuSensorSource"), &iterator);
    if (result) { [self record:@{@"event":@"discovery_failed", @"ioreturn":@((uint32_t)result)}]; return; }
    io_service_t service;
    while ((service = IOIteratorNext(iterator))) {
        uint64_t registryID = 0;
        IORegistryEntryGetRegistryEntryID(service, &registryID);
        CFTypeRef kindValue = IORegistryEntryCreateCFProperty(service, CFSTR("NabuSensorKind"), kCFAllocatorDefault, 0);
        CFTypeRef generationValue = IORegistryEntryCreateCFProperty(service, CFSTR("NabuGeneration"), kCFAllocatorDefault, 0);
        int32_t kind = -1, generation = 0;
        if (kindValue && CFGetTypeID(kindValue) == CFNumberGetTypeID())
            CFNumberGetValue((CFNumberRef)kindValue, kCFNumberSInt32Type, &kind);
        if (generationValue && CFGetTypeID(generationValue) == CFNumberGetTypeID())
            CFNumberGetValue((CFNumberRef)generationValue, kCFNumberSInt32Type, &generation);
        if (kindValue) CFRelease(kindValue);
        if (generationValue) CFRelease(generationValue);
        NSString *identity = [NSString stringWithFormat:@"%llu:%u", (unsigned long long)registryID, (uint32_t)generation];
        if (kind >= 0 && kind < NabuSensorKindCount && !_sources[@(kind)] && ![_failedGenerations containsObject:identity]) {
            NabuSensorEndpoint *source = [NabuSensorEndpoint new];
            source.owner = self; source.identity = identity; source.registryID = registryID; source.kind = (uint32_t)kind;
            _sources[@(kind)] = source;
            IOReturn opened = [source open:service];
            if (opened) [source retire:@"source_open_failed" code:opened blockGeneration:YES];
        }
        IOObjectRelease(service);
    }
    IOObjectRelease(iterator);
}

- (void)stop:(int)status reason:(NSString *)reason
{
    if (_stopping) { if (status) _exitStatus = status; return; }
    _stopping = YES; _exitStatus = status;
    [self record:@{@"event":@"stopping", @"reason":reason, @"exit_status":@(status)}];
    dispatch_source_cancel(_timer);
    dispatch_source_cancel(_interruptSignal);
    dispatch_source_cancel(_terminateSignal);
    for (NabuSensorEndpoint *source in [_sources.allValues copy])
        [source retire:@"daemon_stop" code:0 blockGeneration:NO];
    if (!_sources.count) [self retired:nil];
}

- (void)retired:(NabuSensorEndpoint *)source
{
    if (source && _sources[@(source.kind)] == source) [_sources removeObjectForKey:@(source.kind)];
    if (_stopping && !_sources.count) {
        [self record:@{@"event":@"stopped", @"exit_status":@(_exitStatus), @"system_features_validated":@NO}];
        exit(_exitStatus);
    }
}
@end

int main(int argc, char **argv)
{
    @autoreleasepool {
        int axes[3] = {0}, used = 0;
        BOOL suppliedAxes = NO;
        unsigned seconds = 0;
        const char *logPath = NULL;
        for (int i = 1; i < argc; ++i) {
            if (!strcmp(argv[i], "--axes") && i + 1 < argc) {
                const char *value = argv[++i];
                if (sscanf(value, "%d,%d,%d%n", &axes[0], &axes[1], &axes[2], &used) != 3 || value[used]) return 64;
                suppliedAxes = YES;
            } else if (!strcmp(argv[i], "--seconds") && i + 1 < argc) {
                char *end;
                unsigned long value = strtoul(argv[++i], &end, 10);
                if (*end || value > 86400) return 64;
                seconds = (unsigned)value;
            } else if (!strcmp(argv[i], "--log") && i + 1 < argc) logPath = argv[++i];
            else return 64;
        }
        int8_t mapped[3];
        for (unsigned i = 0; i < 3; ++i) {
            if (axes[i] < -3 || axes[i] > 3 || !axes[i]) suppliedAxes = NO;
            mapped[i] = (int8_t)axes[i];
        }
        if (!suppliedAxes || nabu_sensor_validate_axes(NABU_SENSOR_ACCELEROMETER, mapped)) {
            fprintf(stderr, "Usage: nabu-sensor-daemon --axes 1,2,3 [--seconds N] [--log PATH]\n");
            return 64;
        }
        mach_timebase_info(&timebase);
        NabuSensorDaemon *daemon = [NabuSensorDaemon new];
        daemon.queue = dispatch_queue_create("org.nabu.sensor-daemon", DISPATCH_QUEUE_SERIAL);
        daemon.sources = [NSMutableDictionary dictionary];
        daemon.failedGenerations = [NSMutableSet set];
        daemon.output = logPath ? fopen(logPath, "w") : stdout;
        if (!daemon.output) { perror("sensor log"); return 1; }
        daemon.axisX = mapped[0]; daemon.axisY = mapped[1]; daemon.axisZ = mapped[2];
        daemon.started = mach_absolute_time();
        daemon.deadline = seconds ? nanoseconds(daemon.started) + (uint64_t)seconds * NSEC_PER_SEC : 0;
        [daemon record:@{@"event":@"start", @"abi":@(NabuSensorSourceAbi),
            @"axes":@[@(mapped[0]), @(mapped[1]), @(mapped[2])], @"axes_six_face_verified":@NO,
            @"hid_client_type":@4, @"independent_hid_registration_authority_verified":@NO}];
        signal(SIGINT, SIG_IGN); signal(SIGTERM, SIG_IGN);
        daemon.interruptSignal = dispatch_source_create(DISPATCH_SOURCE_TYPE_SIGNAL, SIGINT, 0, daemon.queue);
        daemon.terminateSignal = dispatch_source_create(DISPATCH_SOURCE_TYPE_SIGNAL, SIGTERM, 0, daemon.queue);
        dispatch_source_set_event_handler(daemon.interruptSignal, ^{ [daemon stop:0 reason:@"SIGINT"]; });
        dispatch_source_set_event_handler(daemon.terminateSignal, ^{ [daemon stop:0 reason:@"SIGTERM"]; });
        dispatch_resume(daemon.interruptSignal); dispatch_resume(daemon.terminateSignal);
        daemon.timer = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, daemon.queue);
        dispatch_source_set_timer(daemon.timer, DISPATCH_TIME_NOW, 100 * NSEC_PER_MSEC, 10 * NSEC_PER_MSEC);
        dispatch_source_set_event_handler(daemon.timer, ^{
            uint64_t now = mach_absolute_time(), nowNs = nanoseconds(now);
            if (daemon.deadline && nowNs >= daemon.deadline) { [daemon stop:0 reason:@"duration_complete"]; return; }
            for (NabuSensorEndpoint *source in [daemon.sources.allValues copy]) [source tick:now];
            if (nowNs >= daemon.nextDiscovery) { daemon.nextDiscovery = nowNs + NSEC_PER_SEC; [daemon discover]; }
        });
        dispatch_resume(daemon.timer);
        dispatch_main();
    }
}
