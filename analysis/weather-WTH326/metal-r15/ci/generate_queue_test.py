"""Extract production queue/CB methods into a real Foundation/dispatch harness.

The C backend is deliberately deterministic: these tests exercise frontend
ordering, ARC ownership and callback waits, not GPU completion correctness.
Run generated .mm on macOS with clang++ -std=c++17 -fobjc-arc -fblocks
-framework Foundation -framework Metal -Wall -Wextra -Werror.
"""
import pathlib,re,sys
source=pathlib.Path(sys.argv[1]).read_text(encoding='utf-8-sig')
out=pathlib.Path(sys.argv[2])
def methods(cls,names):
    body=source.split('@implementation '+cls+'\n',1)[1].split('\n@end',1)[0]
    starts=list(re.finditer(r'^- \([^\n]+',body,re.M))
    found={}
    for i,m in enumerate(starts):
        name=re.match(r'- \([^)]*\)(\w+)',m[0])[1]
        if name in names:found[name]=body[m.start():starts[i+1].start() if i+1<len(starts) else len(body)]
    assert set(found)==set(names),(cls,set(names)-set(found))
    return '\n'.join(found[n] for n in names)
queue=methods('NBQueue',['init','nbEnqueue','nbCommit','nbDiscardEntry','nbDrain','dealloc'])
command=methods('NBCommandBuffer',['init','dealloc','refuse','status','enqueue','nbWaitForSubmission','commit','nbSubmitNow','waitUntilCompleted','waitUntilScheduled','didSchedule','finish','addScheduledHandler','addCompletedHandler'])
prefix=r'''
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
struct NmbCommandBuffer {unsigned id;int status=0,waitResult=0;bool commitOK=true,synchronous=false;
 void (*scheduled)(void*)=nullptr;void (*completed)(void*)=nullptr;void *context=nullptr;};
static std::vector<unsigned> submissionOrder;
static void nmb_queue_release(NmbQueue *p){delete p;}
static void nmb_command_buffer_release(NmbCommandBuffer *p){delete p;}
static uint64_t nmb_command_buffer_trace_identity(NmbCommandBuffer *p){return p->id;}
static int nmb_command_buffer_status(NmbCommandBuffer *p){return p->status;}
static bool nmb_command_buffer_on_completed(NmbCommandBuffer *p,void (*fn)(void*),void *context){p->completed=fn;p->context=context;return true;}
static bool nmb_command_buffer_on_scheduled(NmbCommandBuffer *p,void (*fn)(void*),void *context){p->scheduled=fn;p->context=context;return true;}
static bool nmb_command_buffer_commit(NmbCommandBuffer *p){
 if(!p->commitOK)return false;submissionOrder.push_back(p->id);p->status=MTLCommandBufferStatusCommitted;
 if(p->synchronous){p->status=MTLCommandBufferStatusScheduled;p->scheduled(p->context);}return true;
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
@end
static thread_local NBCommandBuffer *__unsafe_unretained nbFrontendHandler=nullptr;
static void scheduled(void *context){[(__bridge NBCommandBuffer*)context didSchedule];}
static void completed(void *context){NBCommandBuffer *b=(__bridge_transfer NBCommandBuffer*)context;[b finish];}
'''
tests=r'''
static NBCommandBuffer *make(NBQueue *q,unsigned id){NBCommandBuffer*b=[NBCommandBuffer new];b.queue=q;b.handle=new NmbCommandBuffer{id};return b;}
static void complete(NBCommandBuffer *b){NmbCommandBuffer*h=b.handle;if(!b.schedulingDelivered)h->scheduled(h->context);h->status=MTLCommandBufferStatusCompleted;h->completed(h->context);}
static void await(dispatch_semaphore_t s){assert(dispatch_semaphore_wait(s,dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC))==0);}
int main(){@autoreleasepool{
 gInFlight=[NSMutableSet set];NBQueue*q=[NBQueue new];q.handle=new NmbQueue;
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
 [failure commit];await(failed);[failure waitUntilCompleted];[failure waitUntilScheduled];assert(failure.handle==nullptr);
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
 assert(gInFlight.count==0);puts("PASS 9 Foundation queue/callback/ARC behavior cases");
}return 0;}
'''
out.write_text(prefix+'\n@implementation NBQueue\n'+queue+'\n@end\n@implementation NBCommandBuffer\n'+command+'\n@end\n'+tests)
print(out)
