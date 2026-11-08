/* Explicit paired-host audio observations and a short A2DP-only playback trial. */
#import <Foundation/Foundation.h>
#import <AVFAudio/AVFAudio.h>
#include <errno.h>
#include <dlfcn.h>
#include <math.h>
#include <sys/stat.h>
#include <unistd.h>

static BOOL audioBusy;
static NSString *const audioReportPath = @"/private/var/mobile/Media/NabuServices/audio-trial.json";
static NSString *const audioAFCPath = @"/NabuServices/audio-trial.json";

@interface NabuAudioPlaybackObserver : NSObject <AVAudioPlayerDelegate>
@property BOOL finished;
@property BOOL success;
@property(nonatomic, strong) NSError *decodeError;
@end
@implementation NabuAudioPlaybackObserver
- (void)audioPlayerDidFinishPlaying:(AVAudioPlayer *)player successfully:(BOOL)flag {
    (void)player; self.finished = YES; self.success = flag;
}
- (void)audioPlayerDecodeErrorDidOccur:(AVAudioPlayer *)player error:(NSError *)error {
    (void)player; self.decodeError = error;
}
@end

static NSDictionary *audioError(NSError *error) {
    return error ? @{@"domain": error.domain, @"code": @(error.code),
                     @"description": error.localizedDescription ?: @""} : @{};
}

static void audioCheckpoint(NSMutableDictionary *report, NSString *stage) {
    report[@"stage"] = stage;
    report[@"updated_uptime"] = @(NSProcessInfo.processInfo.systemUptime);
    NSData *data = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:NULL];
    NSError *writeError = nil;
    BOOL saved = [data writeToFile:audioReportPath options:NSDataWritingAtomic error:&writeError];
    NSLog(@"NABU AUDIO: stage=%@ action=%@ report_saved=%d error=%@",
          stage, report[@"action"], saved, writeError ?: @"");
}

static NSArray *audioPorts(NSArray<AVAudioSessionPortDescription *> *ports) {
    NSMutableArray *out = [NSMutableArray array];
    for (AVAudioSessionPortDescription *port in ports)
        [out addObject:@{@"type": port.portType, @"channels": @(port.channels.count)}];
    return out;
}

static NSDictionary *audioRoute(AVAudioSession *session) {
    AVAudioSessionRouteDescription *route = session.currentRoute;
    return @{@"outputs": audioPorts(route.outputs), @"inputs": audioPorts(route.inputs)};
}

static NSDictionary *audioSessionSnapshot(AVAudioSession *session) {
    return @{@"route": audioRoute(session), @"category": session.category, @"mode": session.mode,
        @"category_options": @(session.categoryOptions), @"sample_rate": @(session.sampleRate),
        @"preferred_sample_rate": @(session.preferredSampleRate), @"io_buffer_seconds": @(session.IOBufferDuration),
        @"output_channels": @(session.outputNumberOfChannels), @"input_channels": @(session.inputNumberOfChannels),
        @"output_latency_seconds": @(session.outputLatency), @"output_volume": @(session.outputVolume),
        @"input_available": @(session.isInputAvailable), @"other_audio_playing": @(session.isOtherAudioPlaying)};
}

static NSDictionary *audioFiles(void) {
    NSFileManager *fm = NSFileManager.defaultManager;
    NSMutableDictionary *out = [NSMutableDictionary dictionary];
    for (NSString *folder in @[@"/System/Library/Audio/Plug-Ins/HAL", @"/Library/Audio/Plug-Ins/HAL", @"/redwood/hal"]) {
        NSError *error = nil;
        NSArray *names = [fm contentsOfDirectoryAtPath:folder error:&error];
        NSMutableArray *entries = [NSMutableArray array];
        for (NSString *name in names) {
            NSString *path = [folder stringByAppendingPathComponent:name];
            NSDictionary *info = [NSDictionary dictionaryWithContentsOfFile:[path stringByAppendingPathComponent:@"Info.plist"]];
            if (!info) info = [NSDictionary dictionaryWithContentsOfFile:[path stringByAppendingPathComponent:@"Contents/Info.plist"]];
            [entries addObject:@{@"name": name, @"bundle_identifier": info[@"CFBundleIdentifier"] ?: NSNull.null,
                @"executable": info[@"CFBundleExecutable"] ?: NSNull.null}];
        }
        out[folder] = @{@"error": audioError(error), @"entries": entries};
    }
    for (NSString *path in @[@"/dev/hakios-audio", @"/dev/hakios-mic", @"/dev/uart.bluetooth"]) {
        struct stat st; int rc = stat(path.fileSystemRepresentation, &st);
        out[path] = @{@"exists": @(rc == 0), @"errno": @(rc == 0 ? 0 : errno),
            @"character_device": @(rc == 0 && S_ISCHR(st.st_mode))};
    }
    return out;
}

