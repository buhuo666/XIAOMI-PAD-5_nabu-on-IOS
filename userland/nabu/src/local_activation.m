/* nabu's local activation-state provider for the supplied 20F66 userland.
 * Uses the original client's NSXPC protocol. No Apple activation record,
 * device certificate, attestation or network transaction is produced.
 */
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <notify.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <unistd.h>
#include <uuid/uuid.h>

typedef void (^Reply)(NSDictionary *, NSError *);
static NSString *const stateDirectory = @"/private/var/db/nabu";
static NSString *const statePath = @"/private/var/db/nabu/local-activation.plist";
static NSDictionary *localState;
static Protocol *activationProtocol;

static NSError *unsupported(SEL selector) {
    return [NSError errorWithDomain:@"org.nabu.LocalActivation" code:ENOTSUP
        userInfo:@{NSLocalizedDescriptionKey:
            [NSString stringWithFormat:@"%@ is unavailable in local activation mode",
                                       NSStringFromSelector(selector)]}];
}

static void reject(id self, SEL selector, Reply reply) {
    (void)self;
    fprintf(stderr, "NABU ACTIVATION: unsupported %s\n", sel_getName(selector));
    reply(nil, unsupported(selector));
}
static void reject2(id self, SEL selector, id arg, Reply reply) {
    (void)arg; reject(self, selector, reply);
}
static void reject3(id self, SEL selector, id arg, id options, Reply reply) {
    (void)arg; (void)options; reject(self, selector, reply);
}
static void reject5(id self, SEL selector, id a, id b, id c, id d, Reply reply) {
    (void)a; (void)b; (void)c; (void)d; reject(self, selector, reply);
}

@interface NabuLocalActivation : NSObject <NSXPCListenerDelegate>
@end

@implementation NabuLocalActivation
- (void)getActivationStateWithCompletionBlock:(Reply)reply {
    fprintf(stderr, "NABU ACTIVATION: state=%s source=local-persistent\n",
            [localState[@"ActivationState"] UTF8String]);
    reply(@{@"ActivationState": localState[@"ActivationState"]}, nil);
}
- (void)isDeviceBrickedWithCompletionBlock:(Reply)reply {
    BOOL activated = [localState[@"ActivationState"] isEqualToString:@"Activated"];
    reply(@{@"BrickState": @(!activated)}, nil);
}
- (void)getActivationBuildWithCompletionBlock:(Reply)reply {
    reply(@{@"LastActivated": localState[@"BuildVersion"]}, nil);
}
- (BOOL)listener:(NSXPCListener *)listener shouldAcceptNewConnection:(NSXPCConnection *)connection {
    (void)listener;
    connection.exportedInterface = [NSXPCInterface interfaceWithProtocol:activationProtocol];
    connection.exportedObject = self;
    fprintf(stderr, "NABU ACTIVATION: client pid=%d uid=%u\n",
            connection.processIdentifier, connection.effectiveUserIdentifier);
    [connection resume];
    return YES;
}
@end

static BOOL bootEnabled(void) {
    char arguments[4096] = {0};
    size_t count = sizeof(arguments) - 1;
    if (sysctlbyname("kern.bootargs", arguments, &count, NULL, 0)) return NO;
    for (NSString *argument in [[NSString stringWithUTF8String:arguments]
                               componentsSeparatedByCharactersInSet:
                               [NSCharacterSet whitespaceAndNewlineCharacterSet]]) {
        if ([argument isEqualToString:@"nabu-local-activation=1"]) return YES;
    }
    return NO;
}

