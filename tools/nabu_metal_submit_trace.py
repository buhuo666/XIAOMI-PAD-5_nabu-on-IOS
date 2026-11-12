"""Stage bounded commit/scheduled observations on the GPU222 qualified frontend."""
from pathlib import Path
import shutil

INCLUDE = 'NativeMetalSubmitTrace.inc'


def stage_submit_trace(root: Path, metal: Path):
    path = metal / 'NativeBridgeMetalFrontend.mm'
    source = path.read_text(encoding='utf-8')

    def replace(old, new):
        nonlocal source
        if source.count(old) != 1:
            raise ValueError('Qualified submission site changed: ' + old)
        source = source.replace(old, new, 1)

    span = lambda name, begin: (f' NabuMetalSubmitSpan {name}({begin},{begin+1},self.commitIndex,'
                               '(uint64_t)(uintptr_t)(__bridge void *)self);\n')
    replace('#include "NativeMetalCaPresentTrace.inc"',
            '#include "NativeMetalCaPresentTrace.inc"\n#include "' + INCLUDE + '"')
    replace('- (void)didSchedule {\n', '- (void)didSchedule {\n' + span('scheduledTrace', 26))
    replace(' dispatch_group_enter(_handlers);\n', span('commitTrace', 16) + ' dispatch_group_enter(_handlers);\n')
    replace(' if(!self.encodeFailure) {\n  flushSurfaces(_surfaces);',
            ' if(!self.encodeFailure) {\n  {\n' + span('surfaceTrace', 18) +
            '   flushSurfaces(_surfaces);\n  }')
    replace('&& nmb_command_buffer_commit(_handle))return;',
            '&& ([&] {\n' + span('runtimeCommitTrace', 20) +
            '   return nmb_command_buffer_commit(_handle);\n  }()))return;')
    replace('!nmb_command_buffer_wait_scheduled(_handle)',
            '!([&] {\n' + span('runtimeWaitTrace', 22) +
            '  return nmb_command_buffer_wait_scheduled(_handle);\n }())')
    replace(' dispatch_group_wait(_schedulingHandlers,DISPATCH_TIME_FOREVER);',
            ' {\n' + span('groupWaitTrace', 24) +
            '  dispatch_group_wait(_schedulingHandlers,DISPATCH_TIME_FOREVER);\n }')
    path.write_text(source, encoding='utf-8', newline='\n')
    shutil.copyfile(root / 'patches/nabu-metal' / INCLUDE, metal / INCLUDE)
    return dict(event=127, identity='per-process commitIndex, checked with object pointer and lifetime',
                a='stage', b='NBCommandBuffer pointer', c='thread CPU ns; 0 means unavailable',
                stages={16:'commit after publication enter',17:'commit leave',18:'surface flush enter',19:'surface flush leave',
                        20:'runtime commit enter',21:'runtime commit leave',22:'runtime wait scheduled enter',23:'runtime wait scheduled leave',
                        24:'frontend scheduled group wait enter',25:'frontend scheduled group wait leave',
                        26:'scheduled callback enter',27:'scheduled callback leave'},
                enabled_by='NABU_METAL_SUBMIT_TRACE=1 at process launch, or existing native_bridge_metal_set_ca_trace',
                ownership_changed=False)
