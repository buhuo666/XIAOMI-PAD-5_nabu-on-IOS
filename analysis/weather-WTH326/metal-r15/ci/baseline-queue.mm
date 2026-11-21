
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <atomic>
#include <mutex>
#include <vector>
#include <cstdio>
#include <cassert>
struct NabuMetalEncodeStats {};
struct EncodedWork {};
struct NabuMetalSubmitSpan {template<class... A>NabuMetalSubmitSpan(A...) {}};
struct Metric {void add(uint64_t) {}};
static Metric gTimeWaitCompleted,gTimeWaitScheduled;
static std::atomic<unsigned> gCommits{0},gCommitFailures{0},notes{0};
static std::mutex gCommitLock,gRuntimeHandleLock;
struct CommitRecord {unsigned index=0;uint64_t committedUs=0,ageUs=0,scheduledUs=0;EncodedWork work;};
static CommitRecord gCommitRing[32];
static bool gDeviceHostCoherent=true;
static NSMutableSet *gInFlight;
static std::atomic<unsigned> presentations{0},statusChecks{0},statusFailures{0};
static void (^releaseHook)(void);
static void nabuCaPresent(id,bool,CFTimeInterval){presentations++;}
static void checkStatus(bool ok,const char*what){statusChecks++;if(!ok){statusFailures++;fprintf(stderr,"STATUS_REGRESSION: %s\n",what);}}
static uint64_t nowUs(){return 1;}
static void noteProblem(NSString *){notes++;}
static NSString *lastError(){return @"test backend refusal";}
static bool nabuMetalSubmitTraceEnabled(){return false;}
static void nabu_ca_trace_marker(int,unsigned,int,uint64_t,uint64_t){}
static void nabuMetalEncodeProfileEmit(NabuMetalEncodeStats&,unsigned,uint64_t){}
static void flushSurfaces(id){}
static void trimHeldImports(bool){}
#define NBLOG(...) ((void)0)
struct NmbQueue {};
struct NmbCommandBuffer {unsigned id;int status=0,waitResult=0;bool commitOK=true,synchronous=false,completeInCommit=false,concurrent=false,inCommit=false;int finalStatus=MTLCommandBufferStatusCompleted;
 void (*scheduled)(void*)=nullptr;void (*completed)(void*)=nullptr;void *context=nullptr;};
