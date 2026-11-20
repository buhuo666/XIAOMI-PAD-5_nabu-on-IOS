"""Fail a utrace sample safely when its GPU buffer cannot be allocated."""
import difflib
import json
from pathlib import Path
import shutil

PATCH = "nabu-turnip-trace-allocation-failure.patch"
FILES = {"u_trace.c":"src/util/perf/u_trace.c", "u_trace.h":"src/util/perf/u_trace.h",
         "tu_device.cc":"src/freedreno/vulkan/tu_device.cc"}
FAILURE_HELPERS = r'''
/* GPU trace allocation failure invalidates this sample, not the rendering CS.
 * Keep existing valid buffers until the usual submission wait and cleanup. */
static void
u_trace_allocation_failed(struct u_trace *ut, uint32_t size)
{
   if (!ut->allocation_failed)
      fprintf(stderr, "NABU_UTRACE_ALLOCATION_FAILED context=%p trace=%p bytes=%u capture_invalid=1\n",
              (void *)ut->utctx, (void *)ut, size);
   ut->allocation_failed = true;
}

static bool
u_trace_discard_failed_flush(struct u_trace *ut, void *flush_data)
{
   if (!ut->allocation_failed)
      return false;

   struct util_dynarray *timestamps = &ut->buffers[u_trace_buffer_list_timestamps];
   if (util_dynarray_num_elements(timestamps, struct u_trace_buffer)) {
      struct u_trace_buffer *buffer = util_dynarray_element(timestamps, struct u_trace_buffer, 0);
      /* Offset zero invokes the driver's submission wait before cleanup even
       * when failure happened after writing a timestamp but before an event
       * could be appended. Do not publish partial ranges or timestamps. */
      ut->utctx->read_timestamp(ut->utctx, buffer->buffer, 0, 0, flush_data);
   }
   return true;
}
'''

