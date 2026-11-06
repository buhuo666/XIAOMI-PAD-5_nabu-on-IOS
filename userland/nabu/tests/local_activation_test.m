#import <Foundation/Foundation.h>
#include <fcntl.h>
#include <errno.h>
#include <dlfcn.h>
#include <assert.h>
static BOOL failFullSync;
static int testFcntl(int descriptor, int command, ...) {
    assert(command == F_FULLFSYNC);
    if (failFullSync) { errno = EIO; return -1; }
    int (*realFcntl)(int, int, ...) = dlsym(RTLD_DEFAULT, "fcntl");
    return realFcntl(descriptor, command);
}
#define fcntl testFcntl
#define main nabu_daemon_main
#include "../src/local_activation.m"
#undef main
#undef fcntl

int main(void) {
    @autoreleasepool {
        stateDirectory = [NSTemporaryDirectory() stringByAppendingPathComponent:
                          [@"nabu-activation-test-" stringByAppendingString:NSUUID.UUID.UUIDString]];
        statePath = [stateDirectory stringByAppendingPathComponent:@"state.plist"];
        failFullSync = YES;
        assert(!loadState());
        assert([[NSFileManager defaultManager] fileExistsAtPath:statePath]);
        assert(!loadState()); // A failed initial flush cannot pass on retry.
        failFullSync = NO;
        assert(loadState());
        NSDictionary *first = localState;
        localState = nil;
        assert(loadState());
        assert([localState isEqual:first]);
        assert([localState[@"AppleServerValidated"] isEqual:@NO]);
        NabuLocalActivation *provider = [NabuLocalActivation new];
        __block unsigned replies = 0;
        [provider getActivationStateWithCompletionBlock:^(NSDictionary *r, NSError *e) {
            assert(!e && [r[@"ActivationState"] isEqual:@"Activated"]); ++replies;
        }];
        [provider isDeviceBrickedWithCompletionBlock:^(NSDictionary *r, NSError *e) {
            assert(!e && [r[@"BrickState"] isEqual:@NO]); ++replies;
        }];
        [provider getActivationBuildWithCompletionBlock:^(NSDictionary *r, NSError *e) {
            assert(!e && [r[@"LastActivated"] isEqual:@"20F66"]); ++replies;
        }];
        [provider getDCRTStateWithCompletionBlock:^(NSDictionary *r, NSError *e) {
            assert(!e && [r[@"DCRTState"] isEqual:@"DCRTUnavailable"]); ++replies;
        }];
        reject(provider, sel_registerName("copyActivationRecordWithCompletionBlock:"),
               ^(NSDictionary *r, NSError *e) { assert(!r && e.code == ENOTSUP); ++replies; });
        assert(replies == 5);
        NSMutableDictionary *wrong = [localState mutableCopy];
        wrong[@"DeviceUUID"] = @"different-device";
        assert([wrong writeToFile:statePath atomically:YES]);
        assert(!loadState());
        [[NSFileManager defaultManager] removeItemAtPath:stateDirectory error:NULL];
        puts("PASS: failed flush/retry, persistent state reload, identity binding, exact state replies and unsupported certificate request");
    }
    return 0;
}
