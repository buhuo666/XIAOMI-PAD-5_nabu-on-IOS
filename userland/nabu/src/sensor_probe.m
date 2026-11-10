/* Native 20F66 consumer probe. It subscribes to real system sensors and never
 * injects samples or changes sensor capability declarations. */
#import <Foundation/Foundation.h>
#import <CoreMotion/CoreMotion.h>
#import <IOKit/IOKitLib.h>
#import <mach/mach_time.h>
#include <dlfcn.h>
#include <math.h>
#include <stdio.h>
#ifdef NABU_SENSOR_PROBE_APP
#import <UIKit/UIKit.h>
#endif

typedef struct __IOHIDEventSystemClient *HIDClient;
typedef struct __IOHIDServiceClient *HIDService;
typedef struct __IOHIDEvent *HIDEvent;
typedef void (*HIDCallback)(void *, void *, HIDService, HIDEvent);
struct HIDAPI {
    HIDClient (*create)(CFAllocatorRef, int, CFDictionaryRef);
    void (*match_multiple)(HIDClient, CFArrayRef);
    CFArrayRef (*services)(HIDClient);
    void (*register_event)(HIDClient, HIDCallback, void *, void *);
    void (*schedule)(HIDClient, dispatch_queue_t);
    void (*unschedule)(HIDClient, dispatch_queue_t);
    uint32_t (*type)(HIDEvent);
    uint64_t (*timestamp)(HIDEvent);
    CFIndex (*integer)(HIDEvent, uint32_t);
    double (*floating)(HIDEvent, uint32_t);
    CFTypeRef (*registry_id)(HIDService);
    CFTypeRef (*copy_property)(HIDService, CFStringRef);
};
static struct HIDAPI hid;

@interface NabuSensorProbe : NSObject
@property(nonatomic, strong) CMMotionManager *motion;
@property(nonatomic, strong) NSFileHandle *events;
@property(nonatomic, strong) NSMutableDictionary *channels;
@property(nonatomic, strong) NSMutableArray *alsServices;
@property(nonatomic, strong) NSMutableArray *hidServiceSnapshots;
@property(nonatomic, strong) NSMutableArray *orientationEvents;
@property(nonatomic, strong) NSMutableArray *diagnosticSnapshots;
@property(nonatomic, strong) NSString *directory;
@property(nonatomic, strong) NSDictionary *availability;
@property(nonatomic, strong) NSString *hidStatus;
@property(nonatomic, strong) NSTimer *stopTimer;
@property(nonatomic, strong) NSTimer *finishTimer;
@property(nonatomic, copy) void (^finished)(NSDictionary *);
@property(nonatomic) HIDClient hidClient;
@property(nonatomic) double started;
@property(nonatomic) double stopped;
@property(nonatomic) BOOL stopping;
@property(nonatomic) BOOL complete;
- (void)start:(double)seconds directory:(NSString *)directory;
- (void)receive:(NSString *)kind timestamp:(double)timestamp values:(NSArray *)values error:(NSError *)error;
- (void)als:(HIDEvent)event service:(HIDService)service;
- (void)hidEvent:(HIDEvent)event service:(HIDService)service;
- (void)captureHIDServices:(NSString *)phase;
- (void)orientation:(NSDictionary *)record;
- (void)stop;
- (void)captureKernelDiagnostics:(NSString *)phase;
- (NSDictionary *)report;
@end

static double uptime(void) { return NSProcessInfo.processInfo.systemUptime; }

static void hid_event(void *target, void *context, HIDService service, HIDEvent event)
{
    (void)target;
    [(__bridge NabuSensorProbe *)context hidEvent:event service:service];
}

@implementation NabuSensorProbe
- (void)write:(NSDictionary *)record
{
    NSError *error;
    NSData *data = [NSJSONSerialization dataWithJSONObject:record options:0 error:&error];
    if (!data) { fprintf(stderr, "sensor JSON error: %s\n", error.description.UTF8String); return; }
    [self.events writeData:data];
    [self.events writeData:[@"\n" dataUsingEncoding:NSUTF8StringEncoding]];
}

