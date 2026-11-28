#include <assert.h>
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define user_addr_t fixture_user_addr_t
typedef uintptr_t user_addr_t;
struct proc { const char *p_comm; };typedef struct proc*proc_t;
#define PROC_NULL NULL
#define SANDBOX_SYSCALL_CONTAINER_PATH 4
static struct proc process={"test"};
static unsigned cases,refs,in_count,out_count,str_count,fail_in,fail_out,fail_str;
static uint64_t minisandbox_seen;
static unsigned char token[2048],results[1024*1024+4];
static uint64_t decision;
static int copyin(user_addr_t a,void*b,size_t n){in_count++;if(in_count==fail_in||!a)return EFAULT;memcpy(b,(void*)a,n);return 0;}
static int copyout(const void*a,user_addr_t b,size_t n){out_count++;if(out_count==fail_out||!b)return EFAULT;memcpy((void*)b,a,n);return 0;}
static int copyinstr(user_addr_t a,void*b,size_t n,size_t*len){str_count++;if(str_count==fail_str||!a)return EFAULT;size_t l=strnlen((void*)a,n);if(l==n)return ENAMETOOLONG;memcpy(b,(void*)a,l+1);*len=l+1;return 0;}
static proc_t proc_find(int pid){if(pid!=123)return NULL;refs++;return &process;}
static void proc_rele(proc_t p){assert(p==&process&&refs==1);refs--;}
static int proc_pidversion(proc_t p){assert(p==&process);return 9;}
static int proc_getpid(proc_t p){assert(p==&process);return 123;}
static int minisandbox_container_path(user_addr_t a){(void)a;return ENOENT;}
static int quiet_printf(const char *s,...){(void)s;return 0;}
#define printf quiet_printf
/* OUTPUT_FUNCTIONS */
/* DISPATCH_FUNCTION */
#undef printf
struct issue {uintptr_t cls;uint64_t type;uintptr_t resource;uint64_t flags;uintptr_t token;int64_t pid;uint64_t version;};
struct query {uint64_t word[13];};
struct bulk {int64_t pid;uint64_t version;uintptr_t operation;uint64_t flags,count;uintptr_t items,result;};
_Static_assert(sizeof(struct issue)==56&&offsetof(struct issue,token)==32,"issue ABI");
_Static_assert(sizeof(struct query)==104,"check ABI");
_Static_assert(sizeof(struct bulk)==56&&offsetof(struct bulk,result)==48,"bulk ABI");
static void reset(void){assert(!refs);memset(token,0xa5,sizeof token);memset(results,0x5a,sizeof results);decision=0xa5a5a5a5a5a5a5a5ULL;in_count=out_count=str_count=fail_in=fail_out=fail_str=0;}
static void untouched(const void*p,size_t n,unsigned char byte){const unsigned char*b=p;for(size_t i=0;i<n;i++)assert(b[i]==byte);}
static int call(int c,void*p){int e=minisandbox_policy_syscall(&process,c,(uintptr_t)p);assert(!refs);cases++;return e;}
int main(void){
    const char cls[]="com.apple.app-sandbox.read",path[]="/private/var/mobile/test";
    for(unsigned type=0;type<=6;type++)for(unsigned mode=0;mode<3;mode++){
        reset();struct issue a={(uintptr_t)cls,type,type==3?0:(uintptr_t)path,mode?0x10000:0,(uintptr_t)token,123,9};if(mode==2)a.flags|=0x20000;
        assert(call(5,&a)==0);assert(!strcmp((char*)token,"invalid"));untouched(token+8,sizeof token-8,0xa5);
        assert(out_count==1);
    }
    for(unsigned failure=1;failure<=5;failure++){
        reset();struct issue a={(uintptr_t)cls,0,(uintptr_t)path,0,(uintptr_t)token,123,9};
        if(failure==1)fail_in=1;if(failure==2)fail_str=1;if(failure==3)fail_str=2;if(failure==4)fail_out=1;if(failure==5)a.token=0;
        assert(call(5,&a)==(failure==5?EINVAL:EFAULT));untouched(token,sizeof token,0xa5);
    }
    for(unsigned mode=0;mode<10;mode++){
        reset();struct issue a={(uintptr_t)cls,0,(uintptr_t)path,0,(uintptr_t)token,123,9};int want=EINVAL;
        switch(mode){case 0:a.type=7;break;case 1:a.type=1ULL<<32;break;case 2:a.resource=0;break;case 3:a.flags=1ULL<<63;break;case 4:a.flags=0x20000;break;case 5:a.flags=4;want=ENOTSUP;break;case 6:a.type=1;a.flags=8;want=ENOTSUP;break;case 7:a.flags=0x10000;a.pid=999;want=ESRCH;break;case 8:a.flags=0x30000;a.version=8;want=ESRCH;break;case 9:a.flags=0x10000;a.pid=(1ULL<<32)+123;want=ESRCH;break;}
        assert(call(5,&a)==want);untouched(token,sizeof token,0xa5);
    }
    char oversized[1025];memset(oversized,'a',sizeof oversized);oversized[1024]=0;
    reset();struct issue i={(uintptr_t)oversized,3,0,0,(uintptr_t)token,0,0};assert(call(5,&i)==ENAMETOOLONG);
    reset();i.cls=(uintptr_t)cls;i.type=0;i.resource=(uintptr_t)oversized;assert(call(5,&i)==ENAMETOOLONG);
    reset();i.cls=(uintptr_t)"";assert(call(5,&i)==EINVAL);
    for(unsigned n=0;n<12;n++){
        reset();struct query q={{0}};q.word[0]=(uintptr_t)&decision;q.word[5]=(n<6?n:0x4000000ULL+(n-6));
        q.word[11]=(uintptr_t)token;q.word[12]=(uintptr_t)results;
        assert(call(2,&q)==(n<6?0:ENOTSUP));
        assert(decision==(n<6?0:0xa5a5a5a5a5a5a5a5ULL));untouched(token,sizeof token,0xa5);untouched(results,sizeof results,0x5a);
    }
    for(unsigned n=0;n<3;n++){
        reset();struct query q={{0}};q.word[0]=(uintptr_t)&decision;if(n==0)fail_in=1;else if(n==1)fail_out=1;else q.word[0]=0;
        assert(call(2,&q)==EFAULT);assert(decision==0xa5a5a5a5a5a5a5a5ULL);
    }
    uint64_t counts[]={1,2,3,7,255,256,257,511,512,513,4096,1024*1024};
    for(unsigned n=0;n<sizeof counts/sizeof counts[0];n++){
        reset();struct bulk b={123,9,(uintptr_t)"file-read-data",0,counts[n],1,(uintptr_t)(results+2)};
        assert(call(21,&b)==0);untouched(results,2,0x5a);untouched(results+2,counts[n],0);untouched(results+2+counts[n],sizeof results-2-counts[n],0x5a);
        assert(in_count==1&&out_count==(counts[n]+255)/256);
    }
    for(unsigned n=0;n<10;n++){
        reset();struct bulk b={123,9,(uintptr_t)cls,0,10,1,(uintptr_t)(results+2)};int want=EINVAL;
        switch(n){case 0:b.count=0;break;case 1:b.operation=0;break;case 2:b.items=0;break;case 3:b.result=0;break;case 4:b.count=1ULL<<60;want=ERANGE;break;case 5:b.count=1024*1024+1;want=ERANGE;break;case 6:b.result=UINTPTR_MAX-2;want=ERANGE;break;case 7:b.pid=999;want=ESRCH;break;case 8:b.version=8;want=ESRCH;break;case 9:b.pid=(1ULL<<32)+123;want=ESRCH;break;}
        assert(call(21,&b)==want);untouched(results,sizeof results,0x5a);
    }
    for(unsigned n=0;n<4;n++){
        reset();struct bulk b={123,9,(uintptr_t)cls,0,600,1,(uintptr_t)(results+2)};
        if(!n)fail_in=1;else fail_out=n;
        assert(call(21,&b)==EFAULT);size_t prefix=n?(n-1)*256:0;
        untouched(results,2,0x5a);untouched(results+2,prefix,0);untouched(results+2+prefix,sizeof results-2-prefix,0x5a);
    }
    reset();assert(call(4,NULL)==ENOENT);assert(call(1,NULL)==0);assert(call(7,NULL)==0);assert(call(52,NULL)==0);assert(call(67,NULL)==0);
    printf("{\"passed\":true,\"cases\":%u,\"token_nul_and_tail\":true,\"normal_check_allowed\":true,\"filter_query_fails_explicitly\":true,\"bulk_one_byte_per_item\":true,\"copy_faults_propagated\":true,\"references_balanced\":true}\n",cases);
}