static std::vector<unsigned> submissionOrder;
static void nmb_queue_release(NmbQueue *p){delete p;}
static void nmb_command_buffer_release(NmbCommandBuffer *p){if(p&&releaseHook)releaseHook();delete p;}
static uint64_t nmb_command_buffer_trace_identity(NmbCommandBuffer *p){return p->id;}
static int nmb_command_buffer_status(NmbCommandBuffer *p){return p->status;}
static bool nmb_command_buffer_on_completed(NmbCommandBuffer *p,void (*fn)(void*),void *context){p->completed=fn;p->context=context;return true;}
static bool nmb_command_buffer_on_scheduled(NmbCommandBuffer *p,void (*fn)(void*),void *context){p->scheduled=fn;p->context=context;return true;}
static bool nmb_command_buffer_commit(NmbCommandBuffer *p){
 if(!p->commitOK)return false;submissionOrder.push_back(p->id);p->status=MTLCommandBufferStatusCommitted;
 if(p->synchronous){
  p->inCommit=true;
  void (^callbacks)(void)=^{
   p->status=MTLCommandBufferStatusScheduled;p->scheduled(p->context);
   if(p->completeInCommit){p->status=p->finalStatus;p->completed(p->context);}
  };
  if(p->concurrent){
   dispatch_semaphore_t done=dispatch_semaphore_create(0);
   dispatch_async(dispatch_get_global_queue(QOS_CLASS_DEFAULT,0),^{callbacks();dispatch_semaphore_signal(done);});
   assert(dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC))==0);
  }else callbacks();
  p->inCommit=false;
 }return true;
}
static int nmb_command_buffer_wait(NmbCommandBuffer *p,unsigned){return p->waitResult;}
static bool nmb_command_buffer_wait_scheduled(NmbCommandBuffer *p){return p->waitResult==0;}
@interface NBObject:NSObject @end
@implementation NBObject @end
@class NBCommandBuffer;
@interface NBQueueEntry:NSObject
@property(nonatomic,weak) NBCommandBuffer *buffer;
@property(nonatomic,strong) NBCommandBuffer *committedBuffer;
@end
@implementation NBQueueEntry @end
@interface NBQueue:NBObject
@property(nonatomic) NmbQueue *handle;
@property(nonatomic,strong) NSMutableArray<NBQueueEntry*> *orderedBuffers;
@property(atomic,strong) dispatch_queue_t completionQueue;
-(void)nbEnqueue:(NBCommandBuffer*)buffer;
-(void)nbCommit:(NBCommandBuffer*)buffer;
-(void)nbDiscardEntry:(NBQueueEntry*)entry;
-(void)nbDrain;
@end
@interface NBCommandBuffer:NBObject {
@public NabuMetalEncodeStats nabuEncodeStats;EncodedWork encodedWork;uint64_t createdUs;
}
@property(nonatomic) NmbCommandBuffer *handle;
@property(nonatomic,strong) NBQueue *queue;
@property(nonatomic,strong) NBQueueEntry *queueEntry;
@property(atomic,copy) NSString *encodeFailure;
@property(atomic) BOOL committed,failedLocally,enqueued,runtimeCommitted;
@property(nonatomic,strong) NSCondition *submissionIssued;
@property(nonatomic) uint64_t committedUs;
@property(nonatomic) uint32_t commitIndex;
@property(nonatomic,strong) NSMutableArray *scheduledHandlers,*completedHandlers;
@property(nonatomic,strong) NSHashTable *surfaces,*resourceOwners;
@property(nonatomic,strong) NSMutableDictionary *userDictionary;
@property(nonatomic) BOOL requestedRetainedReferences;
@property(nonatomic,strong) dispatch_group_t handlers,schedulingHandlers;
@property(nonatomic) BOOL schedulingDelivered;
-(void)refuse:(NSString*)why;-(void)enqueue;-(void)commit;-(void)nbSubmitNow;-(void)nbWaitForSubmission;
-(MTLCommandBufferStatus)status;-(void)waitUntilCompleted;-(void)waitUntilScheduled;-(void)didSchedule;-(void)finish;
-(void)addScheduledHandler:(MTLCommandBufferHandler)handler;
-(void)addCompletedHandler:(MTLCommandBufferHandler)handler;
-(void)presentDrawable:(id<MTLDrawable>)drawable atTime:(CFTimeInterval)time;
@end
static thread_local NBCommandBuffer *__unsafe_unretained nbFrontendHandler=nullptr;
static void scheduled(void *context){[(__bridge NBCommandBuffer*)context didSchedule];}
static void completed(void *context){NBCommandBuffer *b=(__bridge_transfer NBCommandBuffer*)context;[b finish];}

@implementation NBQueue
- (instancetype)init {if((self=[super init]))_orderedBuffers=[NSMutableArray array];return self;}

- (void)nbEnqueue:(NBCommandBuffer *)buffer {
 @synchronized(self) {
  if(buffer.enqueued)return;
  NBQueueEntry *entry=[NBQueueEntry new];entry.buffer=buffer;buffer.queueEntry=entry;[_orderedBuffers addObject:entry];buffer.enqueued=YES;
 }
}

- (void)nbCommit:(NBCommandBuffer *)buffer {
 @synchronized(self) {
  if(buffer.committed){noteProblem(@"commit called twice");return;}
  [self nbEnqueue:buffer];buffer.committed=YES;
  for(NBQueueEntry *entry in _orderedBuffers)if(entry.buffer==buffer){entry.committedBuffer=buffer;break;}
  [self nbDrain];
 }
}