- (void)captureKernelDiagnostics:(NSString *)phase
{
    BOOL first = [phase isEqualToString:@"start"];
    NSString *suffix = first ? @"-start" : @"";
    NSString *slpiFile = [NSString stringWithFormat:@"slpi-report%@.txt", suffix];
    NSString *sourcesFile = [NSString stringWithFormat:@"sensor-sources%@.plist", suffix];
    NSMutableDictionary *snapshot = [@{@"phase":phase, @"uptime":@(uptime()),
        @"slpi_file":slpiFile, @"sources_file":sourcesFile} mutableCopy];
    NSData *slpiData = [NSData data];
    io_registry_entry_t chosen = IORegistryEntryFromPath(kIOMainPortDefault, "IODeviceTree:/chosen");
    snapshot[@"chosen_found"] = @(chosen != IO_OBJECT_NULL);
    if (chosen) {
        CFTypeRef value = IORegistryEntryCreateCFProperty(chosen, CFSTR("nabu-slpi-report"), kCFAllocatorDefault, 0);
        snapshot[@"slpi_property_present"] = @(value != NULL);
        if (value) {
            CFTypeID type = CFGetTypeID(value);
            if (type == CFDataGetTypeID()) {
                snapshot[@"slpi_property_type"] = @"CFData";
                slpiData = [(__bridge NSData *)value copy];
            } else if (type == CFStringGetTypeID()) {
                snapshot[@"slpi_property_type"] = @"CFString";
                slpiData = [(__bridge NSString *)value dataUsingEncoding:NSUTF8StringEncoding];
            } else {
                CFStringRef typeName = CFCopyTypeIDDescription(type);
                snapshot[@"slpi_property_type"] = (__bridge_transfer NSString *)typeName;
                snapshot[@"slpi_error"] = @"unsupported property type; no text representation substituted";
            }
            CFRelease(value);
        }
        IOObjectRelease(chosen);
    }
    NSError *writeError = nil;
    snapshot[@"slpi_bytes"] = @(slpiData.length);
    // Write even when absent, so an older run's report is never left as current.
    BOOL saved = [slpiData writeToFile:[self.directory stringByAppendingPathComponent:slpiFile]
        options:NSDataWritingAtomic error:&writeError];
    snapshot[@"slpi_write_ok"] = @(saved);
    if (writeError) snapshot[@"slpi_write_error"] = writeError.localizedDescription;
    if (first) {
        NSError *latestError = nil;
        snapshot[@"latest_slpi_write_ok"] = @([slpiData writeToFile:[self.directory stringByAppendingPathComponent:@"slpi-report.txt"]
            options:NSDataWritingAtomic error:&latestError]);
        if (latestError) snapshot[@"latest_slpi_write_error"] = latestError.localizedDescription;
    }

    io_iterator_t iterator = IO_OBJECT_NULL;
    kern_return_t status = IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("NabuSensorSource"), &iterator);
    snapshot[@"source_matching_status"] = @(status);
    NSMutableArray *sources = [NSMutableArray array];
    if (status == KERN_SUCCESS) {
        io_service_t service;
        while ((service = IOIteratorNext(iterator))) {
            NSMutableDictionary *item = [NSMutableDictionary dictionary];
            uint64_t registryID = 0;
            kern_return_t idStatus = IORegistryEntryGetRegistryEntryID(service, &registryID);
            item[@"registry_id_status"] = @(idStatus);
            if (idStatus == KERN_SUCCESS) item[@"registry_id"] = @(registryID);
            io_name_t className = {0};
            if (IOObjectGetClass(service, className) == KERN_SUCCESS) item[@"class"] = [NSString stringWithUTF8String:className];
            CFMutableDictionaryRef properties = NULL;
            kern_return_t propertyStatus = IORegistryEntryCreateCFProperties(service, &properties, kCFAllocatorDefault, 0);
            item[@"properties_status"] = @(propertyStatus);
            if (propertyStatus == KERN_SUCCESS && properties) item[@"properties"] = (__bridge_transfer NSDictionary *)properties;
            [sources addObject:item];
            IOObjectRelease(service);
        }
        IOObjectRelease(iterator);
    }
    snapshot[@"source_count"] = @(sources.count);
    NSError *propertyError = nil;
    NSData *propertyData = [NSPropertyListSerialization dataWithPropertyList:sources format:NSPropertyListBinaryFormat_v1_0 options:0 error:&propertyError];
    BOOL propertiesSaved = propertyData && [propertyData writeToFile:[self.directory stringByAppendingPathComponent:sourcesFile]
        options:NSDataWritingAtomic error:&propertyError];
    snapshot[@"source_properties_write_ok"] = @(propertiesSaved);
    if (propertyError) snapshot[@"source_properties_error"] = propertyError.localizedDescription;
    if (first && propertyData) {
        NSError *latestError = nil;
        snapshot[@"latest_source_properties_write_ok"] = @([propertyData writeToFile:[self.directory stringByAppendingPathComponent:@"sensor-sources.plist"]
            options:NSDataWritingAtomic error:&latestError]);
        if (latestError) snapshot[@"latest_source_properties_error"] = latestError.localizedDescription;
    }
    [self.diagnosticSnapshots addObject:snapshot];
    [self write:@{@"kind":@"kernel_diagnostics", @"snapshot":snapshot}];
    NSData *metadata = [NSJSONSerialization dataWithJSONObject:self.diagnosticSnapshots options:NSJSONWritingPrettyPrinted error:NULL];
    [metadata writeToFile:[self.directory stringByAppendingPathComponent:@"kernel-diagnostics.json"] atomically:YES];
}

