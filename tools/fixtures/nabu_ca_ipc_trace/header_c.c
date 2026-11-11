/* Compile the installed helper as C, as used by the actual XNU call sites. */
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#define NABU_CA_IPC_HOST_TEST 1
#define IKM_NULL ((ipc_kmsg_t)0)
#define MACH_MSGH_BITS_COMPLEX 0x80000000u
typedef struct {uint32_t msgh_bits,msgh_size;uintptr_t remote,local;uint32_t voucher;int32_t msgh_id;} mach_msg_header_t;
typedef struct {uint8_t bytes[8];} NDR_record_t;
typedef struct {struct {uint32_t val[8];} msgh_audit;} mach_msg_max_trailer_t;
typedef struct ipc_kmsg {mach_msg_header_t header;uint8_t data[24];mach_msg_max_trailer_t trailer;} *ipc_kmsg_t;
static NDR_record_t NDR_record={{0,0,0,0,1,0,0,0}};
static mach_msg_header_t *ikm_header(ipc_kmsg_t k){return &k->header;}
static void *ikm_udata(ipc_kmsg_t k,uint32_t count,bool complex){(void)count;(void)complex;return k->data;}
static mach_msg_max_trailer_t *ipc_kmsg_get_trailer(ipc_kmsg_t k,bool copied){(void)copied;return &k->trailer;}
#include "NabuCaIpcTrace.h"
uint32_t nabu_ca_ipc_trace_window(void){return 1;}
static unsigned records;
void nabu_ca_ipc_trace_record(uint32_t w,uint32_t e,uint64_t id,uint64_t a,uint64_t b,uint64_t c){
 (void)e;(void)id;(void)a;(void)b;(void)c;assert(w==1);++records;}
int main(void){struct ipc_kmsg k={0};k.header.msgh_id=40402;k.header.msgh_size=sizeof(k.header)+12;
 memcpy(k.data,&NDR_record,8);uint32_t q=67;memcpy(k.data+8,&q,4);k.trailer.msgh_audit.val[5]=204;
 NabuCaIpcSnapshot s=nabu_ca_ipc_capture(&k,-1);assert(s.bodyID==67&&s.senderPID==204);
 nabu_ca_ipc_begin(&s,NabuCaIpcSendBegin);nabu_ca_ipc_paired(&s,NabuCaIpcSendReturn,s.cookie,0,0);
 nabu_ca_ipc_stage(&s,NabuCaIpcQueued,0);nabu_ca_ipc_drop(&s,NabuCaIpcPostDestroyed,1);
 assert(records==4);return 0;}