- (void)nbDiscardEntry:(NBQueueEntry *)entry {
 @synchronized(self){[_orderedBuffers removeObjectIdenticalTo:entry];[self nbDrain];}
}

- (void)nbDrain {
  while(_orderedBuffers.count) {
   NBQueueEntry *entry=_orderedBuffers.firstObject;
   NBCommandBuffer *next=entry.committedBuffer?:entry.buffer;
   if(!next){[_orderedBuffers removeObjectAtIndex:0];continue;}
   if(!next.committed)break;
   [_orderedBuffers removeObjectAtIndex:0];next.queueEntry=nil;[next nbSubmitNow];
  }
}

- (void)dealloc {nmb_queue_release(_handle);}

@end
@implementation NBCommandBuffer
- (instancetype)init {
 if((self=[super init])) {
  _scheduledHandlers=[NSMutableArray array];
  _completedHandlers=[NSMutableArray array];
  _surfaces=gDeviceHostCoherent?nil:[NSHashTable hashTableWithOptions:NSPointerFunctionsStrongMemory];
  _resourceOwners=[NSHashTable hashTableWithOptions:NSPointerFunctionsStrongMemory];
  _userDictionary=[NSMutableDictionary dictionary];
  _requestedRetainedReferences=YES;
  _submissionIssued=[NSCondition new];
  _handlers=dispatch_group_create();
  _schedulingHandlers=dispatch_group_create();
 }
 if(self)createdUs=nowUs();
 return self;
}

- (void)dealloc {if(_queueEntry)[_queue nbDiscardEntry:_queueEntry];nmb_command_buffer_release(_handle);}

- (void)refuse:(NSString *)what {
 if(!self.encodeFailure){self.encodeFailure=what;NBLOG(@"native-metal: command buffer refused: %@",what);}
}

- (MTLCommandBufferStatus)status {
 if(self.failedLocally)return MTLCommandBufferStatusError;
 if(!self.runtimeCommitted)return self.committed?MTLCommandBufferStatusCommitted:(self.enqueued?MTLCommandBufferStatusEnqueued:MTLCommandBufferStatusNotEnqueued);
 return (MTLCommandBufferStatus)nmb_command_buffer_status(_handle);
}

- (void)enqueue {[_queue nbEnqueue:self];}

- (void)nbWaitForSubmission {
 [_submissionIssued lock];while(!self.runtimeCommitted)[_submissionIssued wait];[_submissionIssued unlock];
}

- (void)commit {[_queue nbCommit:self];}