- (void)startHID
{
    void *library = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_NOW | RTLD_LOCAL);
    if (!library) { self.hidStatus = @"IOKit load failed"; return; }
#define LOAD(field, symbol) do { hid.field = dlsym(library, symbol); if (!hid.field) { self.hidStatus = @"missing " symbol; return; } } while (0)
    LOAD(create, "IOHIDEventSystemClientCreateWithType");
    LOAD(match_multiple, "IOHIDEventSystemClientSetMatchingMultiple");
    LOAD(services, "IOHIDEventSystemClientCopyServices");
    LOAD(register_event, "IOHIDEventSystemClientRegisterEventCallback");
    LOAD(schedule, "IOHIDEventSystemClientScheduleWithDispatchQueue");
    LOAD(unschedule, "IOHIDEventSystemClientUnscheduleFromDispatchQueue");
    LOAD(type, "IOHIDEventGetType");
    LOAD(timestamp, "IOHIDEventGetTimeStamp");
    LOAD(integer, "IOHIDEventGetIntegerValue");
    LOAD(floating, "IOHIDEventGetFloatValue");
    LOAD(registry_id, "IOHIDServiceClientGetRegistryID");
    LOAD(copy_property, "IOHIDServiceClientCopyProperty");
#undef LOAD
    self.hidClient = hid.create(NULL, 1, NULL); /* Monitor, not an injector. */
    if (!self.hidClient) { self.hidStatus = @"monitor creation failed"; return; }
    NSMutableArray *matches = [NSMutableArray array];
    for (NSNumber *usage in @[@3, @9, @10, @4])
        [matches addObject:@{@"DeviceUsagePage":@0xff00, @"DeviceUsage":usage}];
    hid.match_multiple(self.hidClient, (__bridge CFArrayRef)matches);
    hid.register_event(self.hidClient, hid_event, NULL, (__bridge void *)self);
    hid.schedule(self.hidClient, dispatch_get_main_queue());
    self.hidStatus = @"scheduled; delivery unverified";
}

- (void)captureHIDServices:(NSString *)phase
{
    NSMutableArray *services = [NSMutableArray array];
    CFArrayRef found = self.hidClient ? hid.services(self.hidClient) : NULL;
    for (CFIndex i = 0; found && i < CFArrayGetCount(found); ++i) {
        HIDService service = (HIDService)CFArrayGetValueAtIndex(found, i);
        NSMutableDictionary *item = [NSMutableDictionary dictionary];
        CFTypeRef registryID = hid.registry_id(service);
        if (registryID && CFGetTypeID(registryID) == CFNumberGetTypeID())
            item[@"registry_id"] = (__bridge NSNumber *)registryID;
        for (NSString *key in @[@"Product", @"Manufacturer", @"Built-In", @"Transport",
            @"DeviceUsagePage", @"DeviceUsage", @"PrimaryUsagePage", @"PrimaryUsage",
            @"ReportInterval", @"BatchInterval", @"NabuSourceRegistryID", @"NabuSourceGeneration"] ) {
            CFTypeRef value = hid.copy_property(service, (__bridge CFStringRef)key);
            if (value) { item[key] = [(__bridge id)value description]; CFRelease(value); }
        }
        [services addObject:item];
    }
    NSMutableDictionary *snapshot = [@{@"phase":phase, @"uptime":@(uptime()),
        @"client_created":@(self.hidClient != NULL), @"copy_services_returned":@(found != NULL),
        @"services":services} mutableCopy];
    if (found) CFRelease(found);
    [self.hidServiceSnapshots addObject:snapshot];
    [self write:@{@"kind":@"hid_services", @"snapshot":snapshot}];
}

