#include <atomic>
#include <cassert>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <thread>
#include <vector>
#define KERNEL 1
extern "C" {
#include <sys/hakios.sta.h>
}
#define HAKIOS_NET_FRAME_MAX 1514
struct Packet {std::vector<uint8_t> bytes; bool bad=false;};
using mbuf_t=Packet *;
struct hakios_net_link {const char *name;unsigned unit;uint8_t address[6];bool wireless,up;
    bool (*transmit)(mbuf_t,size_t);unsigned (*poll)();};
struct IOLock {std::mutex mutex;std::condition_variable event;};
static constexpr int THREAD_UNINT=0;
static std::vector<IOLock *> all_locks;
static std::atomic<bool> stopping{false};
struct Stop {};
static IOLock *IOLockAlloc(){auto *p=new IOLock;all_locks.push_back(p);return p;}
static void IOLockLock(IOLock *p){p->mutex.lock();}
static void IOLockUnlock(IOLock *p){p->mutex.unlock();}
static void IOLockSleep(IOLock *p,void *,int){
    std::unique_lock<std::mutex> lock(p->mutex,std::adopt_lock);
    if(stopping)throw Stop{};
    p->event.wait(lock);if(stopping)throw Stop{};lock.release();
}
static void IOLockWakeup(IOLock *p,void *,bool){p->event.notify_all();}
static void *IOMalloc(size_t n){return malloc(n);}
static int mbuf_copydata(mbuf_t p,size_t at,size_t n,void *out){
    if(!p||p->bad||at+n>p->bytes.size())return EINVAL;
    memcpy(out,p->bytes.data()+at,n);return 0;
}
static std::thread tx_thread;
extern "C" int lx_os_thread(const char *,void (*fn)(void *),void *ctx){
    tx_thread=std::thread([=]{try{fn(ctx);}catch(Stop &){}});return 0;
}
static bool selected=false;static unsigned attaches;
static uint8_t address[6]={2,7,8,9,10,11};
struct OSData {unsigned getLength(){return 6;}const void *getBytesNoCopy(){return address;}};
struct IORegistryEntry {
    static IORegistryEntry *fromPath(const char *p,const char *){
        assert(!strcmp(p,"/wlan"));static IORegistryEntry node;return selected?&node:nullptr;
    }
    OSData *getProperty(const char *p){assert(!strcmp(p,"local-mac-address"));static OSData mac;return &mac;}
    void release(){}
};
#define OSDynamicCast(type,value) (value)
static const char *gIODTPlane="IODeviceTree";
static void nabu_wireless_log(const char *,...){}
static const hakios_sta_ops *attached_ops;
static bool live=true;
static std::atomic<bool> bsd_up{false},allow_commit{true},hold_tx{false},entered_tx{false};
static std::atomic<unsigned> power_calls{0},leave_calls{0},rx_calls{0},invalidations{0};
static int scan_errno,join_errno,send_errno;
static bool lose_in_join=false,fatal_in_join=false;
static std::vector<uint8_t> last_sent;
static std::mutex native_publish;
static hakios_sta_phase raw_phase=HAKIOS_STA_IDLE;
extern "C" int nabu_ath10k_os_radio_powered(){return live;}
void hakios_sta_attach(const hakios_sta_ops *ops){attached_ops=ops;}
extern "C" void hakios_sta_invalidate(int){std::lock_guard<std::mutex> l(native_publish);++invalidations;allow_commit=false;attached_ops=nullptr;}
bool hakios_sta_present(){return attached_ops!=nullptr;}
bool hakios_sta_powered(){return attached_ops&&raw_phase!=HAKIOS_STA_OFF;}
void hakios_sta_lost(int){std::lock_guard<std::mutex> l(native_publish);allow_commit=false;}
extern "C" bool hakios_sta_join_commit(bool (*fn)(void *),void *ctx){
    std::lock_guard<std::mutex> l(native_publish);return allow_commit&&fn(ctx);
}
extern "C" void hakios_net_link_state(bool up){bsd_up=up;}
extern "C" void hakios_net_input(const uint8_t *,size_t){++rx_calls;}
extern "C" bool hakios_net_attach(const hakios_net_link *link){
    ++attaches;assert(link->wireless&&!link->up&&link->unit==0&&!link->poll);
    assert(!memcmp(link->address,address,6));assert(!link->transmit(nullptr,0));return true;
}
template<class F> static void wait_for(F condition){
    auto until=std::chrono::steady_clock::now()+std::chrono::seconds(5);
    while(!condition()){assert(std::chrono::steady_clock::now()<until);std::this_thread::yield();}
}
