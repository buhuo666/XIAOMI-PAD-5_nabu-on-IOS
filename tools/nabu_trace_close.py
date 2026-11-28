"""Serialize the final trace queue check and producer closure with appends."""
import json,shutil
from pathlib import Path
PATCH='nabu-turnip-trace-close.patch'
OLD='''   trace_send(state);

   pthread_mutex_lock(&state->mutex);
   NativeAdrenoTraceProducer producer = state->producer;
   producer.dropped = state->dropped;
   pthread_mutex_unlock(&state->mutex);
   if (!tu_darwin_trace_call(state->device, NativeAdrenoMethodEndTraceProducer,
                             &producer, sizeof(producer), NULL, 0)) {
      pthread_mutex_lock(&state->mutex);
      state->producer = {};
      pthread_cond_broadcast(&state->changed);
      pthread_mutex_unlock(&state->mutex);
   }
'''
NEW='''   /* Appends can finish after the last send even with no pending GPU work.
    * Drain them before sealing. The empty check, file footer and producer
    * removal share the append mutex, so no record can become orphaned between
    * the last drain and removal. The file transport does not re-enter it. */
   for (;;) {
      trace_send(state);
      pthread_mutex_lock(&state->mutex);
      if (state->queues[TRACE_GPU_QUEUE].count || state->queues[TRACE_METADATA_QUEUE].count) {
         pthread_mutex_unlock(&state->mutex);
         continue;
      }
      NativeAdrenoTraceProducer producer = state->producer;
      producer.dropped = state->dropped;
      if (!tu_darwin_trace_call(state->device, NativeAdrenoMethodEndTraceProducer,
                                &producer, sizeof(producer), NULL, 0)) {
         state->producer = {};
         pthread_cond_broadcast(&state->changed);
      }
      pthread_mutex_unlock(&state->mutex);
      return;
   }
'''
def transform(source,reverse=False):
    old,new=(NEW,OLD) if reverse else (OLD,NEW)
    if source.count(old)!=1:raise ValueError('Qualified trace close block differs')
    return source.replace(old,new,1)
def stage(root:Path,work:Path):
    relative='patches/mesa/'+PATCH
    shutil.copyfile(root/'patches/nabu-vulkan'/PATCH,work/relative)
    p=work/'scripts/data/adreno-compiler-inputs.json';pins=json.loads(p.read_text())
    assert relative not in pins['patches'];pins['patches'].append(relative)
    p.write_text(json.dumps(pins,indent=2)+'\n',encoding='utf8',newline='\n')
    return dict(patch=relative,scope='Trace producer final drain and close only',trace_abi_unchanged=True)
