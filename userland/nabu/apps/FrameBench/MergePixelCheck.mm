#import "MergePixelCheck.h"
#include <algorithm>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <vector>

namespace {
constexpr NSUInteger Width = 1600, Height = 2560, RowBytes = Width * 4;
struct Parameters { uint32_t frame, layer, width, height; float seconds; };
}

NSDictionary *NabuCheckMergedPixels(id<MTLDevice> device, id<MTLCommandQueue> queue,
                                    id<MTLRenderPipelineState> opaque,
                                    id<MTLRenderPipelineState> blend,
                                    id<MTLRenderPipelineState> merged,
                                    NSURL *documents) {
    MTLTextureDescriptor *descriptor = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm
                                     width:Width height:Height mipmapped:NO];
    descriptor.storageMode = MTLStorageModeShared;
    descriptor.usage = MTLTextureUsageRenderTarget;
    id<MTLTexture> baseline = [device newTextureWithDescriptor:descriptor];
    id<MTLTexture> candidate = [device newTextureWithDescriptor:descriptor];
    NSMutableArray *cases = [NSMutableArray array];
    NSString *error = nil;
    uint64_t totalPixels = 0, totalDifferent = 0, alphaErrors = 0, barcodeErrors = 0;
    unsigned maximum = 0;
    std::vector<uint8_t> left(RowBytes * Height), right(RowBytes * Height);
    const std::array<float, 4> phases{0.0f, 0.5f, 1.0f / 0.35f, 60.0f};
    const std::array<uint32_t, 4> frames{0u, 1u, 0x55aau, 0xffffffffu};
    if (!baseline || !candidate) error = @"无法创建原生尺寸校验纹理";
    for (NSUInteger index = 0; !error && index < phases.size(); ++index) {
        id<MTLCommandBuffer> command = [queue commandBuffer];
        if (!command) { error = @"无法创建校验命令缓冲"; break; }
        for (unsigned variant = 0; variant < 2; ++variant) {
            MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
            pass.colorAttachments[0].texture = variant ? candidate : baseline;
            pass.colorAttachments[0].loadAction = MTLLoadActionDontCare;
            pass.colorAttachments[0].storeAction = MTLStoreActionStore;
            id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass];
            if (!encoder) { error = @"无法创建校验编码器"; break; }
            Parameters p{frames[index], 0, uint32_t(Width), uint32_t(Height), phases[index]};
            for (unsigned layer = 0; layer < (variant ? 1u : 8u); ++layer) {
                p.layer = layer;
                [encoder setRenderPipelineState:variant ? merged : layer ? blend : opaque];
                [encoder setFragmentBytes:&p length:sizeof(p) atIndex:0];
                [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
            }
            [encoder endEncoding];
        }
        if (error) break;
        [command commit]; [command waitUntilCompleted];
        if (command.status != MTLCommandBufferStatusCompleted) {
            error = command.error.localizedDescription ?: @"图像校验命令未完成"; break;
        }
        MTLRegion region = MTLRegionMake2D(0, 0, Width, Height);
        [baseline getBytes:left.data() bytesPerRow:RowBytes fromRegion:region mipmapLevel:0];
        [candidate getBytes:right.data() bytesPerRow:RowBytes fromRegion:region mipmapLevel:0];
        std::array<uint64_t, 256> histogram{};
        uint64_t different = 0, alpha = 0, barcode = 0;
        unsigned caseMaximum = 0;
        for (NSUInteger pixel = 0; pixel < Width * Height; ++pixel) {
            unsigned delta = 0;
            for (unsigned channel = 0; channel < 3; ++channel)
                delta = std::max(delta, unsigned(std::abs(int(left[pixel * 4 + channel]) - int(right[pixel * 4 + channel]))));
            ++histogram[delta]; different += delta != 0; caseMaximum = std::max(caseMaximum, delta);
            alpha += left[pixel * 4 + 3] != 255 || right[pixel * 4 + 3] != 255;
            if (pixel / Width < 64) {
                const unsigned bit = std::min(unsigned((float(pixel % Width) + 0.5f) * 16.0f / float(Width)), 15u);
                const uint8_t expected = (frames[index] >> bit) & 1 ? 255 : 0;
                for (unsigned channel = 0; channel < 3; ++channel)
                    barcode += left[pixel * 4 + channel] != expected || right[pixel * 4 + channel] != expected;
            }
        }
        NSString *baseName = [NSString stringWithFormat:@"merge-pixels-%lu-baseline.bgra", (unsigned long)index];
        NSString *mergedName = [NSString stringWithFormat:@"merge-pixels-%lu-merged.bgra", (unsigned long)index];
        NSError *writeError = nil;
        if (![[NSData dataWithBytes:left.data() length:left.size()] writeToURL:[documents URLByAppendingPathComponent:baseName]
                        options:NSDataWritingAtomic error:&writeError] ||
            ![[NSData dataWithBytes:right.data() length:right.size()] writeToURL:[documents URLByAppendingPathComponent:mergedName]
                        options:NSDataWritingAtomic error:&writeError]) {
            error = writeError.localizedDescription ?: @"无法保存校验图像"; break;
        }
        NSMutableArray *bins = [NSMutableArray array];
        for (unsigned delta = 0; delta < histogram.size(); ++delta)
            if (histogram[delta]) [bins addObject:@{@"maximum_rgb_delta": @(delta), @"pixels": @(histogram[delta])}];
        [cases addObject:@{@"case": @(index), @"frame": @(frames[index]), @"seconds": @(phases[index]),
            @"pixels": @(Width * Height), @"different_rgb_pixels": @(different), @"maximum_rgb_delta": @(caseMaximum),
            @"alpha_errors": @(alpha), @"barcode_channel_errors": @(barcode), @"histogram": bins,
            @"baseline_raw": baseName, @"merged_raw": mergedName, @"command_status": @(command.status)}];
        totalPixels += Width * Height; totalDifferent += different; alphaErrors += alpha; barcodeErrors += barcode;
        maximum = std::max(maximum, caseMaximum);
    }
    const bool complete = cases.count == phases.size() && !error;
    NSDictionary *report = @{@"test": @"merged_alpha_native_bgra8", @"schema_version": @1,
        @"width": @(Width), @"height": @(Height), @"bytes_per_row": @(RowBytes), @"pixel_format": @"BGRA8Unorm",
        @"complete": @(complete), @"byte_exact": @(complete && !totalDifferent && !alphaErrors && !barcodeErrors),
        @"error": error ?: @"", @"pixels": @(totalPixels), @"different_rgb_pixels": @(totalDifferent),
        @"maximum_rgb_delta": @(maximum), @"alpha_errors": @(alphaErrors), @"barcode_channel_errors": @(barcodeErrors),
        @"cases": cases, @"scope": @"Independent GPU offscreen readbacks of eight fixed-function blends and one merged draw; no performance timing or display claim"};
    NSData *json = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:nil];
    [json writeToURL:[documents URLByAppendingPathComponent:@"merge-pixel-check.json"] options:NSDataWritingAtomic error:nil];
    return report;
}
