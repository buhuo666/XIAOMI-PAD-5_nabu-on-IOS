/* Execute the extracted producer functions with a failing GPU allocator. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include <stdalign.h>
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define align(n,a) (((n)+(a)-1)&~((a)-1))
#define ALIGN_NPOT(n,a) align(n,a)
#define MAX2(a,b) ((a)>(b)?(a):(b))
#define TIMESTAMP_BUF_SIZE 0x1000
#define U_TRACE_TYPE_INDIRECTS 1
#define U_TRACE_NO_TIMESTAMP UINT64_MAX
#define VK_SUCCESS 0
#define VK_SYSTEM_ALLOCATION_SCOPE_DEVICE 3
#define TU_BO_ALLOC_INTERNAL_RESOURCE 8
#define container_of(p,t,m) ((t*)((char*)(p)-offsetof(t,m)))
struct util_dynarray { void *data; size_t size; size_t capacity; };
#define UTIL_DYNARRAY_INIT ((struct util_dynarray){0})
static void push(struct util_dynarray *a,const void *item,size_t bytes) {
 if(a->size+bytes>a->capacity) {a->capacity=(a->size+bytes)*2; a->data=realloc(a->data,a->capacity); assert(a->data);}
 memcpy((char*)a->data+a->size,item,bytes); a->size+=bytes;
}
#define util_dynarray_append(a,v) do { __typeof__(v) value=(v); push(a,&value,sizeof(value)); } while(0)
#define util_dynarray_num_elements(a,t) ((a)->size/sizeof(t))
#define util_dynarray_element(a,t,i) (((t*)(a)->data)+(i))
#define util_dynarray_last_ptr(a,t) util_dynarray_element(a,t,util_dynarray_num_elements(a,t)-1)
#define util_dynarray_foreach(a,t,p) for(t *p=(t*)(a)->data,*end_##p=p+util_dynarray_num_elements(a,t);p<end_##p;p++)
static void util_dynarray_fini(struct util_dynarray *a) {free(a->data);memset(a,0,sizeof(*a));}
struct allocation {void *p;struct allocation *next;};
typedef struct linear_ctx {struct allocation *head;} linear_ctx;
static linear_ctx *linear_context(void *unused) {(void)unused;return calloc(1,sizeof(linear_ctx));}
static void *linear_alloc_child(linear_ctx *l,size_t size) {struct allocation *a=malloc(sizeof(*a));a->p=calloc(1,size);assert(a->p);a->next=l->head;l->head=a;return a->p;}
static void linear_free_context(linear_ctx *l) {if(!l)return;while(l->head){struct allocation *a=l->head;l->head=a->next;free(a->p);free(a);}free(l);}
struct u_trace; struct u_trace_context;
struct u_trace_buffer_view {uint32_t buffer_index,offset;};
struct u_trace_buffer {void *buffer;uint32_t alloc_offset,size;};
enum u_trace_buffer_list_index {u_trace_buffer_list_timestamps,u_trace_buffer_list_indirect};
struct u_tracepoint {uint32_t payload_sz,flags;};
struct u_trace_address {void *bo;uint64_t offset;};
struct u_trace_event {const struct u_tracepoint *tp;struct u_trace_buffer_view timestamp,indirect;uint32_t payload_size;alignas(uint64_t) uint8_t payload[];};
struct u_trace_context {
 void *pctx;unsigned enabled_traces;uint64_t timestamp_size_bytes,max_indirect_size_bytes;
 void *(*create_buffer)(struct u_trace_context*,uint64_t);
 void (*delete_buffer)(struct u_trace_context*,void*);
 bool (*record_timestamp)(struct u_trace*,void*,void*,uint64_t,uint32_t);
 uint64_t (*read_timestamp)(struct u_trace_context*,void*,uint64_t,uint32_t,void*);
 void (*capture_data)(struct u_trace*,void*,void*,uint64_t,void*,uint64_t,uint32_t);
};
struct u_trace {struct u_trace_context *utctx;linear_ctx *linear_alloc;struct util_dynarray events;struct u_trace_buffer_view last_timestamp;bool allocation_failed;struct util_dynarray buffers[2];};
struct u_trace_iterator {struct u_trace *ut;uint32_t event_idx;};
static bool u_trace_iterator_equal(struct u_trace_iterator a,struct u_trace_iterator b) {return a.ut==b.ut&&a.event_idx==b.event_idx;}
typedef void (*u_trace_copy_buffer)(struct u_trace_context*,void*,void*,uint64_t,void*,uint64_t,uint64_t);
struct tu_suballocator {unsigned initialized;};
struct tu_suballoc_bo {uint64_t handle,iova;uint32_t size;};
struct tu_device {struct {int alloc;} vk;struct u_trace_context trace_context;struct tu_suballocator *trace_suballoc;int trace_mutex;};
typedef int VkResult;
static unsigned gpu_calls,fail_gpu_at,cpu_calls,fail_cpu_at,freed_cpu,live_cpu,writes,copies,waits,deleted,maps;
static bool submission_finished;
static void mtx_lock(int *m) {assert(!*m);*m=1;}
static void mtx_unlock(int *m) {assert(*m);*m=0;}
static void *vk_zalloc(void *a,size_t size,unsigned alignment,int scope) {(void)a;(void)alignment;(void)scope;cpu_calls++;if(cpu_calls==fail_cpu_at)return NULL;void *p=calloc(1,size);assert(p);live_cpu++;return p;}
static void vk_free(void *a,void *p) {(void)a;if(p){free(p);freed_cpu++;live_cpu--;}}
static void tu_bo_suballocator_init(struct tu_suballocator *s,struct tu_device *d,unsigned size,unsigned flags,const char *name) {(void)d;(void)size;(void)flags;assert(s);assert(!strcmp(name,"utrace"));s->initialized=1;}
static VkResult tu_suballoc_bo_alloc(struct tu_suballoc_bo *b,struct tu_suballocator *s,uint64_t size,unsigned alignment) {(void)alignment;assert(b&&s&&s->initialized);gpu_calls++;if(gpu_calls==fail_gpu_at)return -2;b->handle=gpu_calls;b->iova=0x100000+b->handle*0x80000;b->size=size;return VK_SUCCESS;}
struct tu_u_trace_submission_data {void *queue;uint64_t fence;};
static uint64_t mapped_ts[2];
static void tu_queue_wait_fence(void *queue,uint64_t fence,uint64_t timeout) {assert(queue&&fence==7&&timeout==1000000000);waits++;submission_finished=true;}
static void *tu_suballoc_bo_map(struct tu_suballoc_bo *bo) {assert(bo&&submission_finished);maps++;return mapped_ts;}
static uint64_t tu_device_ticks_to_ns(struct tu_device *d,uint64_t ts) {(void)d;return ts*2;}
/* ACTUAL_READ */
/* ACTUAL_CREATE */
/* ACTUAL_GET */
/* ACTUAL_HELPERS */
/* ACTUAL_LINEAR */
/* ACTUAL_INIT */
/* ACTUAL_FINI */
/* ACTUAL_ALLOC */
/* ACTUAL_CLONE */
/* ACTUAL_APPEND */
static void delete_buffer(struct u_trace_context *ctx,void *p) {assert(p);assert(submission_finished);deleted++;vk_free(NULL,p);(void)ctx;}
static bool record(struct u_trace *ut,void *cs,void *p,uint64_t off,uint32_t flags) {(void)ut;(void)cs;(void)flags;struct tu_suballoc_bo *b=p;assert(b&&off<b->size);writes++;return true;}
static uint64_t read_ts(struct u_trace_context *ctx,void *p,uint64_t off,uint32_t flags,void *data) {struct tu_u_trace_submission_data submission={.queue=ctx,.fence=7};return tu_trace_read_ts(ctx,p,off,flags,data?data:&submission);}
static void copy_buffer(struct u_trace_context *ctx,void *cs,void *from,uint64_t from_off,void *to,uint64_t to_off,uint64_t size) {(void)ctx;(void)cs;(void)from;(void)from_off;struct tu_suballoc_bo *b=to;volatile uint64_t iova=b->iova;assert(iova&&to_off+size<=b->size);copies++;}
static void capture(struct u_trace *ut,void *cs,void *to,uint64_t to_off,void *from,uint64_t from_off,uint32_t size) {copy_buffer(ut->utctx,cs,from,from_off,to,to_off,size);}
static void reset_counters(void) {assert(live_cpu==0);gpu_calls=fail_gpu_at=cpu_calls=fail_cpu_at=freed_cpu=live_cpu=writes=copies=waits=deleted=maps=0;submission_finished=true;}
static void setup(struct tu_device *d,struct u_trace *a,struct u_trace *b) {memset(d,0,sizeof(*d));d->trace_context=(struct u_trace_context){.timestamp_size_bytes=8,.max_indirect_size_bytes=16,.enabled_traces=U_TRACE_TYPE_INDIRECTS,.create_buffer=tu_trace_create_buffer,.delete_buffer=delete_buffer,.record_timestamp=record,.read_timestamp=read_ts,.capture_data=capture};u_trace_init(a,&d->trace_context);u_trace_init(b,&d->trace_context);}
static void finish(struct tu_device *d,struct u_trace *a,struct u_trace *b) {submission_finished=true;u_trace_fini(a);u_trace_fini(b);vk_free(NULL,d->trace_suballoc);assert(live_cpu==0);}
static void *append(struct u_trace *ut,bool indirect) {static const struct u_tracepoint tp={8,0};struct u_trace_address addr={NULL,0x1000};uint8_t sz=8;void *payload=u_trace_appendv(ut,NULL,&tp,0,indirect?1:0,&addr,&sz);assert(payload);memset(payload,0x44,8);return payload;}
static void clone(struct u_trace *a,struct u_trace *b) {u_trace_clone_append((struct u_trace_iterator){a,0},(struct u_trace_iterator){a,util_dynarray_num_elements(&a->events,struct u_trace_event*)},b,NULL,copy_buffer);}
int main(int argc,char **argv) {
 struct tu_device d;struct u_trace a,b;reset_counters();setup(&d,&a,&b);
 if(argc>1&&!strcmp(argv[1],"buggy")) {append(&a,false);fail_gpu_at=gpu_calls+1;clone(&a,&b);fprintf(stderr,"BUG NOT REPRODUCED\\n");return 2;}
 struct tu_suballoc_bo sample={0};struct tu_u_trace_submission_data submission={.queue=&d,.fence=7};
 if(argc==1) {
  submission_finished=false;assert(tu_trace_read_ts(&d.trace_context,NULL,0,0,&submission)==U_TRACE_NO_TIMESTAMP);assert(waits==1&&maps==0&&submission_finished);
  mapped_ts[0]=42;assert(tu_trace_read_ts(&d.trace_context,&sample,0,0,&submission)==84);assert(waits==2&&maps==1);
  mapped_ts[1]=U_TRACE_NO_TIMESTAMP;assert(tu_trace_read_ts(&d.trace_context,&sample,8,0,&submission)==U_TRACE_NO_TIMESTAMP);assert(waits==2&&maps==2);
  waits=maps=0;
 }
 append(&a,true);clone(&a,&b);assert(writes==1&&copies==3);assert(!a.allocation_failed&&!b.allocation_failed);assert(util_dynarray_num_elements(&b.events,struct u_trace_event*)==1);finish(&d,&a,&b);
 for(unsigned fail=1;fail<=2;fail++) {reset_counters();setup(&d,&a,&b);fail_gpu_at=fail;append(&a,fail==2);assert(a.allocation_failed&&a.events.size==0);assert(a.buffers[1].size==0);unsigned expected=fail==2?1:0;assert(writes==expected);submission_finished=false;unsigned before=waits;assert(u_trace_discard_failed_flush(&a,NULL));assert(waits-before==1);assert(submission_finished&&maps==0);unsigned prev_calls=gpu_calls;append(&a,true);assert(gpu_calls==prev_calls);finish(&d,&a,&b);}
 for(unsigned fail=1;fail<=2;fail++) {reset_counters();setup(&d,&a,&b);append(&a,true);fail_gpu_at=gpu_calls+fail;unsigned oldcopies=copies;clone(&a,&b);assert(b.allocation_failed&&!b.events.size);assert(copies-oldcopies==fail-1);submission_finished=false;unsigned before=waits;assert(u_trace_discard_failed_flush(&b,NULL));assert(waits-before==1);assert(submission_finished&&maps==0);finish(&d,&a,&b);}
 for(unsigned fail=1;fail<=2;fail++) {reset_counters();setup(&d,&a,&b);fail_cpu_at=fail;append(&a,false);assert(a.allocation_failed&&!a.events.size&&!d.trace_mutex);finish(&d,&a,&b);}
 reset_counters();setup(&d,&a,&b);append(&a,false);unsigned before=waits;assert(!u_trace_discard_failed_flush(&a,NULL));assert(waits==before);a.allocation_failed=true;clone(&a,&b);assert(b.allocation_failed&&!b.events.size&&!b.buffers[0].size);submission_finished=false;before=waits;assert(u_trace_discard_failed_flush(&b,NULL));assert(waits-before==1&&submission_finished&&maps==0);finish(&d,&a,&b);
 reset_counters();setup(&d,&a,&b);fail_gpu_at=1;append(&a,false);assert(a.allocation_failed);u_trace_fini(&a);u_trace_init(&a,&d.trace_context);fail_gpu_at=0;append(&a,false);assert(!a.allocation_failed&&a.events.size);finish(&d,&a,&b);
 puts("PASS: healthy capture; timestamp/indirect/clone/CPU allocation failures; payload safety; actual Turnip NULL wait without map; healthy read and sentinel; submission wait before cleanup; reset recovery; no leaks");
 return 0;
}
