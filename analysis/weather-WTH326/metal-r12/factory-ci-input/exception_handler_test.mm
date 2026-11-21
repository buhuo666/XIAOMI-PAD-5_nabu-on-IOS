// macOS Foundation runtime check for the actual uncaught-exception helper.
// Invokes its handler with a recorded exception, then verifies the preserved
// previous handler and heap diagnostic without changing termination policy.
#include "ExceptionDiag.h"
#include <cassert>
#include <cstdio>
#include <string>
#include <vector>

static NSException *previousException;
static unsigned previousCalls,observerCalls;
static std::vector<uint32_t> markers;
static void previous(NSException *exception) {previousException=exception;++previousCalls;}
static void observer(const char *,void *) {++observerCalls;}
static int markerOpen(unsigned port,unsigned,uint32_t type,unsigned *connection) {
    assert(port==777 && (type>>16)==0x4147);*connection=0;markers.push_back(type&0xffff);return -1;
}
static int markerClose(unsigned) {assert(false);return -1;}

int main() {
    @autoreleasepool {
        NSUncaughtExceptionHandler *saved=NSGetUncaughtExceptionHandler();
        NSSetUncaughtExceptionHandler(previous);
        nabumetalproblem::gOpen=markerOpen;nabumetalproblem::gClose=markerClose;
        nabumetalproblem::gPort.store(777,std::memory_order_release);
        // The actual start remains referenced for -Wunused-function on the
        // host; the fake marker service is already installed for this check.
        auto start=&nabumetalproblem::start;(void)start;
        exceptiondiag::start();exceptiondiag::start();
        assert(NSGetUncaughtExceptionHandler()==exceptiondiag::handler);
        NSException *exception=[NSException exceptionWithName:@"NabuTestException" reason:@"missing global selector: \n" userInfo:nil];
        exceptiondiag::setReport(nullptr,nullptr);
        exceptiondiag::handler(exception);
        assert(previousCalls==1 && previousException==exception && observerCalls==0);
        assert(exceptiondiag::gText && std::string(exceptiondiag::gText).find("SHENGTHROW NabuTestException | missing global selector: ? |") == 0);
        assert(!markers.empty() && markers.front()==0x6d80 && markers.back()==0x6dff);
        const size_t firstReport=markers.size();
        exceptiondiag::setReport(observer,nullptr);
        exceptiondiag::handler(exception);
        assert(previousCalls==2 && observerCalls==1 && markers.size()>firstReport);
        assert(markers[firstReport]==0x6d80 && NSGetUncaughtExceptionHandler()==exceptiondiag::handler);
        NSSetUncaughtExceptionHandler(saved);
        printf("PASS: direct exception reporting without observer, heap throw text, optional observer, previous handler, once-only installation\n");
    }
}