- (void)nbSubmitNow {
 @try {
 self.committedUs=nowUs();
 {
  std::lock_guard<std::mutex> lock(gCommitLock);
  // Assign once under the same lock as publication. A concurrent commit cannot reuse this index.
  const uint32_t index=(uint32_t)(gCommits.fetch_add(1)+1);self.commitIndex=index;
  CommitRecord &r=gCommitRing[index%32];
  r={};r.index=index;r.committedUs=self.committedUs;r.ageUs=self.committedUs-createdUs;r.work=encodedWork;
 }
 if(nabuMetalSubmitTraceEnabled()) {
  const int saved=errno;
  const uint64_t runtime=nmb_command_buffer_trace_identity(_handle);
  nabu_ca_trace_marker(127,self.commitIndex,30,(uint64_t)(uintptr_t)(__bridge void *)self,runtime);
  errno=saved;
 }
 nabuMetalEncodeProfileEmit(nabuEncodeStats,self.commitIndex,(uint64_t)(uintptr_t)(__bridge void *)self);
 NabuMetalSubmitSpan commitTrace(16,17,self.commitIndex,(uint64_t)(uintptr_t)(__bridge void *)self);
 dispatch_group_enter(_handlers);
 dispatch_group_enter(_schedulingHandlers);
 @synchronized(gInFlight){[gInFlight addObject:self];}
 if(!self.encodeFailure) {
  {
 NabuMetalSubmitSpan surfaceTrace(18,19,self.commitIndex,(uint64_t)(uintptr_t)(__bridge void *)self);
   flushSurfaces(_surfaces);
  }
  // Completion owns this reference; the runtime orders the non-owning scheduled callback before it.
  void *context=(__bridge_retained void *)self;
  if(nmb_command_buffer_on_completed(_handle,completed,context) &&
     nmb_command_buffer_on_scheduled(_handle,scheduled,context) && ([&] {
 NabuMetalSubmitSpan runtimeCommitTrace(20,21,self.commitIndex,(uint64_t)(uintptr_t)(__bridge void *)self);
   return nmb_command_buffer_commit(_handle);
  }()))return;
  (void)CFBridgingRelease(context);   // refused registration/commit cannot call the registered handlers
  [self refuse:[@"commit: " stringByAppendingString:lastError()]];
 }
 self.failedLocally=YES;gCommitFailures++;
 dispatch_async(dispatch_get_global_queue(QOS_CLASS_DEFAULT,0),^{[self finish];});
 } @finally {
  [_submissionIssued lock];self.runtimeCommitted=YES;[_submissionIssued broadcast];[_submissionIssued unlock];
 }
}

- (void)waitUntilCompleted {
 if(!self.committed)return;
 if(nbFrontendHandler && (nbFrontendHandler==self || nbFrontendHandler.queue==self.queue ||
    (self.queue.completionQueue && nbFrontendHandler.queue.completionQueue==self.queue.completionQueue)) &&
    (!self.runtimeCommitted || dispatch_group_wait(_handlers,DISPATCH_TIME_NOW)!=0)) {
  noteProblem(@"waitUntilCompleted refused: pending frontend callback on this handler queue");return;
 }
 [self nbWaitForSubmission];
 const uint64_t began=nowUs();
 if(!self.failedLocally && nmb_command_buffer_wait(_handle,0)!=0) {
  // Preserve the runtime's refusal (including a handler waiting for itself).
  // Waiting for the frontend group after that refusal recreates the deadlock.
  noteProblem([@"waitUntilCompleted refused: " stringByAppendingString:lastError()]);
  gTimeWaitCompleted.add(began);return;
 }
 dispatch_group_wait(_handlers,DISPATCH_TIME_FOREVER);
 gTimeWaitCompleted.add(began);
}

- (void)waitUntilScheduled {
 if(!self.committed)return;
 if(nbFrontendHandler && (nbFrontendHandler==self || nbFrontendHandler.queue==self.queue) &&
    (!self.runtimeCommitted || dispatch_group_wait(_schedulingHandlers,DISPATCH_TIME_NOW)!=0)) {
  noteProblem(@"waitUntilScheduled refused: pending callback on this handler queue");return;
 }
 [self nbWaitForSubmission];
 const uint64_t began=nowUs();
 if(!self.failedLocally && !([&] {
 NabuMetalSubmitSpan runtimeWaitTrace(22,23,self.commitIndex,(uint64_t)(uintptr_t)(__bridge void *)self);
  return nmb_command_buffer_wait_scheduled(_handle);
 }())){
  NBLOG(@"native-metal: waitUntilScheduled refused: %@",lastError());return;
 }
 {
 NabuMetalSubmitSpan groupWaitTrace(24,25,self.commitIndex,(uint64_t)(uintptr_t)(__bridge void *)self);
  dispatch_group_wait(_schedulingHandlers,DISPATCH_TIME_FOREVER);
 }
 gTimeWaitScheduled.add(began);
}
- (void)didSchedule {
 NabuMetalSubmitSpan scheduledTrace(26,27,self.commitIndex,(uint64_t)(uintptr_t)(__bridge void *)self);
 {
  const uint64_t took=nowUs()-self.committedUs;
  std::lock_guard<std::mutex> lock(gCommitLock);
  CommitRecord &r=gCommitRing[self.commitIndex%32];
  if(r.index==self.commitIndex)r.scheduledUs=took;
 }
 NSArray *handlers;
 @synchronized(self){
  _schedulingDelivered=YES;handlers=[_scheduledHandlers copy];[_scheduledHandlers removeAllObjects];
 }
 void (^run)(void)=^{
  NBCommandBuffer *previous=nbFrontendHandler;nbFrontendHandler=self;
  @try {for(MTLCommandBufferHandler block in handlers)block((id<MTLCommandBuffer>)self);}
  @finally {nbFrontendHandler=previous;dispatch_group_leave(self->_schedulingHandlers);}
 };
 // Run on the runtime's scheduled-handler thread, preserving its ordering and own-wait
 // deadlock checks. The queue's completionQueue routes completed handlers only.
 run();
}
// Completion releases retained resources and then delivers completed handlers.
// The frontend flushes surfaces only when the driver requires CPU cache operations here.

