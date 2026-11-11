// Host boundary substitutes; function bodies below are extracted from real XNU.
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <algorithm>
#include <array>
#include <deque>
#include <functional>
#include <mutex>
#include <thread>
#include <vector>
#define NABU_CA_IPC_HOST_TEST 1
#define MACH_FLIPC 0
#define IMPORTANCE_INHERITANCE 1
#define IMPORTANCE_TRACE 0
#ifndef __unused
#define __unused __attribute__((unused))
#endif
#define __assert_only
#define FALSE false
#define TRUE true
#define KDBG(...) ((void)0)
#define KERNEL_DEBUG_CONSTANT(...) ((void)0)
#define KERN_SUCCESS 0
#define THREAD_NULL nullptr
#define IKM_NULL nullptr
#define TURNSTILE_NULL nullptr
#define IP_VALID(p) ((p)!=nullptr)
#define MACH_MSG_TYPE_PORT_SEND_ONCE 18
#define MACH_MSGH_BITS_REMOTE(b) ((b)&255)
#define MACH_MSGH_BITS_COMPLEX 0x80000000u
#define MACH_MSGH_BITS_CIRCULAR 0x40000000u
#define IPC_KMSG_DESTROY_ALL 0
#define IPC_KMSG_DESTROY_SKIP_REMOTE 1
#define MACH_SEND_ALWAYS 0x10000u
#define MACH64_SEND_ALWAYS MACH_SEND_ALWAYS
#define MACH_SEND_TIMEOUT 0x10u
#define MACH64_SEND_TIMEOUT MACH_SEND_TIMEOUT
#define MACH64_SEND_MSG 1u
#define MACH64_SEND_KERNEL 0x20000u
#define MACH64_MSG_VECTOR (1ull<<33)
#define MACH64_MACH_MSG2 (1ull<<32)
#define MACH64_RCV_LINEAR_VECTOR (1ull<<34)
#define MACH64_RCV_STACK (1ull<<35)
#define MACH_RCV_LARGE 4u
#define MACH64_RCV_LARGE MACH_RCV_LARGE
#define MACH64_RCV_LARGE_IDENTITY 8u
#define TH_OPT_HONOR_QLIMIT 1u
#define MACH_MSG_DESC_MIN_SIZE 12
#define IPC_MQUEUE_FULL 1
#define IPC_MQUEUE_RECEIVE 2
#define TURNSTILE_SYNC_IPC 1
#define TURNSTILE_DELAYED_UPDATE 2
#define TURNSTILE_INTERLOCK_NOT_HELD 3
#define THREAD_ABORTSAFE 1
#define TIMEOUT_URGENCY_USER_NORMAL 0
#define TIMEOUT_NO_LEEWAY 0
#define THREAD_WAITING 1
#define THREAD_AWAKENED 2
#define THREAD_TIMED_OUT 3
#define THREAD_INTERRUPTED 4
#define THREAD_RESTART 5
#define THREAD_CONTINUE_NULL nullptr
#define WAITQ_KEEP_LOCKED 0
#define WAITQ_WAKEUP_DEFAULT 0
#define NSEC_PER_USEC 1000
#define kThreadWaitPortSend 1
using boolean_t=bool;
using mach_msg_return_t=uint32_t;
using mach_msg_option_t=uint32_t;
using mach_msg_option64_t=uint64_t;
using mach_msg_timeout_t=uint32_t;
using mach_msg_size_t=uint32_t;
using mach_msg_trailer_size_t=uint32_t;
using mach_port_name_t=uint32_t;
using mach_port_seqno_t=uint32_t;
using mach_msg_priority_t=uint32_t;
using mach_msg_qos_t=uint32_t;
using mach_vm_address_t=uint64_t;
using vm_map_t=void*;
using ipc_space_t=void*;
using ipc_object_t=void*;
constexpr mach_msg_return_t MACH_MSG_SUCCESS=0, MACH_SEND_TIMED_OUT=0x10000004,
 MACH_SEND_INTERRUPTED=0x10000007, MACH_SEND_INVALID_DEST=0x10000003,
 MACH_SEND_NO_BUFFER=0x1000000d, MACH_SEND_INVALID_OPTIONS=0x10000013,
 MACH_SEND_MSG_TOO_SMALL=0x10000008, MACH_SEND_TOO_LARGE=0x1000000e,
 MACH_SEND_INVALID_DATA=0x10000002, MACH_RCV_TOO_LARGE=0x10004004,
 MACH_RCV_INVALID_DATA=0x10004009, MACH_RCV_BODY_ERROR=0x1000400c,
 MACH_RCV_HEADER_ERROR=0x1000400b, MACH_RCV_IN_PROGRESS=0x10004010,
 MACH_PEEK_IN_PROGRESS=0x10004011, MACH_MSG_MASK=0x3e00;
