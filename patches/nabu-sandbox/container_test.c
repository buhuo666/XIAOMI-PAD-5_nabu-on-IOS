#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
typedef uintptr_t user_addr_t,user_size_t,vm_offset_t,vm_size_t,vm_map_address_t;
typedef void *task_t,*vm_map_t,*vm_map_copy_t;
struct proc {user_addr_t user_stack;size_t p_argslen;};typedef struct proc*proc_t;
static struct proc process;
static int failure,proc_refs,task_refs,map_refs,allocs;
static size_t copied;
static char input[4096],output[1024];
#define PROC_NULL NULL
#define TASK_NULL NULL
#define VM_MAP_NULL NULL
#define KERN_SUCCESS 0
#define FALSE false
#define KMA_DATA 0
#define KMA_ZERO 0
#define VM_KERN_MEMORY_BSD 0
#define SANDBOX_CONTAINER_VARIABLE "CFFIXED_USER_HOME="
static void*kernel_map=(void*)1;
static int copyin(user_addr_t p,void*to,size_t n){if(failure==1)return EFAULT;memcpy(to,(void*)p,n);return 0;}
static int copyout(const void*src,user_addr_t dst,size_t n){if(failure==7)return EFAULT;assert(dst==(uintptr_t)output&&n<=sizeof output);memcpy((void*)dst,src,n);copied=n;return 0;}
static proc_t proc_find(int pid){if(pid!=123)return NULL;proc_refs++;return &process;}
static int proc_pidversion(proc_t p){assert(p==&process);return 9;}
static void proc_rele(proc_t p){assert(p==&process&&proc_refs==1);proc_refs--;}
static task_t proc_task(proc_t p){assert(p==&process);return failure==2?NULL:(void*)2;}
static void task_reference(task_t t){assert(t==(void*)2);task_refs++;}
static void task_deallocate(task_t t){assert(t==(void*)2&&task_refs==1);task_refs--;}
static vm_map_t get_task_map_reference(task_t t){assert(t==(void*)2);if(failure==3)return NULL;map_refs++;return (void*)3;}
static void vm_map_deallocate(vm_map_t m){assert(m==(void*)3&&map_refs==1);map_refs--;}
static size_t vm_map_page_mask(vm_map_t m){assert(m==(void*)3);return 4095;}
static size_t vm_map_round_page(size_t n,size_t mask){return(n+mask)&~mask;}
static int kmem_alloc(void*k,vm_offset_t*p,size_t n,int flags,int reason){(void)k;(void)flags;(void)reason;if(failure==4)return 1;*p=(uintptr_t)calloc(1,n);assert(*p);allocs++;return 0;}
static void kmem_free(void*k,uintptr_t p,size_t n){(void)k;(void)n;assert(allocs==1);allocs--;free((void*)p);}
static int vm_map_copyin(vm_map_t m,uintptr_t a,size_t n,bool destroy,vm_map_copy_t*c){(void)destroy;assert(m==(void*)3&&a==(uintptr_t)input&&n==sizeof input);if(failure==5)return 1;*c=input;return 0;}
static int vm_map_copy_overwrite(void*m,uintptr_t to,vm_map_copy_t c,size_t n,bool interrupt){(void)m;(void)interrupt;if(failure==6)return 1;memcpy((void*)to,c,n);return 0;}
static void vm_map_copy_discard(vm_map_copy_t c){assert(c==input);}
/* ACTUAL_FUNCTION */
static unsigned cases;
static void check(const char*env,size_t envlen,int fail,int pid,int version,size_t limit,int expected,bool empty){
    memset(input,0,sizeof input);assert(envlen<=sizeof input);memcpy(input+sizeof input-envlen,env,envlen);
    memset(output,0xa5,sizeof output);process=(struct proc){(uintptr_t)(input+sizeof input),empty?0:envlen};
    failure=fail;copied=0;
    struct {int64_t pid;uint64_t version;user_addr_t buffer;user_size_t size;uint64_t check_version;} a={pid,(uint64_t)version,(uintptr_t)output,limit,version!=0};
    int result=minisandbox_container_path((uintptr_t)&a);assert(result==expected);
    assert(!proc_refs&&!task_refs&&!map_refs&&!allocs);
    if(result==0){assert(copied>0&&memchr(output,0,copied));assert(!strcmp(output,"/private/var/mobile/test-container"));}
    else {assert(!copied);for(unsigned i=0;i<sizeof output;i++)assert((unsigned char)output[i]==0xa5);}
    cases++;
}
int main(void){
    const char good[]="X=1\0CFFIXED_USER_HOME=/private/var/mobile/test-container\0Z=2\0";
    const char absent[]="X=1\0HOME=/var/mobile\0";
    const char empty[]="CFFIXED_USER_HOME=\0";
    const char unterminated[]="CFFIXED_USER_HOME=/private/var/mobile/test-container";
    check(good,sizeof good-1,0,123,9,1024,0,false);
    check(absent,sizeof absent-1,0,123,9,1024,ENOENT,false);
    check(empty,sizeof empty-1,0,123,9,1024,ENOENT,false);
    check(unterminated,sizeof unterminated-1,0,123,9,1024,ENOENT,false);
    check(good,sizeof good-1,0,123,9,1024,ENOENT,true);
    check(good,sizeof good-1,0,999,9,1024,ESRCH,false);
    check(good,sizeof good-1,0,123,8,1024,ESRCH,false);
    check(good,sizeof good-1,1,123,9,1024,EFAULT,false);
    check(good,sizeof good-1,2,123,9,1024,ENOENT,false);
    check(good,sizeof good-1,3,123,9,1024,ENOENT,false);
    check(good,sizeof good-1,4,123,9,1024,ENOMEM,false);
    check(good,sizeof good-1,5,123,9,1024,ENOENT,false);
    check(good,sizeof good-1,6,123,9,1024,ENOENT,false);
    check(good,sizeof good-1,7,123,9,1024,EFAULT,false);
    size_t length=strlen("/private/var/mobile/test-container");
    for(size_t n=0;n<=length+2;n++)check(good,sizeof good-1,0,123,9,n,n>length?0:ENAMETOOLONG,false);
    printf("{\"passed\":true,\"cases\":%u,\"absent_path_fails\":true,\"valid_path_exact\":true,\"cleanup_balanced\":true}\n",cases);
}