- (void)start:(double)seconds directory:(NSString *)directory
{
    self.directory = directory;
    [[NSFileManager defaultManager] createDirectoryAtPath:directory withIntermediateDirectories:YES attributes:nil error:NULL];
    NSString *path = [directory stringByAppendingPathComponent:@"sensor-events.jsonl"];
    [[NSFileManager defaultManager] createFileAtPath:path contents:[NSData data] attributes:nil];
    self.events = [NSFileHandle fileHandleForWritingAtPath:path];
    self.channels = [NSMutableDictionary dictionary];
    self.alsServices = [NSMutableArray array];
    self.hidServiceSnapshots = [NSMutableArray array];
    self.orientationEvents = [NSMutableArray array];
    self.diagnosticSnapshots = [NSMutableArray array];
    self.started = uptime();
    for (NSString *name in @[@"accelerometer", @"gyroscope", @"magnetometer", @"deviceMotion", @"ambientLight",
        @"hidAccelerometer", @"hidGyroscope", @"hidMagnetometer"])
        self.channels[name] = [@{@"samples":@0, @"errors":@0, @"nonmonotonic":@0, @"invalid":@0,
                                  @"callbacks_after_stop":@0, @"latest_timestamp":@0} mutableCopy];
    self.motion = [[CMMotionManager alloc] init];
    self.motion.accelerometerUpdateInterval = 0.04;
    self.motion.gyroUpdateInterval = 0.04;
    self.motion.magnetometerUpdateInterval = 0.04;
    self.motion.deviceMotionUpdateInterval = 0.04;
    self.availability = @{@"accelerometer":@(self.motion.accelerometerAvailable),
        @"gyroscope":@(self.motion.gyroAvailable), @"magnetometer":@(self.motion.magnetometerAvailable),
        @"deviceMotion":@(self.motion.deviceMotionAvailable),
        @"attitude_reference_frames":@([CMMotionManager availableAttitudeReferenceFrames])};
    [self startHID];
    [self write:@{@"kind":@"start", @"uptime":@(self.started), @"seconds":@(seconds),
        @"availability":self.availability, @"hid":self.hidStatus,
        @"note":@"availability is a system declaration; only callbacks establish data delivery"}];
    [self captureKernelDiagnostics:@"start"];
    [self captureHIDServices:@"start"];
    NSOperationQueue *queue = NSOperationQueue.mainQueue;
    __weak NabuSensorProbe *weak = self;
    if (self.motion.accelerometerAvailable)
        [self.motion startAccelerometerUpdatesToQueue:queue withHandler:^(CMAccelerometerData *data, NSError *error) {
            CMAcceleration a = data.acceleration;
            [weak receive:@"accelerometer" timestamp:data.timestamp values:@[@(a.x), @(a.y), @(a.z)] error:error];
        }];
    if (self.motion.gyroAvailable)
        [self.motion startGyroUpdatesToQueue:queue withHandler:^(CMGyroData *data, NSError *error) {
            CMRotationRate a = data.rotationRate;
            [weak receive:@"gyroscope" timestamp:data.timestamp values:@[@(a.x), @(a.y), @(a.z)] error:error];
        }];
    if (self.motion.magnetometerAvailable)
        [self.motion startMagnetometerUpdatesToQueue:queue withHandler:^(CMMagnetometerData *data, NSError *error) {
            CMMagneticField a = data.magneticField;
            [weak receive:@"magnetometer" timestamp:data.timestamp values:@[@(a.x), @(a.y), @(a.z)] error:error];
        }];
    CMAttitudeReferenceFrame frames = [CMMotionManager availableAttitudeReferenceFrames];
    if (self.motion.deviceMotionAvailable && (frames & CMAttitudeReferenceFrameXArbitraryZVertical))
        [self.motion startDeviceMotionUpdatesUsingReferenceFrame:CMAttitudeReferenceFrameXArbitraryZVertical
            toQueue:queue withHandler:^(CMDeviceMotion *data, NSError *error) {
                CMQuaternion q = data.attitude.quaternion;
                CMAcceleration g = data.gravity;
                [weak receive:@"deviceMotion" timestamp:data.timestamp
                    values:@[@(q.x), @(q.y), @(q.z), @(q.w), @(g.x), @(g.y), @(g.z)] error:error];
            }];
    self.stopTimer = [NSTimer scheduledTimerWithTimeInterval:seconds repeats:NO block:^(__unused NSTimer *timer) { [weak stop]; }];
}