struct port;struct ipc_kmsg;struct thread;
using ipc_kmsg_t=ipc_kmsg*;using ipc_port_t=port*;using thread_t=thread*;
struct mach_msg_header_t {uint32_t msgh_bits,msgh_size;port *msgh_remote_port,*msgh_local_port;uint32_t msgh_voucher_port;int32_t msgh_id;};
struct mach_msg_user_header_t {uint32_t msgh_bits,msgh_size,msgh_remote_port,msgh_local_port,msgh_reserved;int32_t msgh_id;};
struct mach_msg_user_base_t {mach_msg_user_header_t header;uint32_t descriptors;};
struct mach_msg_aux_header_t {uint32_t msgdh_size,msgdh_reserved;};
struct NDR_record_t {uint8_t bytes[8];};
static NDR_record_t NDR_record={{0,0,0,0,1,0,0,0}};
struct audit_token {uint32_t val[8];};
struct mach_msg_max_trailer_t {audit_token msgh_audit;};
struct ipc_kmsg {mach_msg_header_t header{};uint8_t inline_data[24]{};uint8_t *out_data=nullptr;
 mach_msg_max_trailer_t trailer{};uint32_t ikm_ppriority=0,ikm_qos_override=0;};
struct task {int pid;uint64_t messages_sent=0,messages_received=0;};using task_t=task*;
static task sender_task{204}, receiver_task{88};
struct thread {uint32_t options=0;task *owner=&sender_task;void *map=nullptr;
 uint32_t ith_state=MACH_RCV_IN_PROGRESS,ith_seqno=0,ith_receiver_name=0,ith_max_msize=256,ith_max_asize=0;
 uint32_t ith_msize=0,ith_asize=0;uint64_t ith_option=0,ith_msg_addr=0,ith_aux_addr=0;
 void *ith_object=nullptr,*ith_voucher=nullptr;uint32_t ith_voucher_name=0;ipc_kmsg *ith_kmsg=nullptr;};
static thread send_thread,receive_thread;
static thread_local thread *active_thread=&send_thread;
struct waitq {port *owner;};struct turnstile {waitq ts_waitq;};
struct mqueue {port *owner;uint32_t imq_msgcount=0,imq_seqno=50,imq_receiver_name=12;std::deque<ipc_kmsg*> imq_messages;};
using ipc_mqueue_t=mqueue*;
struct port {mqueue ip_messages{this};waitq ip_waitq{this};turnstile ts{{this}};
 bool active=true,valid=true,full=false,kernel_full=false,locked=false,ip_fullwaiters=false,kernel=false,klist=false;
 uint64_t ip_reply_context=0,ip_context=0;int ip_klist=0;std::deque<thread*> receivers;};
static port destination;
static ipc_space_t ipc_space_kernel=reinterpret_cast<void*>(1);
static bool enforce_strict_reply=false;
static int wait_result=THREAD_AWAKENED,blocked=0,knote_count=0,freed=0,importance_cleaned=0;
static uint32_t copyin_result=0,pseudo_result=0,copyout_result=0,put_result=0,get_result=0;
static bool copyout_reuse=false;static ipc_kmsg *reuse_message=nullptr;
static std::function<void(thread*)> resume_action;
static std::function<void()> unlock_action;
static uint32_t window_id=1;
struct Event {uint32_t window,event;uint64_t id,a,b,c;};
static std::vector<Event> events;static std::mutex event_mutex;
extern "C" uint32_t nabu_ca_ipc_trace_window(){return window_id;}
extern "C" void nabu_ca_ipc_trace_record(uint32_t window,uint32_t event,uint64_t id,uint64_t a,uint64_t b,uint64_t c){
 if(window!=window_id||!window)return;std::lock_guard<std::mutex> lock(event_mutex);events.push_back({window,event,id,a,b,c});}