static id audioHardwareReport(void) {
    void *kit = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_NOW);
    if (!kit) return NSNull.null;
    uint32_t (*fromPath)(uint32_t, const char *) = dlsym(kit, "IORegistryEntryFromPath");
    CFTypeRef (*property)(uint32_t, CFStringRef, CFAllocatorRef, uint32_t) = dlsym(kit, "IORegistryEntryCreateCFProperty");
    int (*release)(uint32_t) = dlsym(kit, "IOObjectRelease");
    uint32_t chosen = fromPath(0, "IODeviceTree:/chosen");
    id report = chosen ? CFBridgingRelease(property(chosen, CFSTR("nabu-adsp-report"), NULL, 0)) : nil;
    if (chosen) release(chosen);
    dlclose(kit);
    if ([report isKindOfClass:NSData.class]) report = [[NSString alloc] initWithData:report encoding:NSUTF8StringEncoding];
    return report ?: NSNull.null;
}

static void little32(uint8_t *out, uint32_t value) { value = CFSwapInt32HostToLittle(value); memcpy(out, &value, 4); }
static void little16(uint8_t *out, uint16_t value) { value = CFSwapInt16HostToLittle(value); memcpy(out, &value, 2); }

static NSData *audioTestWave(void) {
    const uint32_t rate = 48000, frames = rate * 3, bytes = frames * 4;
    NSMutableData *data = [NSMutableData dataWithLength:44 + bytes];
    uint8_t *out = data.mutableBytes;
    memcpy(out, "RIFF", 4); little32(out + 4, 36 + bytes); memcpy(out + 8, "WAVEfmt ", 8);
    little32(out + 16, 16); little16(out + 20, 1); little16(out + 22, 2);
    little32(out + 24, rate); little32(out + 28, rate * 4); little16(out + 32, 4); little16(out + 34, 16);
    memcpy(out + 36, "data", 4); little32(out + 40, bytes);
    for (uint32_t i = 0; i < frames; ++i) {
        double t = (double)i / rate;
        // Left then right then both; gaps and short fades make the trial recognizable.
        unsigned segment = (unsigned)t;
        double local = t - segment;
        if (local >= 0.65) continue;
        double fade = fmin(1.0, fmin(local / 0.03, (0.65 - local) / 0.03));
        int16_t left = segment != 1 ? (int16_t)(1200.0 * fade * sin(2.0 * M_PI * 440.0 * t)) : 0;
        int16_t right = segment != 0 ? (int16_t)(1200.0 * fade * sin(2.0 * M_PI * 660.0 * t)) : 0;
        little16(out + 44 + i * 4, (uint16_t)left);
        little16(out + 46 + i * 4, (uint16_t)right);
    }
    return data;
}

static BOOL audioHasA2DP(AVAudioSession *session) {
    for (AVAudioSessionPortDescription *port in session.currentRoute.outputs)
        if ([port.portType isEqualToString:AVAudioSessionPortBluetoothA2DP]) return YES;
    return NO;
}