static BOOL loadState(void) {
    uuid_t identity;
    struct timespec timeout = {2, 0};
    if (gethostuuid(identity, &timeout)) {
        fprintf(stderr, "NABU ACTIVATION: gethostuuid errno=%d\n", errno);
        return NO;
    }
    NSString *device = [[[NSUUID alloc] initWithUUIDBytes:identity] UUIDString];
    NSError *error = nil;
    NSData *data = [NSData dataWithContentsOfFile:statePath options:0 error:&error];
    BOOL created = NO;
    if (!data) {
        if (![error.domain isEqualToString:NSCocoaErrorDomain] ||
            error.code != NSFileReadNoSuchFileError) {
            fprintf(stderr, "NABU ACTIVATION: state read error=%s\n", error.description.UTF8String);
            return NO;
        }
        localState = @{@"SchemaVersion": @1, @"Mode": @"NabuLocalCompatibility",
            @"DeviceUUID": device, @"ActivationState": @"Activated",
            @"BuildVersion": @"20F66", @"AppleServerValidated": @NO,
            @"CreatedAt": [NSDate date]};
        if (![[NSFileManager defaultManager] createDirectoryAtPath:stateDirectory
                withIntermediateDirectories:YES attributes:@{NSFilePosixPermissions:@0700}
                error:&error]) return NO;
        data = [NSPropertyListSerialization dataWithPropertyList:localState
                format:NSPropertyListBinaryFormat_v1_0 options:0 error:&error];
        if (!data || ![data writeToFile:statePath options:NSDataWritingAtomic error:&error]) return NO;
        if (chmod(statePath.fileSystemRepresentation, 0600)) return NO;
        int fd = open(statePath.fileSystemRepresentation, O_RDONLY);
        if (fd < 0) return NO;
        int status = fcntl(fd, F_FULLFSYNC);
        close(fd);
        if (status) return NO;
        created = YES;
    } else {
        localState = [NSPropertyListSerialization propertyListWithData:data
                options:NSPropertyListImmutable format:NULL error:&error];
    }
    if (![localState isKindOfClass:[NSDictionary class]] ||
        ![localState[@"Mode"] isEqualToString:@"NabuLocalCompatibility"] ||
        ![localState[@"DeviceUUID"] isEqualToString:device] ||
        ![localState[@"ActivationState"] isEqualToString:@"Activated"] ||
        ![localState[@"BuildVersion"] isEqualToString:@"20F66"] ||
        ![localState[@"AppleServerValidated"] isEqual:@NO]) {
        fprintf(stderr, "NABU ACTIVATION: local state identity or format mismatch\n");
        return NO;
    }
    fprintf(stderr, "NABU ACTIVATION: %s persistent local state; AppleServerValidated=false\n",
            created ? "created and fullfsync'ed" : "restored");
    return YES;
}

static BOOL installUnsupportedMethods(void) {
    unsigned count = 0;
    struct objc_method_description *methods =
        protocol_copyMethodDescriptionList(activationProtocol, YES, YES, &count);
    unsigned installed = 0;
    for (unsigned i = 0; i < count; ++i) {
        SEL selector = methods[i].name;
        if (class_getInstanceMethod([NabuLocalActivation class], selector)) continue;
        unsigned arguments = 0;
        for (const char *p = sel_getName(selector); *p; ++p) arguments += *p == ':';
        IMP implementation = arguments == 1 ? (IMP)reject : arguments == 2 ? (IMP)reject2 :
                             arguments == 3 ? (IMP)reject3 : arguments == 5 ? (IMP)reject5 : NULL;
        if (!implementation || !class_addMethod([NabuLocalActivation class], selector,
                                                 implementation, methods[i].types)) {
            free(methods);
            return NO;
        }
        ++installed;
    }
    free(methods);
    fprintf(stderr, "NABU ACTIVATION: protocol methods=%u explicit-unsupported=%u\n", count, installed);
    return count == 32;
}

int main(void) {
    @autoreleasepool {
        if (!bootEnabled()) {
            fprintf(stderr, "NABU ACTIVATION: explicit boot switch is absent\n");
            return 1;
        }
        if (!dlopen("/System/Library/PrivateFrameworks/MobileActivation.framework/MobileActivation",
                    RTLD_NOW | RTLD_LOCAL)) {
            fprintf(stderr, "NABU ACTIVATION: framework unavailable: %s\n", dlerror());
            return 1;
        }
        activationProtocol = objc_getProtocol("MobileActivationProtocol");
        if (!activationProtocol || !loadState() || !installUnsupportedMethods()) return 1;
        NabuLocalActivation *provider = [NabuLocalActivation new];
        NSXPCListener *listener = [[NSXPCListener alloc]
                                  initWithMachServiceName:@"com.apple.mobileactivationd"];
        listener.delegate = provider;
        [listener resume];
        fprintf(stderr, "NABU ACTIVATION: local NSXPC state provider ready\n");
        [[NSRunLoop currentRunLoop] run];
    }
    return 0;
}
