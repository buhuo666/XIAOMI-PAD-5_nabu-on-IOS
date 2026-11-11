static ipc_kmsg *message(uint32_t id=40205,bool ool=false){
 auto *k=new ipc_kmsg;k->header.msgh_id=id;k->header.msgh_size=sizeof(mach_msg_header_t)+(id==40205?24:12);
 k->header.msgh_bits=19;k->header.msgh_remote_port=&destination;k->trailer.msgh_audit.val[5]=sender_task.pid;
 if(ool)k->out_data=new uint8_t[24]{};auto *p=static_cast<uint8_t*>(ikm_udata(k,0,false));
 memcpy(p,&NDR_record,8);uint32_t v=1234;memcpy(p+8,&v,4);
 if(id==40205){v=3;memcpy(p+12,&v,4);uint64_t bits=0x400921fb54442d18;memcpy(p+16,&bits,8);}return k;}
static void reset(){assert(destination.ip_messages.imq_messages.empty());events.clear();
 destination=port{};destination.ip_messages.owner=&destination;destination.ip_waitq.owner=&destination;destination.ts.ts_waitq.owner=&destination;
 send_thread=thread{};receive_thread=thread{};receive_thread.owner=&receiver_task;active_thread=&send_thread;
 blocked=knote_count=freed=importance_cleaned=0;copyin_result=pseudo_result=copyout_result=put_result=get_result=0;
 wait_result=THREAD_AWAKENED;window_id=1;resume_action={};unlock_action={};}
static size_t count(uint32_t e){return std::count_if(events.begin(),events.end(),[=](const Event&r){return r.event==e;});}
static Event one(uint32_t e){auto it=std::find_if(events.begin(),events.end(),[=](const Event&r){return r.event==e;});assert(it!=events.end());return *it;}
static uint32_t send(ipc_kmsg*k,uint64_t options=1,uint32_t timeout=0){next_user_message=k;
 mach_msg_user_header_t h{};h.msgh_id=k->header.msgh_id;h.msgh_bits=k->header.msgh_bits;
 return mach_msg_trap_send(100,0,options,timeout,0,false,h,k->header.msgh_size-8,0,0);}
static uint32_t receive_selected(thread*t){auto *old=active_thread;active_thread=t;
 auto r=mach_msg_receive_results_kevent(nullptr,nullptr,nullptr,nullptr);active_thread=old;return r;}
static uint32_t drain(uint64_t option=0){ip_mq_lock(&destination);receive_thread.ith_option=option;
 ipc_mqueue_select_on_thread_locked(&destination.ip_messages,option,receive_thread.ith_max_msize,0,&receive_thread);
 ip_mq_unlock(&destination);return receive_selected(&receive_thread);}
static void filter_and_body(){reset();assert(sizeof(mach_msg_header_t)==32&&sizeof(mach_msg_user_header_t)==24);
 for(bool ool:{false,true})for(uint32_t id:{40205u,40402u}){auto*k=message(id,ool);auto s=nabu_ca_ipc_capture(k,-1);
 assert(s.window==1&&s.messageID==id&&s.senderPID==204&&s.bodyID==1234);
 assert(s.flags==(id==40205?3:0));assert(s.inputTimeBits==(id==40205?0x400921fb54442d18ull:0));
 auto bytes=std::array<uint8_t,24>{};memcpy(bytes.data(),ikm_udata(k,0,false),24);
 k->header.msgh_bits|=MACH_MSGH_BITS_COMPLEX;assert(!nabu_ca_ipc_capture(k,-1).window);k->header.msgh_bits&=~MACH_MSGH_BITS_COMPLEX;
 k->header.msgh_size+=4;assert(!nabu_ca_ipc_capture(k,-1).window);k->header.msgh_size-=4;
 static_cast<uint8_t*>(ikm_udata(k,0,false))[4]=0;assert(!nabu_ca_ipc_capture(k,-1).window);
 memcpy(ikm_udata(k,0,false),bytes.data(),24);window_id=0;assert(!nabu_ca_ipc_capture(reinterpret_cast<ipc_kmsg*>(1),-1).window);
 window_id=1;ipc_kmsg_free(k);}
 auto*k=message(40204);assert(!nabu_ca_ipc_capture(k,-1).window);ipc_kmsg_free(k);
 puts("shape: exact native simple message shapes, non-linear body, disabled no dereference");}
