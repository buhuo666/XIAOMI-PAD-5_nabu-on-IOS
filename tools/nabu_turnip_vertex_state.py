"""Coalesce vertex bindings and reuse unchanged draw-state command blocks."""
import difflib
import json
from pathlib import Path
import shutil

PATCH='nabu-turnip-vertex-state-reuse.patch'
FILES=('tu_cmd_buffer.cc','tu_cmd_buffer.h','tu_darwin_trace.cc','tu_darwin_trace.h')

def function(source,name):
    at=source.index('\n'+name+'(')
    begin=source.rfind('\n',0,at)+1
    opening=source.index('{',begin);depth=0
    for end in range(opening,len(source)):
        depth+=(source[end]=='{')-(source[end]=='}')
        if not depth:return source[begin:end+1]
    raise ValueError(name)

def transform(sources):
    out=dict(sources)
    old=function(out['tu_cmd_buffer.cc'],'tu_CmdBindVertexBuffers2')
    new='''VKAPI_ATTR void VKAPI_CALL
tu_CmdBindVertexBuffers2(VkCommandBuffer commandBuffer,
                         uint32_t firstBinding,
                         uint32_t bindingCount,
                         const VkBuffer *pBuffers,
                         const VkDeviceSize *pOffsets,
                         const VkDeviceSize *pSizes,
                         const VkDeviceSize *pStrides)
{
   VK_FROM_HANDLE(tu_cmd_buffer, cmd, commandBuffer);
   const uint32_t max_vbs = MAX2(cmd->state.max_vbs_bound,
                                firstBinding + bindingCount);
   bool changed = max_vbs != cmd->state.max_vbs_bound;
   cmd->state.max_vbs_bound = max_vbs;
   cmd->state.vertex_bind_calls++;
   cmd->state.vertex_state_baseline_dwords += 4 * max_vbs;

   if (pStrides) {
      vk_cmd_set_vertex_binding_strides(&cmd->vk, firstBinding, bindingCount,
                                        pStrides);
   }

   for (uint32_t i = 0; i < bindingCount; i++) {
      uint64_t base = 0;
      uint32_t size = 0;
      if (pBuffers[i] != VK_NULL_HANDLE) {
         struct tu_buffer *buf = tu_buffer_from_handle(pBuffers[i]);
         tu_cmd_use_buffer(cmd, buf, TU_RESOURCE_READ);
         base = vk_buffer_address(&buf->vk, pOffsets[i]);
         size = vk_buffer_range(&buf->vk, pOffsets[i],
                                pSizes ? pSizes[i] : VK_WHOLE_SIZE);
      }
      auto &vb = cmd->state.vb[firstBinding + i];
      changed |= vb.base != base || vb.size != size;
      vb.base = base;
      vb.size = size;
   }

   if (changed)
      cmd->state.dirty |= TU_CMD_DIRTY_VERTEX_BUFFERS;
   else
      cmd->state.vertex_bind_reuses++;
}

/* Bind calls only update the final vertex inputs. Build one state block at
 * the next draw; an identical rebind keeps the previously recorded block.
 * Full draw-state restoration still binds that block after clears/secondaries.
 */
static void
tu_emit_vertex_buffer_state(struct tu_cmd_buffer *cmd)
{
   struct tu_cs cs;
   cmd->state.vertex_buffers.size = 4 * cmd->state.max_vbs_bound;
   cmd->state.vertex_buffers.iova =
      tu_cs_draw_state(&cmd->sub_cs, &cs, cmd->state.vertex_buffers.size).iova;
   for (uint32_t i = 0; i < cmd->state.max_vbs_bound; i++) {
      tu_cs_emit_regs(&cs,
                      A6XX_VFD_VERTEX_BUFFER_BASE(i, .qword = cmd->state.vb[i].base),
                      A6XX_VFD_VERTEX_BUFFER_SIZE(i, cmd->state.vb[i].size));
   }
   cmd->state.vertex_state_builds++;
   cmd->state.vertex_state_emitted_dwords += cmd->state.vertex_buffers.size;
}'''
    out['tu_cmd_buffer.cc']=out['tu_cmd_buffer.cc'].replace(old,new,1)
    anchor='   /* Early exit if there is nothing to emit, saves CPU cycles */\n'
    assert out['tu_cmd_buffer.cc'].count(anchor)==1
    out['tu_cmd_buffer.cc']=out['tu_cmd_buffer.cc'].replace(anchor,
        '   if (cmd->state.dirty & TU_CMD_DIRTY_VERTEX_BUFFERS)\n'
        '      tu_emit_vertex_buffer_state(cmd);\n\n'+anchor)
    anchor='   tu_cmd_record_result(cmd_buffer);\n   return vk_command_buffer_end(&cmd_buffer->vk);'
    assert out['tu_cmd_buffer.cc'].count(anchor)==1
    out['tu_cmd_buffer.cc']=out['tu_cmd_buffer.cc'].replace(anchor,
        '   tu_darwin_trace_vertex_state(cmd_buffer);\n'+anchor)
    anchor='   uint32_t max_vbs_bound;'
    assert out['tu_cmd_buffer.h'].count(anchor)==1
    out['tu_cmd_buffer.h']=out['tu_cmd_buffer.h'].replace(anchor,anchor+'''
   uint64_t vertex_bind_calls, vertex_bind_reuses, vertex_state_builds;
   uint64_t vertex_state_baseline_dwords, vertex_state_emitted_dwords;''')
    anchor='void tu_darwin_trace_draw_state(struct tu_cmd_buffer *cmd);'
    out['tu_darwin_trace.h']=out['tu_darwin_trace.h'].replace(anchor,
        'void tu_darwin_trace_vertex_state(struct tu_cmd_buffer *cmd);\n'+anchor)
    anchor='static inline void tu_darwin_trace_draw_state(struct tu_cmd_buffer *) {}'
    out['tu_darwin_trace.h']=out['tu_darwin_trace.h'].replace(anchor,
        'static inline void tu_darwin_trace_vertex_state(struct tu_cmd_buffer *) {}\n'+anchor)
    anchor='void\ntu_darwin_trace_execute('
    assert out['tu_darwin_trace.cc'].count(anchor)==1
    code='''void
tu_darwin_trace_vertex_state(struct tu_cmd_buffer *cmd)
{
   tu_darwin_trace_state *state = trace_state(cmd->device);
   if (!state || !cmd->darwin_trace_generation)
      return;
   NativeAdrenoTraceEvent event = trace_cpu_event(state, 51, "vertex_buffer_state");
   event.command_buffer_id = cmd->darwin_trace_id;
   trace_argument(&event, 0, cmd->state.vertex_bind_calls);
   trace_argument(&event, 1, cmd->state.vertex_bind_reuses);
   trace_argument(&event, 2, cmd->state.vertex_state_builds);
   trace_argument(&event, 3, cmd->state.vertex_state_baseline_dwords -
                             cmd->state.vertex_state_emitted_dwords);
   trace_append(state, cmd->darwin_trace_generation, event);
}

'''
    out['tu_darwin_trace.cc']=out['tu_darwin_trace.cc'].replace(anchor,code+anchor)
    return out

def patch_text(before,after):
    text=''
    for name in FILES:
        path='src/freedreno/vulkan/'+name
        text+='diff --git a/'+path+' b/'+path+'\n'
        text+=''.join(difflib.unified_diff(before[name].splitlines(True),after[name].splitlines(True),
            fromfile='a/'+path,tofile='b/'+path))
    return text

def stage_vertex_state(root:Path,work:Path):
    relative='patches/mesa/'+PATCH
    shutil.copyfile(root/'patches/nabu-vulkan'/PATCH,work/relative)
    path=work/'scripts/data/adreno-compiler-inputs.json'
    pins=json.loads(path.read_text());pins['patches'].append(relative)
    path.write_text(json.dumps(pins,indent=2)+'\n',newline='\n')
    return dict(patch=relative,scope='coalesce vertex input state creation and reuse identical bindings',
        rendering_command_encoding_changed=True,attachment_actions_changed=False,lrz_policy_changed=False,
        per_command_summary='vertex_buffer_state: calls, identical rebinds, state builds, elided setup dwords',
        limitation='Elided command dwords are not measured GPU time; real workload benefit is measured separately.')
