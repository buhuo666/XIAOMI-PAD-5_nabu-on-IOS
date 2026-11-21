// SPDX-License-Identifier: MIT
// The throw site of an uncaught Objective-C exception (int-201). MobileSafari aborts with "-[_NSPlaceholderData initWithContentsOfURL:...]: nil URL
// argument" on a dispatch worker, and the crash record's backtrace has only the dispatch frames: the unwinder gave up inside the throw, so which
// caller passed the nil URL is lost. Foundation records the return addresses when it throws (callStackReturnAddresses); this handler copies them,
// with the exception's name and reason, into a malloc'd C string that the kernel's abort-reason scan finds in the dying process's heap
// (kits/sheng/BootFaultProbe.c, "SHENGTHROW ") and the log prints as the THROW row. The original handler (the app's own, or Foundation's) runs
// after it, unchanged; a process that never throws is untouched.
#pragma once
#import <Foundation/Foundation.h>
#include <stdlib.h>
#include <string.h>
#include <exception>
#include <typeinfo>
#include <execinfo.h>
#include "NabuMetalProblemReporter.h"

namespace exceptiondiag {

static NSUncaughtExceptionHandler *gPrevious;
static std::terminate_handler gPreviousTerminate;
static char *gText;   // kept referenced: the text must stay in the heap until the process is gone
static void (*gReport)(const char *,void *);
static void *gReportContext;
[[maybe_unused]] static void setReport(void (*report)(const char *,void *),void *context) {
    gReport=report;gReportContext=context;
}

static void terminateHandler() noexcept {
    // Introspection catches only this rethrow for its type and what().
    // The original fatal exception is still owned by the runtime, and
    // every path invokes the original terminate handler afterward.
    if(std::exception_ptr current=std::current_exception()) {
        try {std::rethrow_exception(current);}
        catch(const std::exception &exception) {
            char text[1024];
            size_t length=size_t(snprintf(text,sizeof(text),"SHENGTHROW C++ %.96s | %.96s |",
                typeid(exception).name(),exception.what()));
            void *frames[20];const int count=backtrace(frames,20);
            for(int i=0;i<count;++i)length+=size_t(snprintf(text+length,sizeof(text)-length,
                " %llx",(unsigned long long)(uintptr_t)frames[i]));
            for(size_t i=0;i<length;++i)if((unsigned char)text[i]<32 || (unsigned char)text[i]>126)text[i]='?';
            gText=strdup(text);
            nabumetalproblem::send(text,true);
            if(gReport)gReport(text,gReportContext);
        } catch(...) {
            // Objective-C / non-std exceptions retain the original
            // runtime handling; Foundation supplies its throw frames.
        }
    }
    gPreviousTerminate();
}

static void handler(NSException *exception) {
    @autoreleasepool {
        NSMutableString *text = [NSMutableString stringWithFormat:@"SHENGTHROW %@ | ", exception.name];
        NSString *reason = exception.reason ?: @"";
        [text appendString:reason.length > 96 ? [reason substringToIndex:96] : reason];
        [text appendString:@" |"];
        NSArray<NSNumber *> *frames = exception.callStackReturnAddresses;
        for (NSUInteger i = 0; i < frames.count && i < 20; ++i) [text appendFormat:@" %llx", (unsigned long long)frames[i].unsignedLongLongValue];
        for (NSUInteger i = 0; i < text.length; ++i) if ([text characterAtIndex:i] < 32 || [text characterAtIndex:i] > 126) [text replaceCharactersInRange:NSMakeRange(i, 1) withString:@"?"];
        if (const char *utf8 = text.UTF8String) {
            gText = strdup(utf8);
            // Every factory client has its own retained diagnostic service.
            // Optional observers no longer gate the persistent throw record.
            nabumetalproblem::send(utf8,true);
            if(gReport)gReport(utf8,gReportContext);
        }
    }
    if (gPrevious) gPrevious(exception);
}
// Every process that loads the plugin, once: the handler is installed in front of whatever the process already had.
static void start() {
    static std::once_flag started;
    std::call_once(started,[] {
        gPrevious = NSGetUncaughtExceptionHandler();
        gPreviousTerminate = std::get_terminate();
        NSSetUncaughtExceptionHandler(handler);
        std::set_terminate(terminateHandler);
    });
}

}  // namespace exceptiondiag