static mach_msg_header_t *ikm_header(ipc_kmsg *k){return &k->header;}
static void *ikm_udata(ipc_kmsg *k,uint32_t,bool){return k->out_data?k->out_data:k->inline_data;}
static mach_msg_max_trailer_t *ipc_kmsg_get_trailer(ipc_kmsg *k,bool){return &k->trailer;}
#include "NabuCaIpcTrace.h"
static task *current_task(){return active_thread->owner;}static thread *current_thread(){return active_thread;}
static void *current_space(){return nullptr;}static void *current_map(){return nullptr;}
static int task_pid(task *t){return t?t->pid:-1;}static task *get_threadtask(thread *t){return t->owner;}
static port *ip_from_mq(mqueue *q){return q->owner;}
static void ip_mq_lock(port *p){assert(!p->locked);p->locked=true;}
static void ip_mq_unlock(port *p){assert(p->locked);p->locked=false;}
static void waitq_unlock(waitq *w){ip_mq_unlock(w->owner);if(unlock_action){auto f=std::move(unlock_action);unlock_action={};f();}}
static bool waitq_is_valid(waitq *w){return w->owner->valid;}
static bool imq_full(mqueue *q){return q->owner->full;}static bool imq_full_kernel(mqueue *q){return q->owner->kernel_full;}
static void ipc_kmsg_trace_send(ipc_kmsg*,uint32_t){}
static thread *waitq_wakeup64_identify_locked(waitq *w,int,int,int){
 assert(w->owner->locked);if(w->owner->receivers.empty())return nullptr;
 auto r=w->owner->receivers.front();w->owner->receivers.pop_front();return r;}
static bool ipc_kmsg_enqueue_qos(std::deque<ipc_kmsg*> *q,ipc_kmsg *k){bool first=q->empty();q->push_back(k);return first;}
static bool ip_in_a_space(port*){return true;}static void *ip_get_receiver(port*){return nullptr;}
static bool is_active(void*){return true;}static bool ipc_port_has_klist(port*p){return p->klist;}
#define KNOTE(...) (++knote_count)
static void ipc_mqueue_peek_on_thread_locked(mqueue*,uint64_t,thread*){}
static void waitq_resume_identified_thread(waitq*,thread *t,int,int){if(resume_action)resume_action(t);}
static uint32_t ipc_kmsg_copyout_size(ipc_kmsg *k,void*){return k->header.msgh_size-8;}
static uint32_t ipc_kmsg_aux_data_size(ipc_kmsg*){return 0;}
static bool ipc_kmsg_too_large(uint32_t m,uint32_t a,uint64_t,uint32_t mm,uint32_t ma,thread*){return m>mm||a>ma;}
static void ipc_mqueue_release_msgcount(mqueue *q){assert(q->imq_msgcount);--q->imq_msgcount;}
static void waitq_clear_promotion_locked(waitq*,thread*){}
static void ipc_kmsg_free(ipc_kmsg *k){++freed;delete[] k->out_data;delete k;}
static void ipc_kmsg_destroy(ipc_kmsg *k,int){ipc_kmsg_free(k);}
static void counter_inc(uint64_t *v){++*v;}
static void clock_interval_to_deadline(uint32_t t,uint32_t u,uint64_t *d){*d=uint64_t(t)*u;}
static void thread_set_pending_block_hint(thread*,int){}
static void *port_send_turnstile_address(port *p){return &p->ts;}
static turnstile *turnstile_prepare(uintptr_t p,void*,void*,int){return &reinterpret_cast<port*>(p)->ts;}
static void ipc_port_send_update_inheritor(port*,turnstile*,int){}
static int waitq_assert_wait64_leeway(waitq*,int,int,int,uint64_t,int){return THREAD_WAITING;}
static void turnstile_update_inheritor_complete(turnstile*,int){}
static int thread_block(void*){++blocked;if(wait_result==THREAD_AWAKENED)++destination.ip_messages.imq_msgcount;return wait_result;}
static void turnstile_complete(uintptr_t,void*,void*,int){}static void turnstile_cleanup(){}
static void panic(const char*){abort();}
static ipc_kmsg *ipc_kmsg_queue_first(std::deque<ipc_kmsg*> *q){return q->empty()?nullptr:q->front();}
static void ipc_kmsg_rmqueue(std::deque<ipc_kmsg*> *q,ipc_kmsg *k){auto it=std::find(q->begin(),q->end(),k);assert(it!=q->end());q->erase(it);}
static void ipc_voucher_send_preprocessing(ipc_kmsg*){}
static uint32_t ipc_kmsg_validate_reply_context_locked(uint32_t,port*,void*,uint32_t){return MACH_SEND_INVALID_OPTIONS;}
static bool ip_active(port*p){return p->active;}static void ip_release(port*){}
static void ipc_importance_clean(ipc_kmsg*){++importance_cleaned;}
static bool ip_in_space(port*p,void*){return p->kernel;}static void require_ip_active(port*p){assert(p->active);}
static ipc_kmsg *ipc_kobject_server(port*,ipc_kmsg*k,uint32_t){ipc_kmsg_free(k);return nullptr;}
#define TASK_NULL nullptr
static void ipc_kmsg_init_trailer(ipc_kmsg*k,task*t){k->trailer.msgh_audit.val[5]=t?t->pid:0;}
static void ikm_sign(ipc_kmsg*){}static bool ipc_importance_send(ipc_kmsg*,uint32_t){return false;}
static void ipc_special_reply_port_msg_sent(port*){}
static constexpr uint32_t ipc_kmsg_max_body_space=65536;
static ipc_kmsg *next_user_message;
static uint32_t ipc_kmsg_get_from_user(uint64_t,uint32_t,uint64_t,uint32_t,mach_msg_user_header_t,uint32_t,uint64_t,ipc_kmsg **k){
 if(get_result)return get_result;*k=next_user_message;return 0;}
