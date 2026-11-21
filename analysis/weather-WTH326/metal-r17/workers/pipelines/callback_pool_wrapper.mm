// Full frontend translation unit; only the Rust C backend is deterministic.
#include "NativeBridgeMetalFrontend.mm"
#include <thread>
#include <condition_variable>
#include <cassert>
extern "C" void nabu_test_autoreleased_owner(id);
static std::atomic<unsigned> testTextureReleased{0},testCallbacks{0};
static std::atomic<uint64_t> testStatus{MTLCommandBufferStatusScheduled};
static __weak NBTexture *testWeakTexture;
extern "C" void nmb_command_buffer_release(NmbCommandBuffer *){}
extern "C" void nmb_queue_release(NmbQueue *){}
extern "C" void nmb_event_release(NmbEvent *){}
extern "C" void nmb_texture_release(NmbTexture *p){if(p)testTextureReleased++;}
extern "C" void nmb_buffer_release(NmbBuffer *){}
extern "C" uint64_t nmb_command_buffer_status(const NmbCommandBuffer *) {return testStatus;}
extern "C" int nmb_command_buffer_wait(NmbCommandBuffer *,uint64_t){return 0;}
extern "C" bool nmb_command_buffer_wait_scheduled(NmbCommandBuffer *){return true;}
extern "C" void sys_dcache_flush(void *,size_t){}

static void makeTemporary() {
 NBTexture *texture=[NBTexture new];texture.handle=(NmbTexture *)0x1234;
 testWeakTexture=texture;
 nabu_test_autoreleased_owner(texture);
 testCallbacks++;
}
static void waitSignal(dispatch_semaphore_t semaphore) {
 assert(dispatch_semaphore_wait(semaphore,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC))==0);
}
static NBCommandBuffer *makeCommand(NBQueue *queue) {
 NBCommandBuffer *command=[NBCommandBuffer new];command.queue=queue;
 command.committed=YES;command.runtimeCommitted=YES;command.handle=(NmbCommandBuffer *)0x1000;
 command.committedUs=nowUs();command.commitIndex=1;
 dispatch_group_enter(command.handlers);dispatch_group_enter(command.schedulingHandlers);
 @synchronized(gInFlight){[gInFlight addObject:command];}
 return command;
}
extern "C" int nabu_test_callback_pool(const char *kind) {
 gDeviceHostCoherent=true;gInFlight=[NSMutableSet set];
 NBQueue *queue=[NBQueue new];NBCommandBuffer *command=makeCommand(queue);
 NBQueue *otherQueue=[NBQueue new];NBCommandBuffer *other=makeCommand(otherQueue);
 // A separate completed queue permits a real cross-queue wait from each callback.
 other.schedulingDelivered=YES;dispatch_group_leave(other.schedulingHandlers);
 dispatch_group_leave(other.handlers);other.failedLocally=YES;
 @synchronized(gInFlight){[gInFlight removeObject:other];}
 bool completedCase=!strcmp(kind,"completed");
 bool scheduledCase=!strcmp(kind,"scheduled");
 bool dispatchCase=!strcmp(kind,"dispatch");
 bool releaseCase=!strcmp(kind,"deallocator");
 bool eventCase=!strcmp(kind,"event");
 if(!(completedCase||scheduledCase||dispatchCase||releaseCase||eventCase))return 64;
 dispatch_semaphore_t ran=dispatch_semaphore_create(0),leave=dispatch_semaphore_create(0);
 dispatch_semaphore_t queueBlocked=dispatch_semaphore_create(0);
 dispatch_queue_t target=nullptr;
 if(dispatchCase||eventCase) {
  // NEVER requests no libdispatch-managed autorelease boundary, deliberately.
  auto attr=dispatch_queue_attr_make_with_autorelease_frequency(DISPATCH_QUEUE_SERIAL,DISPATCH_AUTORELEASE_FREQUENCY_NEVER);
  target=dispatch_queue_create("nabu.pool.test",attr);
  if(dispatchCase)queue.completionQueue=target;
 }
 void (^consumer)(void)=^{
  [other waitUntilCompleted]; // same implementation, distinct finished queue
  [command waitUntilCompleted]; // own-handler wait must remain rejected, not deadlock
  makeTemporary();
 };
 if(scheduledCase)[command addScheduledHandler:^(id<MTLCommandBuffer>){consumer();}];
 if(completedCase||dispatchCase)[command addCompletedHandler:^(id<MTLCommandBuffer>){consumer();}];
 std::thread worker([&] {
  // No outer pool, matching std::thread-based Rust contexts workers.
  if(scheduledCase)scheduled((__bridge void *)command);
  if(completedCase||dispatchCase) {
   command.schedulingDelivered=YES;dispatch_group_leave(command.schedulingHandlers);
   testStatus=MTLCommandBufferStatusCompleted;
   completed((__bridge_retained void *)command);
  }
  if(releaseCase) {
   void (^deallocator)(void*,NSUInteger)=^(void*,NSUInteger){makeTemporary();};
   releaseBlock((__bridge_retained void *)deallocator,nullptr,0);
  }
  if(eventCase) {
   NBSharedEvent *event=[NBSharedEvent new];
   MTLSharedEventNotificationBlock block=^(id<MTLSharedEvent>,uint64_t){makeTemporary();};
   NSArray *job=@[event,target,[block copy]];
   notified((__bridge_retained void *)job,7);
  }
  if(dispatchCase||eventCase) {
   dispatch_async(target,^{dispatch_semaphore_signal(ran);waitSignal(queueBlocked);});
  } else dispatch_semaphore_signal(ran);
  waitSignal(leave); // Observe while the native callback worker remains alive.
 });
 waitSignal(ran);
 const bool alive=testWeakTexture!=nil;
 const unsigned released=testTextureReleased.load(),callbacks=testCallbacks.load();
 printf("POOL_RESULT case=%s callbacks=%u alive_before_thread_exit=%u releases_before_thread_exit=%u\n",kind,callbacks,unsigned(alive),released);
 dispatch_semaphore_signal(queueBlocked);dispatch_semaphore_signal(leave);worker.join();
 // No claim about actual GPU backing: the stub measures NBTexture's C release.
 return callbacks==1?0:2;
}
