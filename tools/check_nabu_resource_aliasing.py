#!/usr/bin/env python3
"""Exercise the production ObjC resource dispatch against the observed 20F66 rules.

Uses real Objective-C message dispatch and the unchanged production include, with
recording C ABI doubles. It checks forwarding, parent preservation and refusal
logging; it does not execute Rust, Vulkan, heap allocation or the Apple runtime.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from build_nabu_gpu_metal_probe import stage_system_resource_aliasing, stage_system_shader_compatibility
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cassert>
#include <cstddef>
#include <cstdio>
typedef signed char BOOL;
#define YES ((BOOL)1)
#define NO ((BOOL)0)
#define nil ((id)0)
extern "C" id class_createInstance(Class, size_t);
extern "C" id object_dispose(id);
struct NmbBuffer {bool answer, success; unsigned made, queried;};
struct NmbTexture {bool answer, success; unsigned made, queried;};
#include "NativeMetalResourceAliasing.h"
extern "C" bool nmb_buffer_make_aliasable(const NmbBuffer *p) {
 auto &h=*const_cast<NmbBuffer *>(p); ++h.made; return h.success;
}
extern "C" bool nmb_buffer_is_aliasable(const NmbBuffer *p) {
 auto &h=*const_cast<NmbBuffer *>(p); ++h.queried; return h.answer;
}
extern "C" bool nmb_texture_make_aliasable(const NmbTexture *p) {
 auto &h=*const_cast<NmbTexture *>(p); ++h.made; return h.success;
}
extern "C" bool nmb_texture_is_aliasable(const NmbTexture *p) {
 auto &h=*const_cast<NmbTexture *>(p); ++h.queried; return h.answer;
}
__attribute__((objc_root_class))
@interface NBObject {Class isa;}
+ (id)new;
@end
@implementation NBObject
+ (id)new {return class_createInstance(self,0);}
@end
@interface NBBuffer : NBObject {@public NmbBuffer *_handle;}
@end
@implementation NBBuffer
@end
@interface NBTexture : NBObject {
 @public NmbTexture *_handle;
 NBBuffer *_buffer;
 id _parent;
}
@end
@implementation NBTexture
@end
static unsigned refusals;
#define NBLOG(...) (++refusals)
#include "NativeMetalResourceAliasing.inc"

int main() {
 unsigned cases=0;
 NBBuffer *buffer=[NBBuffer new];
 NBTexture *parent=[NBTexture new], *texture=[NBTexture new];
 for(unsigned present=0;present<4;++present) {
  for(unsigned answers=0;answers<8;++answers) {
   for(unsigned success=0;success<2;++success) {
    NmbBuffer backing{bool(answers&1),bool(success),0,0};
    NmbTexture ancestor{bool(answers&2),bool(success),0,0};
    NmbTexture own{bool(answers&4),bool(success),0,0};
    buffer->_handle=&backing;parent->_handle=&ancestor;
    texture->_handle=&own;
    texture->_buffer=(present&1)?buffer:nil;
    texture->_parent=(present&2)?parent:nil;
    // Independent truth table from the original 20F66 instructions:
    // buffer wins the query; then parent; otherwise own. Any parent means
    // makeAliasable must leave both the parent and child storage untouched.
    const bool answersByRoute[4]={own.answer,backing.answer,ancestor.answer,backing.answer};
    const unsigned ownCallsByRoute[4]={1,0,0,0};
    refusals=0;
    assert(bool([texture isAliasable])==answersByRoute[present]);
    assert(backing.queried==((present&1)?1U:0U));
    assert(ancestor.queried==(present==2?1U:0U));
    assert(own.queried==ownCallsByRoute[present]);
    [texture makeAliasable];
    assert(own.made==ownCallsByRoute[present]);
    assert(backing.made==0 && ancestor.made==0);
    assert(refusals==(present==0 && !success?1U:0U));
    ++cases;
   }
  }
 }
 for(unsigned answer=0;answer<2;++answer) {
  for(unsigned success=0;success<2;++success) {
   NmbBuffer own{bool(answer),bool(success),0,0};buffer->_handle=&own;refusals=0;
   assert(bool([buffer isAliasable])==bool(answer));
   [buffer makeAliasable];
   assert(own.queried==1 && own.made==1 && refusals==unsigned(!success));
   ++cases;
  }
 }
 object_dispose(texture);object_dispose(parent);object_dispose(buffer);
 printf("%u production Objective-C dispatch cases passed\n",cases);
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frontend-source', type=Path, default=ROOT / 'src/AdrenoMetal')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    staged = output / 'staged'
    (staged / 'bridge').mkdir(parents=True)
    for name in ('NativeBridgeMetalFrontend.mm', 'bridge/NativeMetalObjects.rs'):
        shutil.copyfile(args.frontend_source / name, staged / name)
    stage_system_shader_compatibility(staged)
    stage_system_resource_aliasing(ROOT, staged)
    frontend = (staged / 'NativeBridgeMetalFrontend.mm').read_text()
    assert 'case 51:return 3;' in frontend and 'pipelineLibrary:(id)pipelineLibrary error:' in frontend
    assert '- (BOOL)isAliasable {return NO;}' not in frontend
    assert frontend.count('#include "NativeMetalResourceAliasing.inc"') == 1
    assert (staged / 'bridge/NativeMetalObjects.rs').read_text().count('include!("NativeMetalResourceAliasing.rs");') == 1
    harness = output / 'resource-alias-dispatch.mm'
    harness.write_text(HARNESS, encoding='utf-8', newline='\n')
    binary = output / 'resource-alias-dispatch'
    command = ['clang++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
               '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
               '-I', host_path(staged), host_path(harness), '-o', host_path(binary)]
    command += ['-lobjc'] if sys.platform == 'darwin' else ['-fobjc-runtime=gcc', '-l:libobjc.so.4']
    result = subprocess.run(host_command(command), capture_output=True)
    (output / 'compile.log').write_bytes(result.stdout + result.stderr)
    result.check_returncode()
    # The process-global Objective-C class registry lives until exit. Its retained
    # allocations are outside this test; address/UB checks remain enabled.
    result = subprocess.run(host_command(['env', 'ASAN_OPTIONS=detect_leaks=0', host_path(binary)]), capture_output=True)
    (output / 'run.log').write_bytes(result.stdout + result.stderr)
    result.check_returncode()
    report = dict(result='pass', dispatch_cases=68,
                  production_staging='tools/build_nabu_gpu_metal_probe.py:stage_system_resource_aliasing',
                  production_include='patches/nabu-metal/NativeMetalResourceAliasing.inc',
                  production_objc_messages_executed=True, c_abi_recording_doubles=True,
                  buffer_queries_and_mutations_forwarded=True, texture_buffer_precedes_parent=True,
                  texture_children_preserve_parent_storage=True, refusal_logging_observed=True,
                  shader_fixes_preserved=True, sanitizers=['address', 'undefined'],
                  original_20f66_methods={'texture_makeAliasable':'0x181aae9b0', 'texture_isAliasable':'0x181aae968',
                      'resource_makeAliasable':'0x181ac7010', 'resource_isAliasable':'0x181ac6ff4'},
                  rust_executed=False, apple_runtime_executed=False, gpu_executed=False,
                  limitations='Recording C ABI doubles validate the real Objective-C forwarding only. Rust compilation, heap reuse and GPU execution require the native build and device test.')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