static uint32_t ipc_kmsg_copyin_from_user(ipc_kmsg*k,void*,void*,uint32_t,uint64_t*,bool){
 if(!copyin_result)ipc_kmsg_init_trailer(k,current_task());return copyin_result;}
static uint32_t ipc_kmsg_copyout_pseudo(ipc_kmsg*,void*,void*){return pseudo_result;}
static uint32_t ipc_kmsg_put_to_user(ipc_kmsg*k,uint64_t,uint64_t,uint32_t,uint64_t,uint32_t,uint32_t,uint32_t*sz,uint32_t*aux){
 if(sz)*sz=k->header.msgh_size-8;if(aux)*aux=0;ipc_kmsg_free(k);return put_result;}
static void mach_msg_receive_results_complete(void*){}static void io_release(void*){}
static int copyout(const void*,uint64_t,uint32_t){return put_result?1:0;}
static uint32_t msg_receive_error(ipc_kmsg*k,uint64_t,uint64_t,uint32_t,uint64_t,uint32_t,uint32_t,void*,uint32_t *s,uint32_t *a){
 return ipc_kmsg_put_to_user(k,0,0,0,0,0,0,s,a);}
static void ipc_importance_receive(ipc_kmsg*,uint32_t){}static void ipc_voucher_receive_postprocessing(ipc_kmsg*,uint32_t){}
static uint32_t ipc_kmsg_copyout(ipc_kmsg*,void*,void*,uint32_t){return copyout_result;}
static uint32_t ipc_kmsg_trailer_size(uint32_t,thread*){return 8;}
static void ipc_importance_unreceive(ipc_kmsg*,uint32_t){}
static void ipc_kmsg_add_trailer(ipc_kmsg*,void*,uint64_t,thread*,uint32_t,bool,uint64_t){}
static void ipc_mqueue_post(mqueue*,ipc_kmsg*,uint32_t);
static uint32_t mach_msg_trap_send(uint64_t,uint64_t,uint64_t,uint32_t,uint32_t,bool,mach_msg_user_header_t,uint32_t,uint32_t,uint32_t);
uint32_t mach_msg_receive_results_kevent(uint32_t*,uint32_t*,uint32_t*,uint32_t*);
