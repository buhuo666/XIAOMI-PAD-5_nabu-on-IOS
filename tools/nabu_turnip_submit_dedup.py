"""Stage exact raw-range deduplication and bounded Turnip submission observations."""
import json
from pathlib import Path
import shutil

PATCH='nabu-turnip-submit-range-dedup.patch'
SOURCE_PATCH='turnip-submit-range-dedup.patch'

DEDUP_SOURCE=r'''
/* Exact source ranges can recur in several CS/descriptor-set records. Remove
 * duplicates while the existing BO retirement lock protects resolution. Do not
 * merge adjacent/overlapping IOVAs here: they may belong to different BOs. The
 * native same-handle/access overlap merge remains after reference acquisition. */
static int
darwin_raw_range_compare(const void *left, const void *right)
{
   const struct tu_resource_range *a = (const struct tu_resource_range *)left;
   const struct tu_resource_range *b = (const struct tu_resource_range *)right;
   if (a->iova != b->iova)
      return a->iova < b->iova ? -1 : 1;
   if (a->size != b->size)
      return a->size < b->size ? -1 : 1;
   return a->access < b->access ? -1 : a->access > b->access;
}

static uint32_t
darwin_deduplicate_submit_ranges(struct tu_darwin_queue_submit *submit)
{
   const uint32_t count = util_dynarray_num_elements(&submit->ranges, struct tu_resource_range);
   if (count < 2)
      return count;
   struct tu_resource_range *ranges = (struct tu_resource_range *)submit->ranges.data;
   qsort(ranges, count, sizeof(*ranges), darwin_raw_range_compare);
   uint32_t unique = 1;
   for (uint32_t at = 1; at < count; at++) {
      const struct tu_resource_range *previous = &ranges[unique - 1];
      if (previous->iova == ranges[at].iova && previous->size == ranges[at].size &&
          previous->access == ranges[at].access)
         continue;
      ranges[unique++] = ranges[at];
   }
   submit->ranges.size = unique * sizeof(*ranges);
   return unique;
}
'''

TRACE_SOURCE=r'''
/* Same optional project marker ABI as CA/runtime event127. The kernel stores
 * only an explicitly opened window. No identity survives this submit object. */
static bool
nabuTurnipSubmitTraceEnabled()
{
   const int saved = errno;
   static const bool enabled = [] {
      const char *value = getenv("NABU_METAL_SUBMIT_TRACE");
      return value && value[0] == '1' && value[1] == '\0';
   }();
   errno = saved;
   return enabled;
}

static void
nabuTurnipSubmitMarker(uint64_t identity, uint64_t stage, uint64_t b, uint64_t c)
{
   const int saved = errno;
   if (nabuTurnipSubmitTraceEnabled()) {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
      (void)syscall(179, UINT64_C(0x31ca81fc), identity, stage, b, c);
#pragma clang diagnostic pop
   }
   errno = saved;
}

class NabuTurnipSubmitSpan {
   bool enabled;
   uint64_t identity, end, argument;
   void mark(uint64_t stage) const {
      const int saved = errno;
      struct timespec cpu = {};
      const uint64_t ns = clock_gettime(CLOCK_THREAD_CPUTIME_ID, &cpu) == 0 ?
         (uint64_t)cpu.tv_sec * UINT64_C(1000000000) + cpu.tv_nsec : 0;
      nabuTurnipSubmitMarker(identity, stage, argument, ns);
      errno = saved;
   }
public:
   NabuTurnipSubmitSpan(uint64_t begin, uint64_t end_stage, const void *object, uint64_t b)
      : enabled(nabuTurnipSubmitTraceEnabled()), identity((uintptr_t)object), end(end_stage), argument(b) {
      if (enabled) mark(begin);
   }
   ~NabuTurnipSubmitSpan() { if (enabled) mark(end); }
   NabuTurnipSubmitSpan(const NabuTurnipSubmitSpan &) = delete;
   NabuTurnipSubmitSpan &operator=(const NabuTurnipSubmitSpan &) = delete;
};
'''


