// SPDX-License-Identifier: MIT
#include <metal_stdlib>
using namespace metal;

struct SurfaceVertex {
    float4 position [[position]];
};

vertex SurfaceVertex nabu_surface_vertex(device const float2 *positions [[buffer(0)]],
                                        uint index [[vertex_id]]) {
    return {float4(positions[index], 0.0f, 1.0f)};
}

fragment float4 nabu_surface_sample(SurfaceVertex input [[stage_in]],
                                   texture2d<float> source [[texture(0)]]) {
    constexpr sampler nearest(coord::normalized, address::clamp_to_edge, filter::nearest);
    const float2 size = float2(source.get_width(), source.get_height());
    return source.sample(nearest, input.position.xy / size);
}

fragment float4 nabu_surface_color(constant float4 &color [[buffer(0)]]) {
    return color;
}