static void queued_roundtrip(){for(bool enabled:{false,true}){reset();window_id=enabled?1:0;destination.klist=true;
 auto*k=message(40205,true);uint8_t original[24];memcpy(original,k->out_data,24);assert(send(k)==0);
 assert(destination.ip_messages.imq_msgcount==1&&knote_count==1);assert(memcmp(original,k->out_data,24)==0);
 assert(drain()==0&&freed==1&&destination.ip_messages.imq_msgcount==0);
 if(!enabled){assert(events.empty());continue;}
 assert(count(NabuCaIpcQueued)==1&&count(NabuCaIpcDequeued)==1&&count(NabuCaIpcDirect)==0);
 assert(one(NabuCaIpcSendBegin).id==one(NabuCaIpcSendReturn).id);
 assert(one(NabuCaIpcReceiveBegin).id==one(NabuCaIpcReceiveResult).id);
 assert(one(NabuCaIpcSendBegin).id!=one(NabuCaIpcReceiveBegin).id);
 assert((one(NabuCaIpcReceivePayload).b>>32)==88);assert((one(NabuCaIpcQueued).a>>32)==204);
 assert(one(NabuCaIpcSendPayload).a==0x400921fb54442d18ull);}
 puts("queued: send, enqueue, actual selection, copyout result; IPC state identical when disabled");}
static void direct_free_before_send_return(){reset();destination.receivers.push_back(&receive_thread);
 resume_action=[](thread*t){assert(t->ith_kmsg);assert(receive_selected(t)==0);};
 auto*k=message(40402);assert(send(k,0x11,0)==0);assert(freed==1&&destination.ip_messages.imq_msgcount==0);
 assert(count(NabuCaIpcDirect)==1&&count(NabuCaIpcQueued)==0);
 assert(one(NabuCaIpcSendBegin).id==one(NabuCaIpcSendReturn).id);
 assert(one(NabuCaIpcSendPayload).a==0&&one(NabuCaIpcSendPayload).b==0x11);
 puts("direct: receiver frees kmsg before sender returns; result uses retained stack snapshot");}
static void queue_limits_and_failures(){
 for(int result:{THREAD_TIMED_OUT,THREAD_INTERRUPTED,THREAD_RESTART,THREAD_AWAKENED}){reset();destination.full=true;wait_result=result;
 auto*k=message(40402);uint32_t r=send(k,0x11,10);
 if(result==THREAD_AWAKENED){assert(r==0&&blocked==1);assert(drain()==0);}
 else if(result==THREAD_RESTART){assert(r==0&&freed==1);assert(one(NabuCaIpcDropped).b==NabuCaIpcPortDiedWhileSending);}
 else {assert(r==(result==THREAD_TIMED_OUT?MACH_SEND_TIMED_OUT:MACH_SEND_INTERRUPTED));assert(freed==1);assert(one(NabuCaIpcSendResult).b==r);}
 assert(one(NabuCaIpcSendReturn).b==r);}
 reset();destination.full=true;assert(send(message(40402),0x11,0)==MACH_SEND_TIMED_OUT);assert(blocked==0&&count(NabuCaIpcQueued)==0);
 reset();destination.full=true;assert(send(message(),1,0)==0&&blocked==1);assert(drain()==0);
 reset();destination.full=true;destination.kernel_full=true;assert(send(message())==MACH_SEND_NO_BUFFER&&freed==1);
 reset();copyin_result=MACH_SEND_INVALID_DEST;assert(send(message())==copyin_result&&freed==1);assert(one(NabuCaIpcSendResult).c==1);
 reset();destination.full=true;wait_result=THREAD_INTERRUPTED;pseudo_result=0x100;auto r=send(message());
 assert(one(NabuCaIpcSendResult).b==MACH_SEND_INTERRUPTED);assert(one(NabuCaIpcSendReturn).b==r&&r==(MACH_SEND_INTERRUPTED|pseudo_result));
 puts("failure: queue timeout, interruption, no-buffer, copyin, raw and pseudo-copyout status; send-only can block");}
static void destroyed_success(){for(int mode=0;mode<3;++mode){reset();auto*k=message();
 if(mode==0)destination.active=false;if(mode==1)k->header.msgh_bits|=MACH_MSGH_BITS_CIRCULAR;if(mode==2)destination.valid=false;
 assert(send(k)==0&&freed==1);assert(count(NabuCaIpcDropped)==1&&count(NabuCaIpcDirect)==0&&count(NabuCaIpcQueued)==0);
 assert(one(NabuCaIpcDropped).b==uint64_t(mode==0?NabuCaIpcInactivePort:mode==1?NabuCaIpcCircular:NabuCaIpcPostDestroyed));}
 puts("destroy: API success is distinct from delivery for dead/circular/post-invalid destinations");}
