/* MIT. Host integration fixture. Generated includes contain the actual Mesa
 * cache routines and the actual Turnip functions, unchanged. Hardware shader
 * compilation, hash-table storage and optional disk I/O are fixture boundaries. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <pthread.h>
#include <sched.h>
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define p_atomic_read(p) __atomic_load_n(p,__ATOMIC_SEQ_CST)
#define p_atomic_set(p,v) __atomic_store_n(p,v,__ATOMIC_SEQ_CST)
#define p_atomic_inc(p) ((void)__atomic_add_fetch(p,1,__ATOMIC_SEQ_CST))
#define p_atomic_dec_zero(p) (__atomic_sub_fetch(p,1,__ATOMIC_SEQ_CST)==0)
#define VK_PIPELINE_CACHE_CREATE_EXTERNALLY_SYNCHRONIZED_BIT 1
#define vk_pipeline_cache_log(...) ((void)0)
#define simple_mtx_lock pthread_mutex_lock
#define simple_mtx_unlock pthread_mutex_unlock
#define CHECK(x) do {if(!(x)){fprintf(stderr,"%s:%d: %s\n",__FILE__,__LINE__,#x);abort();}} while(0)
typedef unsigned char cache_key[20];
struct vk_pipeline_cache;
struct vk_pipeline_cache_object;
struct disk_cache {};
struct blob {void *data;size_t size;bool out_of_memory;};
struct vk_physical_device {struct disk_cache *disk_cache;};
struct vk_device {struct vk_physical_device *physical;};
struct vk_pipeline_cache_object_ops {
 bool (*serialize)(struct vk_pipeline_cache_object *,struct blob *);
 void (*destroy)(struct vk_device *,struct vk_pipeline_cache_object *);
};
struct vk_pipeline_cache_object {
 const struct vk_pipeline_cache_object_ops *ops;
 struct vk_pipeline_cache *weak_owner;
 uint32_t ref_cnt,data_size;const void *key_data;uint32_t key_size;
};
struct vk_raw_data_cache_object {struct vk_pipeline_cache_object base;void *data;size_t data_size;};
struct set_entry {const void *key;struct set_entry *next;};
struct set {struct set_entry *head;};
struct vk_pipeline_cache {
 struct {struct vk_device *device;} base;
 uint32_t flags;bool weak_ref,skip_disk_cache;struct disk_cache *disk_cache;
 pthread_mutex_t lock;struct set *object_cache;
};
struct tu_device {struct vk_device vk;struct vk_pipeline_cache *mem_cache;};
struct tu_shader {struct vk_pipeline_cache_object base;uint64_t key[2],value;};
static uint64_t made,freed,live,peak;
static bool object_keys_equal(const void *,const void *);
static void vk_pipeline_cache_object_unref(struct vk_device *,struct vk_pipeline_cache_object *);
static uint32_t _mesa_hash_data(const void *p,size_t n) {
 const unsigned char *b=p;uint32_t h=2166136261u;while(n--)h=(h^*b++)*16777619u;return h;
}
static struct set_entry *_mesa_set_search_pre_hashed(struct set *s,uint32_t h,const void *key) {
 (void)h;for(struct set_entry *e=s->head;e;e=e->next)if(object_keys_equal(e->key,key))return e;return NULL;
}
static struct set_entry *_mesa_set_search_or_add_pre_hashed(struct set *s,uint32_t h,const void *key,bool *found) {
 struct set_entry *e=_mesa_set_search_pre_hashed(s,h,key);*found=e!=NULL;
 if(e)return e;e=calloc(1,sizeof *e);CHECK(e);e->key=key;e->next=s->head;s->head=e;return e;
}
static void _mesa_set_remove(struct set *s,struct set_entry *e) {
 struct set_entry **at=&s->head;while(*at!=e)at=&(*at)->next;*at=e->next;free(e);
}
static void disk_cache_compute_key(struct disk_cache *c,const void *p,size_t n,cache_key k){(void)c;(void)p;(void)n;(void)k;CHECK(false);}
static void *disk_cache_get(struct disk_cache *c,cache_key k,size_t *n){(void)c;(void)k;(void)n;CHECK(false);return NULL;}
static void disk_cache_put(struct disk_cache *c,cache_key k,const void *p,size_t n,void *meta){(void)c;(void)k;(void)p;(void)n;(void)meta;CHECK(false);}
static void blob_init(struct blob *b){memset(b,0,sizeof *b);}
static void blob_finish(struct blob *b){(void)b;}
static void destroy_shader(struct vk_device *d,struct vk_pipeline_cache_object *o) {
 (void)d;CHECK(o->ref_cnt==0);p_atomic_inc(&freed);__atomic_sub_fetch(&live,1,__ATOMIC_SEQ_CST);free(container_of(o,struct tu_shader,base));
}
static const struct vk_pipeline_cache_object_ops tu_shader_ops={NULL,destroy_shader};
static const struct vk_pipeline_cache_object_ops vk_raw_data_cache_object_ops={NULL,NULL};
static struct vk_pipeline_cache_object *vk_pipeline_cache_object_deserialize(
 struct vk_pipeline_cache *c,const void *k,uint32_t n,const void *data,size_t bytes,
 const struct vk_pipeline_cache_object_ops *ops){(void)c;(void)k;(void)n;(void)data;(void)bytes;(void)ops;CHECK(false);return NULL;}
#include "mesa_cache_actual.inc"
#include "turnip_shared_actual.inc"
static void init_cache(struct vk_pipeline_cache *c,struct tu_device *d,bool enabled,bool external) {
 memset(c,0,sizeof *c);c->base.device=&d->vk;c->skip_disk_cache=true;
 c->flags=external?VK_PIPELINE_CACHE_CREATE_EXTERNALLY_SYNCHRONIZED_BIT:0;
 CHECK(!pthread_mutex_init(&c->lock,NULL));if(enabled){c->object_cache=calloc(1,sizeof(struct set));CHECK(c->object_cache);}
}
static void close_cache(struct vk_pipeline_cache *c) {
 if(c->object_cache){
  while(c->object_cache->head){struct set_entry *e=c->object_cache->head;c->object_cache->head=e->next;
   vk_pipeline_cache_object_unref(c->base.device,(void *)e->key);free(e);}
  free(c->object_cache);
 } CHECK(!pthread_mutex_destroy(&c->lock));
}
static void init_device(struct tu_device *d,struct vk_pipeline_cache *c,bool enabled) {
 static struct vk_physical_device physical={0};memset(d,0,sizeof *d);d->vk.physical=&physical;d->mem_cache=c;init_cache(c,d,enabled,false);
}
static size_t entries(struct vk_pipeline_cache *c) {
 size_t n=0;if(c->object_cache)for(struct set_entry *e=c->object_cache->head;e;e=e->next)n++;return n;
}
static struct tu_shader *compile_shader(uint64_t id,uint64_t variant) {
 struct tu_shader *s=calloc(1,sizeof *s);CHECK(s);s->key[0]=id;s->key[1]=variant;s->value=id^variant^0x36516;
 vk_pipeline_cache_object_init(NULL,&s->base,&tu_shader_ops,s->key,sizeof s->key);
 p_atomic_inc(&made);uint64_t now=__atomic_add_fetch(&live,1,__ATOMIC_SEQ_CST),prev=p_atomic_read(&peak);
 while(now>prev&&!__atomic_compare_exchange_n(&peak,&prev,now,false,__ATOMIC_SEQ_CST,__ATOMIC_SEQ_CST)){}
 return s;
}
static void drop(struct tu_device *d,struct tu_shader *s){vk_pipeline_cache_object_unref(&d->vk,&s->base);}
static void sequential(void) {
 struct tu_device d;struct vk_pipeline_cache mem,a,b;init_device(&d,&mem,true);init_cache(&a,&d,true,false);init_cache(&b,&d,true,false);
 const uint64_t key[]={7,9};bool hit=true;CHECK(!tu_pipeline_cache_lookup(&a,key,sizeof key,&hit)&&!hit);
 struct tu_shader *s=tu_pipeline_cache_insert(&a,compile_shader(7,9));CHECK(s->base.ref_cnt==3);
 struct tu_shader *t=tu_pipeline_cache_lookup(&b,key,sizeof key,&hit);CHECK(t==s&&!hit&&s->base.ref_cnt==5);drop(&d,t);
 t=tu_pipeline_cache_lookup(&b,key,sizeof key,&hit);CHECK(t==s&&hit);drop(&d,t);
 t=tu_pipeline_cache_lookup(&mem,key,sizeof key,&hit);CHECK(t==s&&hit);drop(&d,t);
 const uint64_t other[]={7,10};CHECK(!tu_pipeline_cache_lookup(&b,other,sizeof other,NULL));
 CHECK(!tu_pipeline_cache_lookup(&b,key,sizeof(uint64_t),NULL));
 t=tu_pipeline_cache_insert(&b,compile_shader(7,9));CHECK(t==s);drop(&d,t);
 close_cache(&a);close_cache(&b);CHECK(s->base.ref_cnt==2);drop(&d,s);CHECK(live==1);
 init_cache(&b,&d,true,false);t=tu_pipeline_cache_lookup(&b,key,sizeof key,&hit);CHECK(t&&!hit);
 close_cache(&b);close_cache(&mem);CHECK(live==1);drop(&d,t);CHECK(live==0);
}
static void isolation_and_modes(void) {
 for(unsigned enabled=0;enabled<4;enabled++) {
  struct tu_device d,e;struct vk_pipeline_cache mem,other,a;init_device(&d,&mem,enabled&1);init_device(&e,&other,true);
  init_cache(&a,&d,enabled&2,true);uint64_t key[]={11,12};bool hit;
  struct tu_shader *s=tu_pipeline_cache_insert(&a,compile_shader(11,12));
  CHECK(!tu_pipeline_cache_lookup(&other,key,sizeof key,&hit));
  struct tu_shader *t=tu_pipeline_cache_lookup(&a,key,sizeof key,&hit);
  CHECK((t!=NULL)==(enabled!=0));if(t){CHECK(t->value==s->value);drop(&d,t);}
  close_cache(&a);close_cache(&mem);close_cache(&other);drop(&d,s);CHECK(live==0);
 }
 struct tu_device d;struct vk_pipeline_cache mem;init_device(&d,&mem,true);
 struct tu_shader *s=tu_pipeline_cache_insert(&mem,compile_shader(1,2));CHECK(s->base.ref_cnt==2);
 drop(&d,s);close_cache(&mem);CHECK(live==0);
}
struct thread_arg {struct tu_device *device;unsigned index;};
static void *concurrent(void *v) {
 struct thread_arg *a=v;
 for(unsigned round=0;round<100;round++) {
  struct vk_pipeline_cache c;init_cache(&c,a->device,true,false);
  for(unsigned j=0;j<32;j++) {
   uint64_t key[]={j,(j%3)+1};bool hit;
   struct tu_shader *s=tu_pipeline_cache_lookup(&c,key,sizeof key,&hit);
   if(!s){sched_yield();s=tu_pipeline_cache_insert(&c,compile_shader(key[0],key[1]));}
   CHECK(s->value==(key[0]^key[1]^0x36516));drop(a->device,s);
  } close_cache(&c);
 }return NULL;
}
static void racing(void) {
 struct tu_device d;struct vk_pipeline_cache mem;init_device(&d,&mem,true);
 pthread_t th[8];struct thread_arg args[8];
 for(unsigned i=0;i<8;i++){args[i]=(struct thread_arg){&d,i};CHECK(!pthread_create(&th[i],NULL,concurrent,&args[i]));}
 for(unsigned i=0;i<8;i++)CHECK(!pthread_join(th[i],NULL));
 CHECK(entries(&mem)==32&&live==32);close_cache(&mem);CHECK(live==0);
}
int main(void) {
 sequential();isolation_and_modes();racing();CHECK(made==freed);
 printf("{\"passed\":true,\"threads\":8,\"concurrent_requests\":25600,\"allocated\":%llu,\"destroyed\":%llu,\"peak_live\":%llu,\"live_after_device_close\":%llu}\n",
  (unsigned long long)made,(unsigned long long)freed,(unsigned long long)peak,(unsigned long long)live);
}