- (void)finish {
 flushSurfaces(_surfaces);
 // Actual GPU completion (or a local refusal that never submitted) is the
 // release point. A retained completed command must not pin every old frame.
 [_surfaces removeAllObjects];[_resourceOwners removeAllObjects];
 @synchronized(gInFlight){[gInFlight removeObject:self];}
 trimHeldImports(false);

 if(self.failedLocally) {
  std::lock_guard<std::mutex> lock(gRuntimeHandleLock);
  NmbCommandBuffer *handle=_handle;
  _handle=nullptr;
  nmb_command_buffer_release(handle);
 }

 NSArray *completedHandlers;
 @synchronized(self){
  // A frontend refusal or a failed submission never scheduled. Unblock its waiter without inventing a scheduled event.
  if(!_schedulingDelivered){_schedulingDelivered=YES;[_scheduledHandlers removeAllObjects];dispatch_group_leave(_schedulingHandlers);}
  completedHandlers=[_completedHandlers copy];[_completedHandlers removeAllObjects];
 }
 void (^run)(void)=^{
  NBCommandBuffer *previous=nbFrontendHandler;nbFrontendHandler=self;
  @try {for(MTLCommandBufferHandler block in completedHandlers)block((id<MTLCommandBuffer>)self);}
  @finally {nbFrontendHandler=previous;dispatch_group_leave(self->_handlers);}
 };
 dispatch_queue_t queue=_queue.completionQueue;
 if(queue)dispatch_async(queue,run);else run();
}

- (void)addScheduledHandler:(MTLCommandBufferHandler)block {if(block)@synchronized(self){[_scheduledHandlers addObject:[block copy]];}}

- (void)addCompletedHandler:(MTLCommandBufferHandler)block {if(block)@synchronized(self){[_completedHandlers addObject:[block copy]];}}
// A drawable is presented after its command buffer reports successful completion.

- (void)presentDrawable:(id<MTLDrawable>)drawable atTime:(CFTimeInterval)time {
 [self addCompletedHandler:^(id<MTLCommandBuffer> commandBuffer) {
  if(commandBuffer.status==MTLCommandBufferStatusCompleted) {
   nabuCaPresent(drawable,true,time);
  }
 }];
}

@end

