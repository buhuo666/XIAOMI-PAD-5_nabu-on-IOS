"""Stage precise runtime submission spans and the frontend-to-runtime identity edge."""
from pathlib import Path
import shutil

PATCH = '0031-nabu-runtime-submit-spans.patch'


def stage_runtime_trace(root: Path, metal: Path):
    directory = metal/'bridge/patches'
    shutil.copyfile(root/'patches/nabu-metal'/PATCH,directory/PATCH)
    series=directory/'series'
    series.write_text(series.read_text().rstrip('\n')+'\n'+PATCH+'\n',encoding='utf-8',newline='\n')

    def replace(path,old,new):
        source=path.read_text(encoding='utf-8')
        if source.count(old)!=1:
            raise ValueError('Qualified runtime trace site changed: '+old)
        path.write_text(source.replace(old,new,1),encoding='utf-8',newline='\n')

    replace(metal/'bridge/NativeMetalObjects.h',
        'bool nmb_command_buffer_commit(NmbCommandBuffer *);',
        'uint64_t nmb_command_buffer_trace_identity(const NmbCommandBuffer *);\n'
        'bool nmb_command_buffer_commit(NmbCommandBuffer *);')
    replace(metal/'bridge/NativeMetalObjects.rs',
        '#[unsafe(no_mangle)]\npub extern "C" fn nmb_command_buffer_commit(',
        '#[unsafe(no_mangle)]\npub extern "C" fn nmb_command_buffer_trace_identity(command_buffer: *const NmbCommandBuffer) -> u64 {\n'
        '    guard(0, || Ok(get(command_buffer)?.0.nabu_trace_identity()))\n}\n\n'
        '#[unsafe(no_mangle)]\npub extern "C" fn nmb_command_buffer_commit(')
    replace(metal/'NativeBridgeMetalFrontend.mm',
        ' NabuMetalSubmitSpan commitTrace(16,17,self.commitIndex,(uint64_t)(uintptr_t)(__bridge void *)self);',
        ' if(nabuMetalSubmitTraceEnabled()) {\n'
        '  const int saved=errno;\n'
        '  const uint64_t runtime=nmb_command_buffer_trace_identity(_handle);\n'
        '  nabu_ca_trace_marker(127,self.commitIndex,30,(uint64_t)(uintptr_t)(__bridge void *)self,runtime);\n'
        '  errno=saved;\n'
        ' }\n'
        ' NabuMetalSubmitSpan commitTrace(16,17,self.commitIndex,(uint64_t)(uintptr_t)(__bridge void *)self);')
    return dict(runtime_patch=PATCH,event=127,
        identity_edge=dict(stage=30,identity='frontend commitIndex',b='NBCommandBuffer pointer',c='live runtime Arc pointer'),
        runtime_identity='CommandBufferShared Arc address within its frontend commit lifetime; not a kernel completion ID',
        stages={32:'submit_batch enter',33:'submit_batch leave',34:'first_submission enter',35:'first_submission leave',
                36:'tracker plan enter',37:'tracker plan leave',38:'prepare submit buffers enter',39:'prepare submit buffers leave',
                40:'group submit enter',41:'group submit leave',42:'scheduler commit enter',43:'scheduler commit leave'},
        b='batch index, except 42/43 logical queue ID',c='thread CPU ns; 0 unavailable',
        enabled_by='NABU_METAL_SUBMIT_TRACE=1 at process launch',changes_submission_semantics=False)
