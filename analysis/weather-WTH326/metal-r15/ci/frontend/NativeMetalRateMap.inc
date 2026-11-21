// SPDX-License-Identifier: MIT
#include "NativeMetalRateMap.h"
@interface NBRateMap : NBObject <MTLRasterizationRateMap>
@property(nonatomic) NmbRateMap *handle;
@end
@implementation NBRateMap
- (id<MTLDevice>)device {return (id<MTLDevice>)gDeviceObject;}
- (void)dealloc {nmb_rate_map_release(_handle);}
- (MTLSize)mapSize:(uint32_t)kind layer:(NSUInteger)layer {
 uint64_t value[3]={};
 if(!nmb_rate_map_query(_handle,kind,layer,value))
  [NSException raise:NSInvalidArgumentException format:@"rasterization rate map query: %@",lastError()];
 return MTLSizeMake(value[0],value[1],value[2]);
}
- (MTLSize)screenSize {return [self mapSize:0 layer:0];}
- (MTLSize)physicalGranularity {return [self mapSize:1 layer:0];}
- (NSUInteger)layerCount {return [self mapSize:2 layer:0].width;}
- (MTLSizeAndAlign)parameterBufferSizeAndAlign {MTLSize s=[self mapSize:3 layer:0];return {s.width,s.height};}
- (MTLSize)physicalSizeForLayer:(NSUInteger)layer {return [self mapSize:4 layer:layer];}
- (MTLCoordinate2D)mapCoordinates:(MTLCoordinate2D)point layer:(NSUInteger)layer toPhysical:(BOOL)physical {
 const float input[2]={point.x,point.y};float output[2]={};
 if(!nmb_rate_map_coordinates(_handle,physical,input,layer,output))
  [NSException raise:NSInvalidArgumentException format:@"rasterization rate coordinates: %@",lastError()];
 return {output[0],output[1]};
}
- (MTLCoordinate2D)mapScreenToPhysicalCoordinates:(MTLCoordinate2D)point forLayer:(NSUInteger)layer {
 return [self mapCoordinates:point layer:layer toPhysical:YES];
}
- (MTLCoordinate2D)mapPhysicalToScreenCoordinates:(MTLCoordinate2D)point forLayer:(NSUInteger)layer {
 return [self mapCoordinates:point layer:layer toPhysical:NO];
}
- (void)copyParameterDataToBuffer:(id<MTLBuffer>)buffer offset:(NSUInteger)offset {
 if(![(id)buffer isKindOfClass:[NBBuffer class]] || !nmb_rate_map_copy(_handle,[(NBBuffer *)buffer handle],offset))
  [NSException raise:NSInvalidArgumentException format:@"rasterization rate parameter buffer: %@",lastError()];
}
@end

static id<MTLRasterizationRateMap> nabuCreateRateMap(MTLRasterizationRateMapDescriptor *d) {
 if(!d)return nil;
 std::vector<NmbRateLayer> layers;
 for(NSUInteger i=0;i<d.layerCount;++i) {
  MTLRasterizationRateLayerDescriptor *layer=d.layers[i];
  layers.push_back({layer.horizontalSampleStorage,layer.verticalSampleStorage,
                   layer.sampleCount.width,layer.sampleCount.height});
 }
 NmbRateMap *handle=nmb_rate_map_new(gDevice,d.screenSize.width,d.screenSize.height,
                                  layers.data(),layers.size(),d.label.UTF8String);
 if(!handle){NBLOG(@"native-metal: rasterization rate map: %@",lastError());return nil;}
 NBRateMap *map=[NBRateMap new];map.handle=handle;map.label=d.label;return map;
}