def apply_range_dedup(source: str,reverse: bool=False) -> str:
    def replace(old,new):
        nonlocal source
        if reverse:
            old,new=new,old
        if source.count(old)!=1:
            raise ValueError('Qualified Turnip submission site changed: '+old)
        source=source.replace(old,new,1)
    replace('#include <unistd.h>','#include <unistd.h>\n#include <time.h>')
    replace("/* 'NTNL':",TRACE_SOURCE+"\n/* 'NTNL':")
    replace('static VkResult\ndarwin_collect_submit_resources(',DEDUP_SOURCE+'\nstatic VkResult\ndarwin_collect_submit_resources(')
    replace('   struct darwin_retire_state *retire = (struct darwin_retire_state *)dev->darwin_retire;\n   uint16_t object_indices[DARWIN_NATIVE_BO_LIMIT + 1] = {};',
        '   NabuTurnipSubmitSpan nabu_collect(44, 45, submit, 0);\n'
        '   struct darwin_retire_state *retire = (struct darwin_retire_state *)dev->darwin_retire;\n'
        '   uint16_t object_indices[DARWIN_NATIVE_BO_LIMIT + 1] = {};')
    replace('   VkResult result = VK_SUCCESS;\n   pthread_mutex_lock(&retire->lock);\n   util_dynarray_foreach (&submit->ranges, struct tu_resource_range, range) {',
        '   VkResult result = VK_SUCCESS;\n'
        '   const uint32_t raw_ranges = util_dynarray_num_elements(&submit->ranges, struct tu_resource_range);\n'
        '   pthread_mutex_lock(&retire->lock);\n'
        '   const uint32_t unique_ranges = darwin_deduplicate_submit_ranges(submit);\n'
        '   util_dynarray_foreach (&submit->ranges, struct tu_resource_range, range) {')
    replace('   pthread_mutex_unlock(&retire->lock);\n   if (result != VK_SUCCESS)\n      return result;\n\n   NativeAdrenoAbiSubmitResourceV2 *ranges =',
        '   pthread_mutex_unlock(&retire->lock);\n'
        '   nabuTurnipSubmitMarker((uintptr_t)submit, 49, raw_ranges, unique_ranges);\n'
        '   if (result != VK_SUCCESS)\n      return result;\n\n   NativeAdrenoAbiSubmitResourceV2 *ranges =')
    old='''      const kern_return_t status = IOConnectCallStructMethod(dw.conn,
         dw.tunnel ? dw.selector : method,
         dw.tunnel ? (void *)packet : (void *)(packet + 8), bytes + (dw.tunnel ? 8 : 0),
         &reply, &output_size);'''
    new='''      const kern_return_t status = [&] {
         NabuTurnipSubmitSpan nabu_call(46, 47, submit, queue->msm_queue_id);
         return IOConnectCallStructMethod(dw.conn,
            dw.tunnel ? dw.selector : method,
            dw.tunnel ? (void *)packet : (void *)(packet + 8), bytes + (dw.tunnel ? 8 : 0),
            &reply, &output_size);
      }();
      nabuTurnipSubmitMarker((uintptr_t)submit, 50, (uint32_t)status, output_size);'''
    replace(old,new)
    replace('            *fence = reply.fence;',
        '            *fence = reply.fence;\n'
        '            nabuTurnipSubmitMarker((uintptr_t)submit, 48, reply.fence, queue->msm_queue_id);')
    return source


def stage_submit_range_dedup(root: Path,work: Path):
    root,work=Path(root),Path(work)
    rel='patches/mesa/'+PATCH
    shutil.copyfile(root/'patches/nabu-vulkan'/SOURCE_PATCH,work/rel)
    path=work/'scripts/data/adreno-compiler-inputs.json'
    pins=json.loads(path.read_text())
    if rel in pins['patches']:
        raise ValueError('Turnip range dedup patch already staged')
    pins['patches'].append(rel)
    path.write_text(json.dumps(pins,indent=2)+'\n',encoding='utf-8',newline='\n')
    return dict(patch=rel,source='src/freedreno/vulkan/tu_knl_darwin.cc',
        exact_raw_range_dedup=True,merge_key=['iova','size','access'],
        bounds='one submission only, under existing retirement lock before BO lookup; native overlap merge unchanged',
        trace_environment='NABU_METAL_SUBMIT_TRACE=1',event=127,
        spans={44:'collect enter',45:'collect leave',46:'native IOKit submit enter',47:'native IOKit submit leave'},
        span_identity='live tu_darwin_queue_submit pointer; link only within same PID/thread containing runtime group submit',
        span_b='logical queue ID for46/47, zero for44/45',span_c='thread CPU ns',
        metadata={48:'b=validated successful completion,c=logical queue',49:'b=raw ranges including IB,c=unique exact triples',50:'b=IOKit status,c=reply output size'})