- (void)receive:(NSString *)kind timestamp:(double)timestamp values:(NSArray *)values error:(NSError *)error
{
    NSMutableDictionary *state = self.channels[kind];
    if (self.stopping) {
        state[@"callbacks_after_stop"] = @([state[@"callbacks_after_stop"] unsignedLongLongValue] + 1);
        [self write:@{@"kind":@"callback_after_stop", @"sensor":kind, @"timestamp":@(timestamp), @"received":@(uptime())}];
        return;
    }
    if (error) {
        state[@"errors"] = @([state[@"errors"] unsignedLongLongValue] + 1);
        [self write:@{@"kind":@"error", @"sensor":kind, @"domain":error.domain, @"code":@(error.code), @"message":error.localizedDescription}];
        return;
    }
    BOOL valid = isfinite(timestamp) && timestamp > 0;
    for (NSNumber *number in values) valid = valid && isfinite(number.doubleValue);
    if (!valid) { state[@"invalid"] = @([state[@"invalid"] unsignedLongLongValue] + 1); return; }
    uint64_t samples = [state[@"samples"] unsignedLongLongValue];
    if (samples && timestamp <= [state[@"latest_timestamp"] doubleValue])
        state[@"nonmonotonic"] = @([state[@"nonmonotonic"] unsignedLongLongValue] + 1);
    if (!samples) { state[@"first_timestamp"] = @(timestamp); state[@"first_callback_latency"] = @(uptime()-self.started); }
    state[@"samples"] = @(samples + 1);
    state[@"latest_timestamp"] = @(timestamp);
    state[@"latest_values"] = values;
    [self write:@{@"kind":@"sample", @"sensor":kind, @"timestamp":@(timestamp), @"received":@(uptime()), @"values":values}];
}

- (void)hidEvent:(HIDEvent)event service:(HIDService)service
{
    uint32_t type = hid.type(event);
    if (type == 12) { [self als:event service:service]; return; }
    NSString *channel = nil;
    if (type == 13) channel = @"hidAccelerometer";
    else if (type == 20) channel = @"hidGyroscope";
    else if (type == 21) channel = @"hidMagnetometer";
    else return;
    mach_timebase_info_data_t timebase;
    mach_timebase_info(&timebase);
    double stamp = (double)hid.timestamp(event) * timebase.numer / timebase.denom / 1e9;
    uint32_t field = type << 16;
    [self receive:channel timestamp:stamp values:@[@(hid.floating(event, field)),
        @(hid.floating(event, field + 1)), @(hid.floating(event, field + 2))] error:nil];
}

- (void)als:(HIDEvent)event service:(HIDService)service
{
    if (hid.type(event) != 12) return;
    self.hidStatus = @"ALS callback received";
    CFTypeRef identifier = hid.registry_id(service);
    if (identifier && CFGetTypeID(identifier) == CFNumberGetTypeID()) {
        NSNumber *number = (__bridge NSNumber *)identifier;
        if (![[self.alsServices valueForKey:@"registry_id"] containsObject:number]) {
            NSMutableDictionary *item = [@{@"registry_id":number} mutableCopy];
            for (NSString *key in @[@"Product", @"Built-In", @"Orientation", @"Placement", @"ALSSensorType", @"Transport"]) {
                CFTypeRef value = hid.copy_property(service, (__bridge CFStringRef)key);
                if (value) { item[key] = [(__bridge id)value description]; CFRelease(value); }
            }
            io_service_t object = IOServiceGetMatchingService(kIOMainPortDefault, IORegistryEntryIDMatching(number.unsignedLongLongValue));
            item[@"registry_service_found"] = @(object != IO_OBJECT_NULL);
            if (object) {
                io_name_t name = {0};
                if (IOObjectGetClass(object, name) == KERN_SUCCESS) item[@"registry_class"] = [NSString stringWithUTF8String:name];
                IOObjectRelease(object);
            }
            [self.alsServices addObject:item];
            [self write:@{@"kind":@"als_service", @"service":item}];
        }
    }
    mach_timebase_info_data_t timebase;
    mach_timebase_info(&timebase);
    double stamp = (double)hid.timestamp(event) * timebase.numer / timebase.denom / 1e9;
    [self receive:@"ambientLight" timestamp:stamp values:@[@(hid.integer(event, 0xc0000))] error:nil];
}