static void large_peek_and_copyout(){reset();assert(send(message())==0);receive_thread.ith_max_msize=8;
 assert(drain(MACH_RCV_LARGE)==MACH_RCV_TOO_LARGE&&freed==0&&destination.ip_messages.imq_msgcount==1);
 assert(count(NabuCaIpcReceiveNotTaken)==1&&count(NabuCaIpcReceiveBegin)==0);
 receive_thread.ith_max_msize=256;assert(drain()==0&&freed==1);
 reset();assert(send(message())==0);receive_thread.ith_max_msize=8;assert(drain()==MACH_RCV_TOO_LARGE&&freed==1);
 assert(one(NabuCaIpcReceiveResult).b==MACH_RCV_TOO_LARGE);
 reset();receive_thread.ith_state=MACH_PEEK_IN_PROGRESS;destination.receivers.push_back(&receive_thread);
 assert(send(message())==0&&count(NabuCaIpcQueued)==1&&count(NabuCaIpcDirect)==0);receive_thread.ith_state=MACH_RCV_IN_PROGRESS;assert(drain()==0);
 for(uint32_t error:{MACH_RCV_HEADER_ERROR,MACH_RCV_BODY_ERROR}){reset();assert(send(message())==0);copyout_result=error;assert(drain()==error);
 assert(one(NabuCaIpcReceiveResult).b==error&&freed==1);}
 reset();assert(send(message())==0);put_result=MACH_RCV_INVALID_DATA;assert(drain()==MACH_RCV_INVALID_DATA&&freed==1);
 assert(one(NabuCaIpcReceiveResult).b==MACH_RCV_INVALID_DATA);
 reset();receive_thread.ith_max_msize=8;receive_thread.ith_option=MACH_RCV_LARGE;
 destination.receivers.push_back(&receive_thread);resume_action=[](thread*t){assert(t->ith_kmsg==nullptr);};
 assert(send(message())==0&&count(NabuCaIpcReceiveNotTaken)==1&&count(NabuCaIpcQueued)==1);
 resume_action={};receive_thread.ith_max_msize=256;assert(drain()==0);
 puts("receive: LARGE remains queued, destructive too-large, peek, header/body/copyout failures");}
static void same_cookie_tokens_and_window(){reset();auto*k=message();auto first=nabu_ca_ipc_capture(k,-1);nabu_ca_ipc_begin(&first,NabuCaIpcSendBegin);
 auto second=nabu_ca_ipc_capture(k,-1);nabu_ca_ipc_begin(&second,NabuCaIpcSendBegin);
 assert(first.cookie==second.cookie&&first.token!=second.token);
 ipc_kmsg_free(k);nabu_ca_ipc_paired(&first,NabuCaIpcSendReturn,first.cookie,0,0);
 assert(events.back().id==first.token);window_id=2;nabu_ca_ipc_paired(&second,NabuCaIpcSendReturn,second.cookie,0,0);
 assert(events.back().id==first.token);
 puts("identity: delayed results keep begin token across same cookie and stale window is refused");}
static void concurrent_tokens(){reset();std::vector<std::thread> workers;
 for(unsigned i=0;i<4;++i)workers.emplace_back([]{for(unsigned n=0;n<100;++n){auto*k=message();
   auto s=nabu_ca_ipc_capture(k,-1);nabu_ca_ipc_begin(&s,NabuCaIpcSendBegin);
   delete[] k->out_data;delete k;nabu_ca_ipc_paired(&s,NabuCaIpcSendReturn,s.cookie,0,0);}});
 for(auto &t:workers)t.join();std::vector<uint64_t> starts,ends;
 for(const auto&r:events){if(r.event==NabuCaIpcSendBegin)starts.push_back(r.id);else ends.push_back(r.id);}
 std::sort(starts.begin(),starts.end());std::sort(ends.begin(),ends.end());
 assert(starts.size()==400&&starts==ends&&std::adjacent_find(starts.begin(),starts.end())==starts.end());
 puts("concurrency: 400 begin/result tokens unique across four recorder producers (IPC scheduling remains simulated)");}
int main(){filter_and_body();queued_roundtrip();direct_free_before_send_return();queue_limits_and_failures();destroyed_success();large_peek_and_copyout();same_cookie_tokens_and_window();
 concurrent_tokens();
 puts("actual XNU IPC trace host checks passed");}
