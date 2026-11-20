"""Measure render-pass cache flushes using the render-pass timestamp stream."""
import json
from pathlib import Path
import shutil

PATCH='nabu-turnip-renderpass-flush-profile.patch'
CHANGES=(
 ('   const bool trace_flush = flushes && cs == &cmd_buffer->cs;',
  '   const bool trace_flush = flushes &&\n'
  '      (cs == &cmd_buffer->cs || cs == &cmd_buffer->draw_cs);\n'
  '   struct u_trace *flush_trace = cs == &cmd_buffer->draw_cs ?\n'
  '      &cmd_buffer->rp_trace : &cmd_buffer->trace;'),
 ('      trace_start_cache_flush(&cmd_buffer->trace, cs, cmd_buffer, flushes);',
  '      trace_start_cache_flush(flush_trace, cs, cmd_buffer, flushes);'),
 ('      trace_end_cache_flush(&cmd_buffer->trace, cs);',
  '      trace_end_cache_flush(flush_trace, cs);'),
)


def transform(source,reverse=False):
    for before,after in CHANGES:
        if reverse:before,after=after,before
        if source.count(before)!=1:raise ValueError('Qualified flush trace site changed: '+before)
        source=source.replace(before,after,1)
    return source


def stage_full_gpu_profile(root:Path,work:Path):
    relative='patches/mesa/'+PATCH
    shutil.copyfile(root/'patches/nabu-vulkan'/PATCH,work/relative)
    path=work/'scripts/data/adreno-compiler-inputs.json'
    pins=json.loads(path.read_text(encoding='utf8'))
    pins['patches'].append(relative)
    path.write_text(json.dumps(pins,indent=2)+'\n',encoding='utf8',newline='\n')
    return dict(patch=relative,scope='main CS and render-pass CS cache flush timestamp boundaries',
                command_logic_unchanged=True,disabled_adds_gpu_packets=False,
                enabled_adds_timestamp_packets=True,
                limitations='Timing includes pipeline drain/backpressure and profiling overhead. '
                'This does not isolate every firmware stall or every instruction-level synchronization.')