- (void)orientation:(NSDictionary *)record
{
    if (self.complete) return;
    [self.orientationEvents addObject:record];
    [self write:@{@"kind":@"orientation", @"received":@(uptime()), @"observation":record}];
}

- (NSDictionary *)report
{
    NSMutableDictionary *out = [@{@"schema":@2, @"started_uptime":@(self.started), @"stopped_uptime":@(self.stopped),
        @"complete":@(self.complete), @"availability":self.availability, @"channels":self.channels,
        @"hid_status":self.hidStatus, @"als_services":self.alsServices, @"orientation_events":self.orientationEvents,
        @"hid_service_snapshots":self.hidServiceSnapshots,
        @"kernel_diagnostics":self.diagnosticSnapshots,
        @"automatic_brightness_verified":@NO, @"sensor_hardware_origin_verified_by_probe":@NO,
        @"note":@"CoreMotion and raw HID counters are independent. Only CoreMotion callbacks satisfy raw_three_axis_delivery_passed. Correlate with this boot's SSC records; ALS service presence does not establish AABC initialization."} mutableCopy];
    BOOL raw = YES;
    for (NSString *name in @[@"accelerometer", @"gyroscope", @"magnetometer"]) {
        NSDictionary *state = self.channels[name];
        raw = raw && [state[@"samples"] unsignedLongLongValue] >= 25 &&
            [state[@"nonmonotonic"] unsignedLongLongValue] == 0 && [state[@"invalid"] unsignedLongLongValue] == 0 &&
            [state[@"errors"] unsignedLongLongValue] == 0;
    }
    out[@"raw_three_axis_delivery_passed"] = @(self.complete && raw);
    return out;
}

- (void)stop
{
    if (self.stopping) return;
    self.stopping = YES;
    self.stopped = uptime();
    [self captureHIDServices:@"stop"];
    [self.motion stopAccelerometerUpdates];
    [self.motion stopGyroUpdates];
    [self.motion stopMagnetometerUpdates];
    [self.motion stopDeviceMotionUpdates];
    if (self.hidClient) {
        hid.unschedule(self.hidClient, dispatch_get_main_queue());
    }
    [self write:@{@"kind":@"stop", @"uptime":@(self.stopped)}];
    __weak NabuSensorProbe *weak = self;
    self.finishTimer = [NSTimer scheduledTimerWithTimeInterval:1 repeats:NO block:^(__unused NSTimer *timer) {
        NabuSensorProbe *strong = weak;
        [strong captureKernelDiagnostics:@"finish"];
        if (strong.hidClient) { CFRelease(strong.hidClient); strong.hidClient = NULL; }
        strong.complete = YES;
        NSDictionary *report = strong.report;
        NSData *json = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:NULL];
        [json writeToFile:[strong.directory stringByAppendingPathComponent:@"sensor-result.json"] atomically:YES];
        [strong write:@{@"kind":@"result", @"result":report}];
        [strong.events synchronizeFile];
        [strong.events closeFile];
        fprintf(stdout, "%s\n", [[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding].UTF8String);
        if (strong.finished) strong.finished(report);
    }];
}
@end

