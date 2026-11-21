// macOS process test: a real exception on dispatch_async_and_wait must still
// terminate the child, after the diagnostic reports the original throw stack.
// The baseline child proves that the diagnostic preserves termination status.
#include "ExceptionDiag.h"
#include <dispatch/dispatch.h>
#include <cassert>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <iomanip>
#include <sstream>
#include <spawn.h>
#include <string>
#include <sys/wait.h>
#include <unistd.h>
#include <vector>

extern char **environ;
static int reportFd=-1;
static constexpr uint32_t previousMarker=0xfacedeadu;
static constexpr uint32_t previousTerminateMarker=0xfacedeeeu;
static std::terminate_handler originalTerminate;
static void writeWord(uint32_t word) {
    if(write(reportFd,&word,sizeof(word))!=sizeof(word))_exit(111);
}
static void previous(NSException *exception) {
    assert([exception.name isEqualToString:@"NabuDispatchException"]);
    writeWord(previousMarker);
}
static void previousTerminate() {
    writeWord(previousTerminateMarker);
    originalTerminate();
}
static int markerOpen(unsigned port,unsigned,uint32_t type,unsigned *connection) {
    assert(port==777 && (type>>16)==0x4147);
    *connection=0;writeWord(type);return -1;
}
static int markerClose(unsigned) {assert(false);return -1;}
[[noreturn]] static void throwOnDispatchWorker() {
    @throw [NSException exceptionWithName:@"NabuDispatchException"
        reason:@"global dispatch selector exception" userInfo:nil];
}
static void throwCppOnDispatchWorker() {
    std::function<void()> missing;
    missing();
}
[[noreturn]] static void child(int fd,bool instrumented,bool cpp) {
    reportFd=fd;
    NSSetUncaughtExceptionHandler(previous);
    originalTerminate=std::get_terminate();std::set_terminate(previousTerminate);
    if(instrumented) {
        nabumetalproblem::gOpen=markerOpen;nabumetalproblem::gClose=markerClose;
        nabumetalproblem::gPort.store(777,std::memory_order_release);
        exceptiondiag::setReport(nullptr,nullptr);
        exceptiondiag::start();
    }
    // A worker enters dispatch_async_and_wait; its block raises through the
    // real libdispatch / Objective-C runtime, with no test catch or rethrow.
    dispatch_queue_t serial=dispatch_queue_create("org.nabu.test.throw",DISPATCH_QUEUE_SERIAL);
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_DEFAULT,0),^{
        dispatch_async_and_wait(serial,^{if(cpp)throwCppOnDispatchWorker();else throwOnDispatchWorker();});
        _exit(77); // Reaching here means the original exception was swallowed.
    });
    dispatch_main();
}
struct ChildResult {int status=0;std::vector<uint32_t> words;};
static ChildResult runChild(const char *executable,bool instrumented,bool cpp) {
    int fds[2];assert(pipe(fds)==0);
    char fdText[32];snprintf(fdText,sizeof(fdText),"%d",fds[1]);
    char *arguments[]={const_cast<char *>(executable),const_cast<char *>("--child"),
        fdText,const_cast<char *>(instrumented?"instrumented":"baseline"),
        const_cast<char *>(cpp?"cpp":"objc"),nullptr};
    posix_spawn_file_actions_t actions;assert(posix_spawn_file_actions_init(&actions)==0);
    assert(posix_spawn_file_actions_addclose(&actions,fds[0])==0);
    pid_t pid=0;
    assert(posix_spawnp(&pid,executable,&actions,nullptr,arguments,environ)==0);
    assert(posix_spawn_file_actions_destroy(&actions)==0);assert(close(fds[1])==0);
    std::vector<unsigned char> bytes;
    for(;;) {
        unsigned char chunk[1024];const ssize_t count=read(fds[0],chunk,sizeof(chunk));
        if(count==0)break;
        if(count<0 && errno==EINTR)continue;
        assert(count>0);bytes.insert(bytes.end(),chunk,chunk+count);
    }
    assert(close(fds[0])==0);
    ChildResult result;assert(waitpid(pid,&result.status,0)==pid);
    assert(bytes.size()%sizeof(uint32_t)==0);
    result.words.resize(bytes.size()/sizeof(uint32_t));
    if(!bytes.empty())memcpy(result.words.data(),bytes.data(),bytes.size());
    return result;
}
static bool fatal(int status) {
    return (WIFSIGNALED(status) && WTERMSIG(status)==SIGABRT) ||
        (WIFEXITED(status) && WEXITSTATUS(status)!=0 && WEXITSTATUS(status)!=77 && WEXITSTATUS(status)!=111);
}
static std::string originalThrow(const std::vector<uint32_t> &words,bool cpp) {
    bool active=false,previousSeen=false,previousTerminateSeen=false;std::string line,text;
    size_t lastReport=0,previousAt=0,previousTerminateAt=0;
    unsigned sequence=0,parts=0,received=0;
    for(size_t index=0;index<words.size();++index) {
        const uint32_t word=words[index];
        if(word==previousMarker) {assert(!active && !previousSeen);previousSeen=true;previousAt=index;continue;}
        if(word==previousTerminateMarker) {
            assert(!active && !previousTerminateSeen);previousTerminateSeen=true;previousTerminateAt=index;continue;
        }
        assert(!previousSeen && (word>>16)==0x4147);
        const uint32_t value=word&0xffff;
        if(value==0x6d80) {assert(!active);active=true;line.clear();}
        else if(value==0x6dff) {
            assert(active && line.size()>=16);active=false;
            char kind=0,truncated=0;unsigned gotSequence=0,part=0,total=0;
            assert(sscanf(line.c_str(),"%c%8x %2u/%2u%c",&kind,&gotSequence,&part,&total,&truncated)==5);
            assert(kind=='E' && truncated==' ' && part==received+1);
            if(!received) {sequence=gotSequence;parts=total;}
            assert(sequence==gotSequence && parts==total);++received;
            text+=line.substr(16);lastReport=index;
        } else {
            assert(active && value>0x6d00 && value<0x6d80);line+=char(value&0xff);
        }
    }
    assert(!active && received==parts && parts>0);
    if(cpp)assert(!previousSeen && previousTerminateSeen && lastReport<previousTerminateAt);
    else assert(previousSeen && lastReport<previousAt);
    return text;
}
static void check(const char *executable,bool cpp) {
    const ChildResult baseline=runChild(executable,false,cpp),instrumented=runChild(executable,true,cpp);
    assert(fatal(baseline.status) && fatal(instrumented.status));
    assert(WIFSIGNALED(baseline.status)==WIFSIGNALED(instrumented.status));
    if(WIFSIGNALED(baseline.status))assert(WTERMSIG(baseline.status)==WTERMSIG(instrumented.status));
    else assert(WEXITSTATUS(baseline.status)==WEXITSTATUS(instrumented.status));
    bool previousSeen=false,previousTerminateSeen=false;
    for(uint32_t word:baseline.words) {
        if(word==previousMarker) {assert(!previousSeen);previousSeen=true;}
        else {assert(word==previousTerminateMarker && !previousTerminateSeen);previousTerminateSeen=true;}
    }
    if(cpp)assert(!previousSeen && previousTerminateSeen);else assert(previousSeen);
    const std::string text=originalThrow(instrumented.words,cpp);
    std::string prefix;
    if(cpp) {
        assert(text.find("SHENGTHROW C++ ")==0 && text.find("bad_function_call")!=std::string::npos);
        const size_t stack=text.rfind(" |");assert(stack!=std::string::npos);prefix=text.substr(0,stack+2);
    } else {
        prefix="SHENGTHROW NabuDispatchException | global dispatch selector exception |";
        assert(text.find(prefix)==0);
    }
    std::istringstream frames(text.substr(prefix.size()));unsigned count=0;unsigned long long address=0;
    while(frames>>std::hex>>address) {assert(address!=0);++count;}
    assert(count>0 && count<=20);
    printf("PASS: real dispatch %s exception, original %s termination preserved, direct record and %u %s frames, previous %s handler preserved\n",
        cpp?"C++ bad_function_call":"Objective-C",WIFSIGNALED(instrumented.status)?"SIGABRT":"nonzero-exit",count,
        cpp?"terminate/throw-stack":"recorded-throw",cpp?"terminate":"NS");
}
int main(int argc,char **argv) {
    // Reference the real bootstrap for a complete strict compilation; the
    // child uses the fake service instead of opening a real GPU connection.
    auto start=&nabumetalproblem::start;(void)start;
    @autoreleasepool {
        if(argc==5 && !strcmp(argv[1],"--child"))child(atoi(argv[2]),!strcmp(argv[3],"instrumented"),!strcmp(argv[4],"cpp"));
        assert(argc==1);
        check(argv[0],false);check(argv[0],true);
    }
}