CHANGES = [
("u_trace.h", "   struct u_trace_buffer_view last_timestamp;",
 "   struct u_trace_buffer_view last_timestamp;\n   bool allocation_failed; /* reset with this trace; never store an invalid GPU buffer */"),
("u_trace.c", "static char *\nprint_time(void *ctx, double time_ns)",
 FAILURE_HELPERS + "\nstatic char *\nprint_time(void *ctx, double time_ns)"),
("u_trace.c", "   struct u_trace_context *utctx = ut->utctx;\n\n   if (flush->frame_nr",
 "   struct u_trace_context *utctx = ut->utctx;\n\n   if (u_trace_discard_failed_flush(ut, flush->flush_data))\n      return;\n\n   if (flush->frame_nr"),
("u_trace.c", "   struct util_dynarray *list = &ut->buffers[list_index];\n\n   size = align(size, 8);",
 "   struct util_dynarray *list = &ut->buffers[list_index];\n\n   if (ut->allocation_failed)\n      return (struct u_trace_buffer_view){ .buffer_index = UINT32_MAX };\n\n   size = align(size, 8);"),
("u_trace.c", "   util_dynarray_append(list, new_buffer);",
 "   if (!new_buffer.buffer) {\n      u_trace_allocation_failed(ut, alloc_size);\n      return (struct u_trace_buffer_view){ .buffer_index = UINT32_MAX };\n   }\n\n   util_dynarray_append(list, new_buffer);"),
("u_trace.c", "   struct u_trace *from = begin_it.ut;\n\n   if (u_trace_iterator_equal",
 "   struct u_trace *from = begin_it.ut;\n\n   if (from->allocation_failed) {\n      u_trace_allocation_failed(into, 0);\n      return;\n   }\n   if (into->allocation_failed)\n      return;\n\n   if (u_trace_iterator_equal"),
("u_trace.c", "         dst_timestamp = alloc_device_memory(into, u_trace_buffer_list_timestamps, src_buffer->size);",
 "         dst_timestamp = alloc_device_memory(into, u_trace_buffer_list_timestamps, src_buffer->size);\n         if (dst_timestamp.buffer_index == UINT32_MAX)\n            return;"),
("u_trace.c", "         dst_indirect = alloc_device_memory(into, u_trace_buffer_list_indirect, src_buffer->size);",
 "         dst_indirect = alloc_device_memory(into, u_trace_buffer_list_indirect, src_buffer->size);\n         if (dst_indirect.buffer_index == UINT32_MAX)\n            return;"),
("u_trace.c", "   event->payload_size = payload_sz;\n\n   struct u_trace_buffer_view dst_timestamp",
 "   event->payload_size = payload_sz;\n\n   /* Generated tracepoints fill this payload unconditionally. Preserve that\n    * CPU storage while dropping the failed GPU sample. */\n   if (ut->allocation_failed)\n      return event->payload;\n\n   struct u_trace_buffer_view dst_timestamp"),
("u_trace.c", "      alloc_device_memory(ut, u_trace_buffer_list_timestamps, ut->utctx->timestamp_size_bytes);\n   void *dst_timestamp_buffer",
 "      alloc_device_memory(ut, u_trace_buffer_list_timestamps, ut->utctx->timestamp_size_bytes);\n   if (dst_timestamp.buffer_index == UINT32_MAX)\n      return event->payload;\n   void *dst_timestamp_buffer"),
("u_trace.c", "         alloc_device_memory(ut, u_trace_buffer_list_indirect, ut->utctx->max_indirect_size_bytes);\n      void *dst_indirect_buffer",
 "         alloc_device_memory(ut, u_trace_buffer_list_indirect, ut->utctx->max_indirect_size_bytes);\n      if (dst_indirect.buffer_index == UINT32_MAX)\n         return event->payload;\n      void *dst_indirect_buffer"),
("tu_device.cc", "      tu_bo_suballocator_init(device->trace_suballoc, device, 512 * 1024,",
 "      if (!device->trace_suballoc) {\n         mtx_unlock(&device->trace_mutex);\n         return NULL;\n      }\n\n      tu_bo_suballocator_init(device->trace_suballoc, device, 512 * 1024,"),
("tu_device.cc", "   VkResult result =\n      tu_suballoc_bo_alloc(suballoc_bo, device->trace_suballoc, size_B, 1);",
 "   if (!suballoc_bo) {\n      mtx_unlock(&device->trace_mutex);\n      return NULL;\n   }\n\n   VkResult result =\n      tu_suballoc_bo_alloc(suballoc_bo, device->trace_suballoc, size_B, 1);"),
("tu_device.cc", "   return result == VK_SUCCESS ? suballoc_bo : NULL;",
 "   if (result != VK_SUCCESS) {\n      vk_free(&device->vk.alloc, suballoc_bo);\n      return NULL;\n   }\n   return suballoc_bo;"),
]

def transform(sources, reverse=False):
    result = dict(sources)
    for filename, before, after in (reversed(CHANGES) if reverse else CHANGES):
        if reverse:
            before, after = after, before
        if result[filename].count(before) != 1:
            raise ValueError("Pinned utrace allocation site changed: " + filename + " " + before[:90])
        result[filename] = result[filename].replace(before, after, 1)
    return result

def patch_text(sources):
    changed = transform(sources)
    return "".join("".join(difflib.unified_diff(sources[name].splitlines(True), changed[name].splitlines(True),
                                               fromfile="a/"+path, tofile="b/"+path))
                   for name,path in FILES.items())

def stage_trace_allocation_failure(root:Path, work:Path):
    relative = "patches/mesa/"+PATCH
    shutil.copyfile(root/"patches/nabu-vulkan"/PATCH, work/relative)
    path = work/"scripts/data/adreno-compiler-inputs.json"
    pins = json.loads(path.read_text(encoding="utf-8"))
    pins["patches"].append(relative)
    path.write_text(json.dumps(pins,indent=2)+"\n",encoding="utf-8",newline="\n")
    return dict(patch=relative, scope="GPU trace allocation error handling and cleanup",
                gpu_rendering_commands_changed=False, successful_capture_changed=False,
                tracepoints_disabled=False, invalid_capture_marker="NABU_UTRACE_ALLOCATION_FAILED")