#ifdef NABU_SENSOR_PROBE_APP
@interface SensorViewController : UIViewController
@property(nonatomic, strong) NabuSensorProbe *probe;
@property(nonatomic, strong) UILabel *label;
@property(nonatomic, strong) UIButton *sampleButton;
- (void)beginSampling;
@end
@implementation SensorViewController
- (void)viewDidLoad
{
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.systemBackgroundColor;
    self.label = [[UILabel alloc] init];
    self.label.numberOfLines = 0;
    self.label.font = [UIFont monospacedSystemFontOfSize:21 weight:UIFontWeightRegular];
    self.label.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:self.label];
    [NSLayoutConstraint activateConstraints:@[[self.label.leadingAnchor constraintEqualToAnchor:self.view.safeAreaLayoutGuide.leadingAnchor constant:32],
        [self.label.trailingAnchor constraintEqualToAnchor:self.view.safeAreaLayoutGuide.trailingAnchor constant:-32],
        [self.label.centerYAnchor constraintEqualToAnchor:self.view.centerYAnchor]]];
    self.sampleButton = [UIButton buttonWithType:UIButtonTypeSystem];
    [self.sampleButton setTitle:@"重新采样" forState:UIControlStateNormal];
    self.sampleButton.titleLabel.font = [UIFont systemFontOfSize:22];
    self.sampleButton.translatesAutoresizingMaskIntoConstraints = NO;
    [self.sampleButton addTarget:self action:@selector(beginSampling) forControlEvents:UIControlEventTouchUpInside];
    [self.view addSubview:self.sampleButton];
    [NSLayoutConstraint activateConstraints:@[
        [self.sampleButton.topAnchor constraintEqualToAnchor:self.label.bottomAnchor constant:28],
        [self.sampleButton.centerXAnchor constraintEqualToAnchor:self.view.centerXAnchor]]];
    [self beginSampling];
    [[UIDevice currentDevice] beginGeneratingDeviceOrientationNotifications];
    [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(deviceOrientation:) name:UIDeviceOrientationDidChangeNotification object:nil];
}
- (void)beginSampling
{
    self.sampleButton.enabled = NO;
    self.label.text = @"传感器诊断：正在采样30秒\n\n请缓慢转动平板，并遮挡、移开前置光线传感器。\n\n结束后会显示各通道实际样本数。";
    self.probe = [[NabuSensorProbe alloc] init];
    __weak SensorViewController *weak = self;
    self.probe.finished = ^(NSDictionary *report) {
        NSDictionary *c = report[@"channels"];
        weak.label.text = [NSString stringWithFormat:@"采样完成\n\n加速度：%@\n陀螺仪：%@\n磁场：%@\n融合姿态：%@\n环境光：%@\n\n原生三轴数据：%@\n报告已保存，自动亮度需单独实测。",
            c[@"accelerometer"][@"samples"], c[@"gyroscope"][@"samples"], c[@"magnetometer"][@"samples"],
            c[@"deviceMotion"][@"samples"], c[@"ambientLight"][@"samples"],
            [report[@"raw_three_axis_delivery_passed"] boolValue] ? @"已收到" : @"未通过"];
        weak.sampleButton.enabled = YES;
    };
    NSString *directory = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES).firstObject;
    [self.probe start:30 directory:directory];
}
- (void)deviceOrientation:(NSNotification *)notification
{
    (void)notification;
    [self.probe orientation:@{@"device_orientation":@([UIDevice currentDevice].orientation)}];
}
- (void)viewWillTransitionToSize:(CGSize)size withTransitionCoordinator:(id<UIViewControllerTransitionCoordinator>)coordinator
{
    [super viewWillTransitionToSize:size withTransitionCoordinator:coordinator];
    [self.probe orientation:@{@"view_width":@(size.width), @"view_height":@(size.height)}];
}
- (UIInterfaceOrientationMask)supportedInterfaceOrientations { return UIInterfaceOrientationMaskAll; }
- (BOOL)shouldAutorotate { return YES; }
@end
@interface SensorAppDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic, strong) UIWindow *window;
@end
@implementation SensorAppDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options
{
    (void)application; (void)options;
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    self.window.rootViewController = [[SensorViewController alloc] init];
    [self.window makeKeyAndVisible];
    return YES;
}
@end
int main(int argc, char **argv)
{
    @autoreleasepool { return UIApplicationMain(argc, argv, nil, NSStringFromClass(SensorAppDelegate.class)); }
}
#else
int main(int argc, char **argv)
{
    @autoreleasepool {
        if (argc != 3) { fprintf(stderr, "usage: nabu-sensor-probe SECONDS OUTPUT_DIRECTORY\n"); return 2; }
        double seconds = strtod(argv[1], NULL);
        if (!isfinite(seconds) || seconds < 1 || seconds > 120) return 2;
        NabuSensorProbe *probe = [[NabuSensorProbe alloc] init];
        [probe start:seconds directory:[NSString stringWithUTF8String:argv[2]]];
        while (!probe.complete) @autoreleasepool { [NSRunLoop.mainRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.1]]; }
        return [probe.report[@"raw_three_axis_delivery_passed"] boolValue] ? 0 : 1;
    }
}
#endif