static NBCommandBuffer *make(NBQueue *q,unsigned id){NBCommandBuffer*b=[NBCommandBuffer new];b.queue=q;b.handle=new NmbCommandBuffer{id};return b;}
static void complete(NBCommandBuffer *b){NmbCommandBuffer*h=b.handle;if(!b.schedulingDelivered){h->status=MTLCommandBufferStatusScheduled;h->scheduled(h->context);}h->status=MTLCommandBufferStatusCompleted;h->completed(h->context);}
static void await(dispatch_semaphore_t s){assert(dispatch_semaphore_wait(s,dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC))==0);}
int main(){@autoreleasepool{
 gInFlight=[NSMutableSet set];NBQueue*q=[NBQueue new];q.handle=new NmbQueue;
 // Force actual Foundation callback delivery before the C commit call returns.
 // Exercise both inline and a distinct real dispatch thread, with no timing sleeps.
 for(unsigned concurrent=0;concurrent<2;concurrent++)for(unsigned failed=0;failed<2;failed++){
  NBCommandBuffer*early=make(q,100+concurrent*2+failed);NmbCommandBuffer*h=early.handle;
  h->synchronous=true;h->completeInCommit=true;h->concurrent=concurrent;
  h->finalStatus=failed?MTLCommandBufferStatusError:MTLCommandBufferStatusCompleted;
  __block unsigned scheduledCalls=0,completedCalls=0;const unsigned presentBefore=presentations;
  checkStatus(early.status==MTLCommandBufferStatusNotEnqueued,"new command status");
  [early addScheduledHandler:^(id<MTLCommandBuffer> cb){
   scheduledCalls++;
   checkStatus(h->inCommit&&![(NBCommandBuffer*)cb runtimeCommitted],"scheduled before commit returns");
   checkStatus(cb.status==MTLCommandBufferStatusScheduled,"scheduled callback sees Scheduled");
  }];
  [early addCompletedHandler:^(id<MTLCommandBuffer> cb){
   completedCalls++;
   checkStatus(h->inCommit&&![(NBCommandBuffer*)cb runtimeCommitted],"completed before commit returns");
   checkStatus(cb.status==(MTLCommandBufferStatus)h->finalStatus,"completed callback sees actual final status");
  }];
  [early presentDrawable:(id<MTLDrawable>)[NSObject new] atTime:0];
  [early commit];[early waitUntilCompleted];
  checkStatus(scheduledCalls==1&&completedCalls==1,"callbacks exactly once");
  checkStatus(presentations==presentBefore+(!failed),"production presentation gate");
  checkStatus(early.runtimeCommitted,"submission wait publication preserved");
  checkStatus(early.status==(MTLCommandBufferStatus)h->finalStatus,"final status after return");
 }
 submissionOrder.clear();
 // The public enqueue call reserves ordering even when commit calls reverse it.
 NBCommandBuffer*a=make(q,1),*b=make(q,2);[a enqueue];[b commit];assert(submissionOrder.empty());
 assert(a.status==MTLCommandBufferStatusEnqueued&&b.status==MTLCommandBufferStatusCommitted);
 dispatch_semaphore_t waited=dispatch_semaphore_create(0);
 dispatch_async(dispatch_get_global_queue(QOS_CLASS_DEFAULT,0),^{[b waitUntilCompleted];dispatch_semaphore_signal(waited);});
 [a commit];assert((submissionOrder==std::vector<unsigned>{1,2}));complete(a);complete(b);await(waited);
 // Discarding an uncommitted reservation releases the following committed CB.
 NBCommandBuffer*next=make(q,4);__weak NBCommandBuffer*weak;
 @autoreleasepool{NBCommandBuffer*abandoned=make(q,3);weak=abandoned;[abandoned enqueue];[next commit];assert(submissionOrder.back()==2);abandoned=nil;}
 assert(weak==nil&&submissionOrder.back()==4);complete(next);
 // Re-enter commit from a real scheduled callback: no duplicate submission.
 NBCommandBuffer*outer=make(q,5),*inner=make(q,6);outer.handle->synchronous=true;
 [outer addScheduledHandler:^(id<MTLCommandBuffer> cb){[cb waitUntilCompleted];[inner commit];}];
 unsigned before=notes;[outer commit];assert(notes==before+1);
 assert(submissionOrder[submissionOrder.size()-2]==5&&submissionOrder.back()==6);complete(outer);complete(inner);
 // A backend wait refusal must not fall through to an infinite frontend group.
 NBCommandBuffer*refused=make(q,7);[refused commit];refused.handle->waitResult=-1;
 before=notes;[refused waitUntilCompleted];assert(notes==before+1);complete(refused);
 // Same-queue callbacks must not wait for a pending, not-yet-submitted CB.
 NBCommandBuffer*first=make(q,8),*gate=make(q,9),*blocked=make(q,10);
 [first commit];[gate enqueue];[blocked commit];
 [first addCompletedHandler:^(id<MTLCommandBuffer> cb){(void)cb;[blocked waitUntilCompleted];[blocked waitUntilScheduled];}];
 before=notes;complete(first);assert(notes==before+2);[gate commit];complete(gate);complete(blocked);
 // A local submission failure invokes completion and closes both wait groups.
 NBCommandBuffer*failure=make(q,11);failure.handle->commitOK=false;
 dispatch_semaphore_t failed=dispatch_semaphore_create(0);[failure addCompletedHandler:^(id<MTLCommandBuffer> cb){assert(cb.status==MTLCommandBufferStatusError);dispatch_semaphore_signal(failed);}];
 // A resource deallocator may synchronously ask another thread for CB status.
 // The worker-start handshake proves a timeout is on the query, not dispatch setup.
 __block BOOL releaseRan=NO;dispatch_semaphore_t releaseReaderFinished=dispatch_semaphore_create(0);
 releaseHook=^{
  releaseRan=YES;dispatch_semaphore_t started=dispatch_semaphore_create(0),queried=dispatch_semaphore_create(0);
  dispatch_async(dispatch_get_global_queue(QOS_CLASS_DEFAULT,0),^{
   dispatch_semaphore_signal(started);
   checkStatus(next.status==MTLCommandBufferStatusCompleted,"release callback reads another command status");
   dispatch_semaphore_signal(queried);
   dispatch_semaphore_signal(releaseReaderFinished);
  });
  await(started);
  checkStatus(dispatch_semaphore_wait(queried,dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC))==0,"resource release permits synchronous status query");
 };
 [failure commit];await(failed);await(releaseReaderFinished);[failure waitUntilCompleted];[failure waitUntilScheduled];assert(failure.handle==nullptr);
 releaseHook=nil;checkStatus(releaseRan,"failure actually released its runtime handle");
 // ARC ownership: retained resource wrappers survive until actual completion.
 NBCommandBuffer*resources=make(q,12);__weak NSObject*owner;
 @autoreleasepool{NSObject*value=[NSObject new];owner=value;[resources.resourceOwners addObject:value];}
 assert(owner!=nil);[resources commit];complete(resources);assert(owner==nil);
 NBCommandBuffer*unretained=make(q,13);unretained.resourceOwners=[NSHashTable weakObjectsHashTable];
 @autoreleasepool{NSObject*value=[NSObject new];owner=value;[unretained.resourceOwners addObject:value];}
 assert(owner==nil);[unretained commit];complete(unretained);
 // Callback exceptions cannot strand the frontend completion dispatch group.
 NBCommandBuffer*throwing=make(q,14);[throwing addCompletedHandler:^(id<MTLCommandBuffer> cb){(void)cb;@throw [NSException exceptionWithName:@"test" reason:nil userInfo:nil];}];
 [throwing commit];bool caught=false;@try{complete(throwing);}@catch(NSException *e){caught=[e.name isEqualToString:@"test"];}
 assert(caught&&nbFrontendHandler==nullptr);assert(dispatch_group_wait(throwing.handlers,DISPATCH_TIME_NOW)==0);
 assert(gInFlight.count==0);printf("STATUS_RESULT checks=%u failures=%u\n",statusChecks.load(),statusFailures.load());
 if(statusFailures)return 2;
 puts("PASS 13 Foundation queue/callback/ARC cases, including pre-return scheduled/completed statuses and presentation");
}return 0;}