static void audioRun(NSString *action, NSString *identifier) {
    NSMutableDictionary *report = [@{@"action": action, @"request_id": identifier,
        @"uid": @(getuid()), @"started_uptime": @(NSProcessInfo.processInfo.systemUptime),
        @"microphone_capture": @NO, @"system_volume_changed": @NO,
        @"interpretation": @"Route and API completion are observations; only listening confirms audible playback."} mutableCopy];
    AVAudioSession *session = nil;
    BOOL activated = NO, categoryChanged = NO;
    NSString *oldCategory = nil, *oldMode = nil;
    AVAudioSessionCategoryOptions oldOptions = 0;
    @try {
        report[@"files"] = audioFiles();
        report[@"adsp"] = audioHardwareReport();
        audioCheckpoint(report, @"AVAudioSession-enter");
        session = AVAudioSession.sharedInstance;
        audioCheckpoint(report, @"session-snapshot-enter");
        report[@"before"] = audioSessionSnapshot(session);
        audioCheckpoint(report, @"inventory-complete");
        if ([action isEqualToString:@"AudioBluetoothPlaybackTrial"]) {
            oldCategory = session.category; oldMode = session.mode; oldOptions = session.categoryOptions;
            NSError *error = nil;
            audioCheckpoint(report, @"category-enter");
            BOOL ok = [session setCategory:AVAudioSessionCategoryPlayback mode:AVAudioSessionModeDefault options:0 error:&error];
            categoryChanged = ok;
            report[@"set_category"] = @{@"ok": @(ok), @"error": audioError(error)};
            if (ok) {
                error = nil; audioCheckpoint(report, @"activate-enter");
                activated = [session setActive:YES error:&error];
                report[@"activate"] = @{@"ok": @(activated), @"error": audioError(error)};
            }
            report[@"active_route"] = audioRoute(session);
            if (activated && audioHasA2DP(session)) {
                error = nil; audioCheckpoint(report, @"player-create-enter");
                AVAudioPlayer *player = [[AVAudioPlayer alloc] initWithData:audioTestWave() error:&error];
                report[@"player_created"] = @(player != nil); report[@"player_error"] = audioError(error);
                if (player) {
                    NabuAudioPlaybackObserver *observer = [NabuAudioPlaybackObserver new];
                    player.delegate = observer; player.volume = 1.0; player.meteringEnabled = YES;
                    report[@"wave"] = @{@"sample_rate": @48000, @"channels": @2, @"seconds": @3, @"peak_pcm16": @1200};
                    audioCheckpoint(report, @"prepare-enter");
                    BOOL prepared = [player prepareToPlay]; report[@"prepared"] = @(prepared);
                    audioCheckpoint(report, @"play-enter");
                    BOOL started = prepared && [player play]; report[@"play_return"] = @(started);
                    audioCheckpoint(report, @"playing");
                    double began = NSProcessInfo.processInfo.systemUptime;
                    double lastTime = 0;
                    while (started && !observer.finished && !observer.decodeError &&
                           NSProcessInfo.processInfo.systemUptime - began < 6.0) {
                        [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
                        lastTime = fmax(lastTime, player.currentTime);
                        if (!audioHasA2DP(session)) { report[@"route_changed_away_from_a2dp"] = @YES; break; }
                    }
                    report[@"player_result"] = @{@"delegate_finished": @(observer.finished), @"delegate_success": @(observer.success),
                        @"last_observed_time": @(lastTime), @"decode_error": audioError(observer.decodeError),
                        @"elapsed_seconds": @(NSProcessInfo.processInfo.systemUptime - began)};
                    [player stop]; player.delegate = nil;
                }
            } else report[@"playback_skipped"] = activated ? @"Current output is not BluetoothA2DP" : @"Audio session activation failed";
            report[@"after_playback"] = audioSessionSnapshot(session);
        }
    } @catch (NSException *exception) {
        report[@"exception"] = @{@"name": exception.name, @"reason": exception.reason ?: @""};
    } @finally {
        NSError *error = nil;
        if (activated) {
            BOOL ok = [session setActive:NO withOptions:AVAudioSessionSetActiveOptionNotifyOthersOnDeactivation error:&error];
            report[@"deactivate"] = @{@"ok": @(ok), @"error": audioError(error)};
        }
        if (categoryChanged) {
            error = nil; BOOL ok = [session setCategory:oldCategory mode:oldMode options:oldOptions error:&error];
            report[@"restore_category"] = @{@"ok": @(ok), @"error": audioError(error)};
        }
        audioCheckpoint(report, @"complete");
        @synchronized (NabuAudioPlaybackObserver.class) { audioBusy = NO; }
    }
}

NSDictionary *nabuAudioRequest(NSString *action, NSString *identifier) {
    @synchronized (NabuAudioPlaybackObserver.class) {
        if (audioBusy) return @{@"status": @"busy", @"report_path": audioAFCPath};
        audioBusy = YES;
    }
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        @autoreleasepool { audioRun(action, identifier); }
    });
    return @{@"status": @"queued", @"request_id": identifier, @"report_path": audioAFCPath};
}
