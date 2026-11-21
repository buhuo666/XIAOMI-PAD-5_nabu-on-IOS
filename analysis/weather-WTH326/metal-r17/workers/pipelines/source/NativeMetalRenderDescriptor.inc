// SPDX-License-Identifier: MIT
static NmbRenderPipelineExtra renderExtraDescriptor(MTLRenderPipelineDescriptor *d) {
 return {(uint64_t)d.maxVertexAmplificationCount,(uint64_t)d.maxTessellationFactor,
  (uint64_t)d.tessellationPartitionMode,(uint64_t)d.tessellationFactorFormat,
  (uint64_t)d.tessellationFactorStepFunction,(uint64_t)d.tessellationOutputWindingOrder,
  (uint64_t)d.tessellationControlPointIndexType,(uint64_t)d.isTessellationFactorScaleEnabled,
  (uint64_t)d.supportIndirectCommandBuffers};
}
