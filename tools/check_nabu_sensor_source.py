#!/usr/bin/env python3
"""Exercise actual sensor IOUserClient methods and XNU queue code on the host.

IOKit allocation, registration, ports and maps are host substitutes. The source
methods and IOSharedDataQueue enqueue/dequeue bodies are extracted unchanged.
This checks the kernel/userland contract; it does not run the iOS HID server.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

from check_darwinboot_8796 import host_command, host_path
from check_nabu_pending_als import block

ROOT = Path(__file__).resolve().parents[1]
PRELUDE = r'''
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <mutex>
#include <string>
#include <vector>
#include "NabuSensorHid.h"
using UInt8=uint8_t;using UInt32=uint32_t;using Boolean=bool;
using IOReturn=int32_t;using IOOptionBits=uint32_t;using io_user_reference_t=uint64_t;using task_t=void *;
constexpr bool TRUE=true;
constexpr IOReturn kIOReturnSuccess=0,kIOReturnNotReady=-1,kIOReturnUnsupported=-2,kIOReturnNoMemory=-3;
constexpr IOReturn kIOReturnNoResources=-4,kIOReturnBusy=-5,kIOReturnNotOpen=-6,kIOReturnBadArgument=-7;
constexpr IOReturn kIOReturnAborted=-8,kIOReturnNotFound=-9;
constexpr const char *kIOClientPrivilegeAdministrator="admin";
constexpr const char *kIOUserClientDefaultLockingKey="locking";
constexpr const char *kIOUserClientDefaultLockingSetPropertiesKey="properties";
constexpr const char *kIOUserClientDefaultLockingSingleThreadExternalMethodKey="single";
constexpr bool kOSBooleanTrue=true,kOSBooleanFalse=false;
#define OSDeclareDefaultStructors(x)
#define OSDefineMetaClassAndStructors(x,y)
#define APPLE_KEXT_OVERRIDE
#define OSDynamicCast(t,p) dynamic_cast<t *>(p)
#define OSSafeReleaseNULL(p) do{if(p){(p)->release();(p)=nullptr;}}while(0)
#define __nochk_memcpy memcpy
struct IOLock{std::mutex mutex;};
IOLock *IOLockAlloc(){return new IOLock;}
void IOLockFree(IOLock *lock){delete lock;}
void IOLockLock(IOLock *lock){lock->mutex.lock();}
void IOLockUnlock(IOLock *lock){lock->mutex.unlock();}
void IOLog(const char *,...){}
struct kmod_info_t{const char *name;};
extern "C" {kmod_info_t g_kernel_kmod_info{"sensor-host"};}
struct OSMetaClass{static void *preModLoad(const char *){return reinterpret_cast<void *>(1);}static IOReturn postModLoad(void *){return 0;}};
struct Port{unsigned released=0,notifications=0;};
using mach_port_t=Port *;
constexpr mach_port_t MACH_PORT_NULL=nullptr;
struct OSObject{
    unsigned references=1;
    virtual ~OSObject()=default;
    virtual void free(){}
    void retain(){++references;}
    void release(){assert(references);if(!--references){free();delete this;}}
};
struct OSData:OSObject{static OSData *withBytes(const void *,size_t){return new OSData;}};
struct OSNumber:OSObject{static OSNumber *withNumber(uint64_t,unsigned){return new OSNumber;}};
struct OSDictionary:OSObject{static OSDictionary *withCapacity(unsigned){return new OSDictionary;}bool setObject(const char *,OSObject *){return true;}};
struct OSArray:OSObject{static OSArray *withCapacity(unsigned){return new OSArray;}bool setObject(OSObject *){return true;}};
struct IOService:OSObject{
    std::map<std::string,uint64_t> numbers;std::string name;unsigned registered=0;
    bool init(){return true;}bool attach(IOService *){return true;}void detach(IOService *){}
    virtual bool start(IOService *){return true;}
    bool setProperty(const char *key,uint64_t value,unsigned){numbers[key]=value;return true;}
    bool setProperty(const char *,const char *){return true;}bool setProperty(const char *,bool){return true;}
    bool setProperty(const char *,OSObject *){return true;}
    void setName(const char *value){name=value;}void registerService(){++registered;}
    static IOService *getPlatform(){static IOService platform;return &platform;}
};
struct IOMemoryDescriptor:OSObject{void *address=nullptr;size_t length=0;};
struct IOMemoryMap:OSObject{IOMemoryDescriptor *descriptor=nullptr;bool unmapped=false;
    IOReturn unmap(){assert(!unmapped);unmapped=true;return 0;}
    void free()override{assert(unmapped);}
};
struct IOExternalMethodArguments{const void *structureInput=nullptr;size_t structureInputSize=0;void *structureOutput=nullptr;size_t structureOutputSize=0;};
struct IOExternalMethodDispatch{IOReturn (*function)(OSObject *,void *,IOExternalMethodArguments *);unsigned scalarIn,structureIn,scalarOut,structureOut;};
struct IOUserClient:IOService{
    std::vector<IOMemoryMap *> maps;bool terminated=false;
    static IOReturn clientHasPrivilege(task_t,const char *){return 0;}
    bool initWithTask(task_t,void *,UInt32,OSDictionary *){return true;}
    void terminate(){terminated=true;}
    IOMemoryMap *removeMappingForDescriptor(IOMemoryDescriptor *d){
        for(auto it=maps.begin();it!=maps.end();++it)if((*it)->descriptor==d){auto *map=*it;maps.erase(it);return map;}
        return nullptr;
    }
    static void releaseNotificationPort(Port *port){assert(port&&!port->released);++port->released;}
    IOReturn externalMethod(uint32_t,IOExternalMethodArguments *args,IOExternalMethodDispatch *method,OSObject *target,void *ref){
        if(args->structureInputSize!=method->structureIn||args->structureOutputSize!=method->structureOut)return kIOReturnBadArgument;
        return method->function(target,ref,args);
    }
};
struct IODataQueueEntry{UInt32 size;UInt8 data[4];};
struct IODataQueueMemory{UInt32 queueSize;volatile UInt32 head,tail;IODataQueueEntry queue[1];};
constexpr size_t DATA_QUEUE_ENTRY_HEADER_SIZE=4,DATA_QUEUE_MEMORY_HEADER_SIZE=12;
struct IOSharedDataQueue:OSObject{
    IODataQueueMemory *dataQueue=nullptr;UInt32 capacity=0;Port *port=nullptr;
    static IOSharedDataQueue *withCapacity(UInt32 size){
        auto *q=new IOSharedDataQueue;q->capacity=size;
        q->dataQueue=static_cast<IODataQueueMemory *>(calloc(1,size+DATA_QUEUE_MEMORY_HEADER_SIZE+64));
        assert(q->dataQueue);q->dataQueue->queueSize=size;return q;
    }
    IOMemoryDescriptor *getMemoryDescriptor(){auto *d=new IOMemoryDescriptor;d->address=dataQueue;d->length=capacity+DATA_QUEUE_MEMORY_HEADER_SIZE+64;return d;}
    UInt32 getQueueSize(){return capacity;}
    void setNotificationPort(Port *value){port=value;}
    void sendDataAvailableNotification(){if(port){assert(!port->released);++port->notifications;}}
    Boolean enqueue(void *,UInt32);
    Boolean dequeue(void *,UInt32 *);
    void free()override{std::free(dataQueue);}
};
'''

TEST = r'''
extern "C" void nabu_sensor_hid_static_init(){}
unsigned failures=0,checks=0,handlerCalls=0;
void check(bool value,const char *name){++checks;if(!value){++failures;printf("FAIL: %s\n",name);}}
NabuSensorDescription description(unsigned kind,uint64_t suid){
    NabuSensorDescription d{};d.abi_version=1;d.kind=kind;d.physical_suid[0]=suid;d.physical_suid[1]=suid+1;
    strcpy(d.product,"real-sensor-fixture");strcpy(d.manufacturer,"fixture-vendor");return d;
}
NabuSensorRecord sample(unsigned kind,uint64_t stamp){
    NabuSensorRecord r{};r.kind=kind;r.value_count=kind==3?1:3;r.accuracy=3;r.ssc_ticks=stamp*19;r.mach_timestamp=stamp;
    r.value_bits[0]=0x3f800000;r.value_bits[1]=0x40000000;r.value_bits[2]=0x40400000;return r;
}
IOReturn controlHandlerResult=0;
bool invalidateInHandler=false;
int32_t handler(void *,uint32_t kind,uint32_t control,uint64_t microseconds){
    ++handlerCalls;check(kind==0&&control==0&&microseconds==20000,"exact control payload reaches backend");
    if(invalidateInHandler)nabu_sensor_hid_invalidate(kind,kIOReturnAborted);
    return controlHandlerResult;
}
IOReturn control(NabuSensorUserClient *client){
    NabuSensorControlRequest request{0,0,20000};IOExternalMethodArguments args;
    args.structureInput=&request;args.structureInputSize=sizeof request;
    return client->externalMethod(NabuSensorSourceSetControl,&args,nullptr,nullptr,nullptr);
}
NabuSensorStatus status(NabuSensorUserClient *client){
    NabuSensorStatus value{};IOExternalMethodArguments args;
    args.structureOutput=&value;args.structureOutputSize=sizeof value;
    check(client->externalMethod(NabuSensorSourceGetStatus,&args,nullptr,nullptr,nullptr)==0,"status external-method ABI");
    return value;
}
struct Client {
    NabuSensorUserClient *client=nullptr;IOMemoryDescriptor *memory=nullptr;IOSharedDataQueue reader;Port port;
    void open(unsigned kind){
        IOUserClient *base=nullptr;
        check(sources[kind]->newUserClient(nullptr,nullptr,NabuSensorSourceOpenType,nullptr,&base)==0,"source opens via real override");
        client=static_cast<NabuSensorUserClient *>(base);assert(client);
        IOOptionBits options=99;check(client->clientMemoryForType(0,&options,&memory)==0&&!options,"map queue memory type 0");
        IOMemoryDescriptor *same=nullptr;check(client->clientMemoryForType(0,&options,&same)==0&&same==memory,"stable map/unmap descriptor identity");same->release();
        reader.dataQueue=static_cast<IODataQueueMemory *>(memory->address);reader.capacity=reader.dataQueue->queueSize;
        check(memory->length>=DATA_QUEUE_MEMORY_HEADER_SIZE+reader.capacity,"daemon mapping-size contract");
        check(client->registerNotificationPort(&port,0,0)==0,"notification type 0 accepted");
    }
    bool read(NabuSensorRecord &record){UInt32 bytes=sizeof record;return reader.dequeue(&record,&bytes)&&bytes==sizeof record;}
    void close(){
        if(!client)return;
        auto *map=new IOMemoryMap;map->descriptor=memory;client->maps.push_back(map);
        check(client->clientClose()==0&&client->terminated&&client->maps.empty(),"close unmaps held queue and terminates client");
        check(port.released==1,"close releases owned notification send right once");
        memory->release();memory=nullptr;client->release();client=nullptr;reader.dataQueue=nullptr;
    }
    ~Client(){close();}
};
int main(){
    static_assert(offsetof(NabuSensorStatus,latest)==104&&offsetof(NabuSensorStatus,generation)==212,"status offsets");
    static_assert(offsetof(NabuSensorRecord,mach_timestamp)==32&&offsetof(NabuSensorRecord,value_bits)==40,"record offsets");
    check(nabu_sensor_hid_initialize()==0,"class initialization");
    for(auto *s:sources)check(s==nullptr,"initialization publishes no source without a real sample");
    nabu_sensor_hid_set_control_handler(handler,nullptr);
    auto d=description(0,11);auto r=sample(0,1000);
    check(nabu_sensor_hid_submit(&d,&r)==0,"first real sample creates source");
    check(sources[0]->registered==1&&sources[0]->status.generation==1,"registration follows first sample");
    {Client first;first.open(0);NabuSensorRecord snapshot{};
        check(first.port.notifications==0&&first.read(snapshot),"snapshot is drainable before any port notification");
        check(snapshot.flags==NabuSensorRecordCurrentSnapshot&&snapshot.mach_timestamp==1000&&snapshot.sequence==1,"snapshot preserves original time and sequence");
        check(!memcmp(snapshot.value_bits,r.value_bits,12),"raw sample words preserved");
        for(unsigned i=0;i<4000;++i){
            r=sample(0,1001+i);check(nabu_sensor_hid_submit(&d,&r)==0,"stream sample accepted");
            NabuSensorRecord actual{};check(first.read(actual)&&actual.sequence==i+2&&actual.mach_timestamp==r.mach_timestamp,"queue wraps with exact ABI records");
        }
        check(first.port.notifications==4000,"empty-to-nonempty transitions notify live port");
        auto s=status(first.client);check(s.accepted_samples==4001&&s.active==1,"daemon status sees live source");
        check(control(first.client)==0&&status(first.client).report_interval_us==20000,"accepted backend control updates status");
        controlHandlerResult=kIOReturnUnsupported;
        check(control(first.client)==kIOReturnUnsupported&&status(first.client).report_interval_us==20000,"rejected backend control preserves status");
        controlHandlerResult=0;
        invalidateInHandler=true;
        check(control(first.client)==kIOReturnAborted&&!status(first.client).active,"invalidation during control cannot report false success");
        invalidateInHandler=false;
    }
    r=sample(0,6000);check(nabu_sensor_hid_submit(&d,&r)==0,"same source can resume with a new generation");
    {Client old;old.open(0);NabuSensorRecord record{};check(old.read(record),"resumed source provides snapshot");
        for(unsigned i=0;i<1100;++i){r=sample(0,6001+i);check(nabu_sensor_hid_submit(&d,&r)==0,"full queue still accepts producer samples");}
        const auto dropped=sources[0]->status.dropped_records;
        check(dropped>0,"exercise actual full IOSharedDataQueue");
        const auto generation=status(old.client).generation;
        nabu_sensor_hid_invalidate(0,kIOReturnAborted);
        check(sources[0]->status.dropped_records==dropped+1,"full queue drops invalidation but status becomes inactive");
        unsigned invalidations=0;
        while(old.read(record))invalidations+=record.record_type==NabuSensorRecordInvalidated;
        check(!invalidations,"no invalidation record available to the old consumer");
        d=description(0,31);r=sample(0,9000);check(nabu_sensor_hid_submit(&d,&r)==0,"new generation publishes real new source sample");
        check(status(old.client).generation==generation+1,"status polling exposes generation change");
        check(!old.read(record),"old userclient must not receive next-generation sample under old identity");
        const unsigned calls=handlerCalls;
        check(control(old.client)==kIOReturnNotReady&&handlerCalls==calls,"old userclient must not control next-generation source");
        old.close();
        Client current;current.open(0);check(current.read(record)&&record.mach_timestamp==9000,"fresh connection receives preserved new-generation sample");
        check(status(current.client).description.physical_suid[0]==31,"fresh connection sees current physical identity");
        check(control(current.client)==0,"fresh connection can control resumed source");
    }
    {auto light=description(3,51);auto value=sample(3,10000);check(nabu_sensor_hid_submit(&light,&value)==0,"on-change ALS first sample");
        Client als;als.open(3);NabuSensorRecord record{};check(als.read(record)&&record.value_count==1,"ALS snapshot reaches a late-opening consumer once");
        check(!als.read(record)&&status(als.client).active,"unchanged ALS is not periodically fabricated or invalidated");
    }
    nabu_sensor_hid_set_control_handler(nullptr,nullptr);
    for(auto *&s:sources){if(s){assert(!s->client);s->release();s=nullptr;}}
    IOLockFree(sourceLock);sourceLock=nullptr;
    printf("CHECKS %u FAILURES %u\n",checks,failures);return failures?1:0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=ROOT / 'patches/nabu-sensors/NabuSensorHid.cpp')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = args.source.read_text()
    # All transport production definitions are retained; only includes move to
    # the fixture's platform substitutes. Header ABI remains the real header.
    source = re.sub(r'^#include[^\n]*\n', '', source, flags=re.M)
    queue = (ROOT / 'src/xnu-8796/iokit/Kernel/IOSharedDataQueue.cpp').read_text()
    queue_methods = '\n'.join(block(queue, marker) for marker in (
        'Boolean\nIOSharedDataQueue::enqueue(', 'Boolean\nIOSharedDataQueue::dequeue('))
    generated = args.output / 'sensor-source-host.cpp'
    generated.write_text(PRELUDE + queue_methods + source + TEST, newline='\n')
    binary = args.output / 'sensor-source-host'
    command = host_command(['clang++-18', '-std=c++17', '-Wall', '-Wextra', '-Werror',
        '-Wno-misleading-indentation', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-g',
        '-I' + host_path(ROOT / 'patches/nabu-sensors'), host_path(generated), '-o', host_path(binary)])
    result = subprocess.run(command, capture_output=True)
    (args.output / 'compile.log').write_bytes(result.stdout + result.stderr)
    result.check_returncode()
    result = subprocess.run(host_command([host_path(binary)]), capture_output=True, timeout=30)
    (args.output / 'run.log').write_bytes(result.stdout + result.stderr)
    stdout = result.stdout.decode(errors='replace')
    counts = re.search(r'CHECKS (\d+) FAILURES (\d+)', stdout)
    report = {'passed': result.returncode == 0 and bool(counts), 'device_execution': False,
              'source': str(args.source), 'actual_xnu_queue_methods': True,
              'checks': int(counts[1]) if counts else 0, 'failures': int(counts[2]) if counts else None,
              'sanitizers': ['address', 'undefined'], 'command': command, 'stdout': stdout,
              'limitations': 'Host IOKit allocation/registry/map/port substitutes; native HID authorization and event-server consumption still require device execution'}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(stdout)
    result.check_returncode()


if __name__ == '__main__':
    main()
