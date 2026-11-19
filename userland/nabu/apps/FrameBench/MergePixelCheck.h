#import <Metal/Metal.h>
#import <Foundation/Foundation.h>

NSDictionary *NabuCheckMergedPixels(id<MTLDevice> device, id<MTLCommandQueue> queue,
                                    id<MTLRenderPipelineState> opaque,
                                    id<MTLRenderPipelineState> blend,
                                    id<MTLRenderPipelineState> merged,
                                    NSURL *documents);
