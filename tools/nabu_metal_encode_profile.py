"""Stage bounded per-command Metal encoding totals on the qualified GPU230 frontend."""
from pathlib import Path
import shutil

INCLUDE = 'NativeMetalEncodeProfile.inc'
CATEGORIES = ('render_pass_create', 'encoder_end', 'draw', 'resource_bind',
              'pipeline_bind', 'resource_usage', 'compute_dispatch', 'render_state')


def apply_encode_profile(source: str, reverse: bool = False) -> str:
    def replace(old, new):
        nonlocal source
        if reverse:
            old, new = new, old
        if source.count(old) != 1:
            raise ValueError('Qualified Metal encoding site changed: ' + old)
        source = source.replace(old, new, 1)

    replace('static uint64_t nowUs() {return clock_gettime_nsec_np(CLOCK_UPTIME_RAW)/1000;}',
            'static uint64_t nowUs() {return clock_gettime_nsec_np(CLOCK_UPTIME_RAW)/1000;}\n'
            '#include "' + INCLUDE + '"')
    replace(' EncodedWork encodedWork;   // the command buffer\'s single encoder thread, not global counter deltas',
            ' NabuMetalEncodeStats nabuEncodeStats;\n'
            ' EncodedWork encodedWork;   // the command buffer\'s single encoder thread, not global counter deltas')

    def scope(signature, category, command='self.commandBuffer'):
        replace(signature, signature + '\n NabuMetalEncodeScope nabuProfile(' + command +
                '->nabuEncodeStats,NabuEncode' + category + ');')

    scope('- (void)endEncoding {', 'End')
    for signature in (
        '- (void)buffer:(id<MTLBuffer>)buffer offset:(NSUInteger)offset index:(NSUInteger)index stage:(uint32_t)stage {',
        '- (void)texture:(id<MTLTexture>)texture index:(NSUInteger)index stage:(uint32_t)stage {',
        '- (void)sampler:(id<MTLSamplerState>)sampler index:(NSUInteger)index stage:(uint32_t)stage {',
        '- (void)bytes:(const void *)bytes length:(NSUInteger)length index:(NSUInteger)index stage:(uint32_t)stage {',
        '- (void)offset:(NSUInteger)offset index:(NSUInteger)index stage:(uint32_t)stage {',
    ):
        scope(signature, 'Bind')
    for signature in (
        '- (void)fence:(id<MTLFence>)fence stages:(uint64_t)stages update:(bool)update {',
        '- (void)useResources:(const id<MTLResource> __unsafe_unretained [])resources count:(NSUInteger)count usage:(MTLResourceUsage)usage renderStages:(uint64_t)stages {',
        '- (void)barrierResources:(const id<MTLResource> __unsafe_unretained [])resources count:(NSUInteger)count after:(uint64_t)after before:(uint64_t)before {',
        '- (void)memoryBarrierWithScope:(MTLBarrierScope)scope {',
        '- (void)memoryBarrierWithScope:(MTLBarrierScope)scope afterStages:(MTLRenderStages)after beforeStages:(MTLRenderStages)before {',
    ):
        scope(signature, 'Usage')
    for signature in (
        '- (void)setRenderPipelineState:(id<MTLRenderPipelineState>)state {',
        '- (void)setComputePipelineState:(id<MTLComputePipelineState>)state {',
    ):
        scope(signature, 'Pipeline')
    for signature in (
        '- (void)drawPrimitives:(MTLPrimitiveType)t vertexStart:(NSUInteger)s vertexCount:(NSUInteger)n instanceCount:(NSUInteger)i baseInstance:(NSUInteger)b {',
        '                instanceCount:(NSUInteger)i baseVertex:(NSInteger)v baseInstance:(NSUInteger)bi {',
    ):
        scope(signature, 'Draw')
    scope('- (void)dispatch:(MTLSize)size group:(MTLSize)group threads:(bool)threads {', 'Dispatch')
    for signature in (
        '- (void)setDepthStencilState:(id<MTLDepthStencilState>)state {',
        '- (void)setViewport:(MTLViewport)v {',
        '- (void)setScissorRect:(MTLScissorRect)r {',
        '- (void)raster {',
        '- (void)setStencilReferenceValue:(uint32_t)v {',
        '- (void)setStencilFrontReferenceValue:(uint32_t)f backReferenceValue:(uint32_t)b {',
        '- (void)setBlendColorRed:(float)r green:(float)g blue:(float)b alpha:(float)a {',
    ):
        scope(signature, 'State')
    scope('- (id<MTLRenderCommandEncoder>)renderCommandEncoderWithDescriptor:(MTLRenderPassDescriptor *)d {',
          'Pass', 'self')
    replace(' NabuMetalSubmitSpan commitTrace(16,17,self.commitIndex,(uint64_t)(uintptr_t)(__bridge void *)self);',
            ' nabuMetalEncodeProfileEmit(nabuEncodeStats,self.commitIndex,(uint64_t)(uintptr_t)(__bridge void *)self);\n'
            ' NabuMetalSubmitSpan commitTrace(16,17,self.commitIndex,(uint64_t)(uintptr_t)(__bridge void *)self);')
    return source


def stage_encode_profile(root: Path, metal: Path):
    path = metal / 'NativeBridgeMetalFrontend.mm'
    original = path.read_text(encoding='utf-8')
    updated = apply_encode_profile(original)
    if apply_encode_profile(updated, reverse=True) != original:
        raise ValueError('Encoding observation transform did not roundtrip')
    path.write_text(updated, encoding='utf-8', newline='\n')
    shutil.copyfile(root / 'patches/nabu-metal' / INCLUDE, metal / INCLUDE)
    return dict(event=127, categories=list(CATEGORIES),
        enabled_by='NABU_METAL_ENCODE_PROFILE=1 at process launch',
        identity='per-process commitIndex plus unique stage64 NBCommandBuffer pointer; validate publication',
        stages={'64': 'b=command pointer,c=category count',
                '65..72': 'b=wall microseconds,c=thread CPU nanoseconds sum',
                '73..80': 'b=call count,c=maximum call wall microseconds',
                '81..88': 'b=first call begin,c=last call end; mach uptime microseconds',
                '89..96': 'b=encoding thread ID,c=flags:1 mixed threads,2 unavailable CPU'},
        marker_bound_per_command=33, per_call_kernel_markers=False,
        limits='Clock reads and relaxed atomic counters add observation overhead. Category scopes do not nest. '
               'Only same-thread calls contained in the exact CA render interval qualify as that render CPU. '
               'No GPU synchronization, resource retention, API result or shader-cache identity changed.')
