// SPDX-License-Identifier: MIT
// Every field below comes from the runtime's AIR-derived reflection tree.
@class NBReflectedStruct,NBReflectedArray,NBReflectedPointer,NBReflectedTexture;
static NSDictionary *nbReflectionData(id value) {return [value isKindOfClass:[NSDictionary class]]?value:nil;}
static id nbReflected(Class cls,id data) {
 if(!nbReflectionData(data))return nil;
 id result=[cls new];[result setValue:data forKey:@"nbData"];return result;
}
#define NB_REFLECTION_STORAGE @property(nonatomic,copy) NSDictionary *nbData;
#define NB_NUMBER(TYPE,NAME) - (TYPE)NAME {return (TYPE)[_nbData[@#NAME] unsignedLongLongValue];}
#define NB_BOOL(NAME) - (BOOL)NAME {return [_nbData[@#NAME] boolValue];}
#define NB_CHILD(TYPE,NAME,CLASS) - (TYPE *)NAME {return nbReflected([CLASS class],_nbData[@#NAME]);}
@interface NBReflectedMember : MTLStructMember
NB_REFLECTION_STORAGE
@end
@interface NBReflectedStruct : MTLStructType
NB_REFLECTION_STORAGE
@end
@interface NBReflectedArray : MTLArrayType
NB_REFLECTION_STORAGE
@end
@interface NBReflectedPointer : MTLPointerType
NB_REFLECTION_STORAGE
@end
@interface NBReflectedTexture : MTLTextureReferenceType
NB_REFLECTION_STORAGE
@end
@implementation NBReflectedMember
- (NSString *)name {return _nbData[@"name"];}
NB_NUMBER(NSUInteger,offset)
NB_NUMBER(MTLDataType,dataType)
NB_NUMBER(NSUInteger,argumentIndex)
NB_CHILD(MTLStructType,structType,NBReflectedStruct)
NB_CHILD(MTLArrayType,arrayType,NBReflectedArray)
NB_CHILD(MTLPointerType,pointerType,NBReflectedPointer)
NB_CHILD(MTLTextureReferenceType,textureReferenceType,NBReflectedTexture)
@end
@implementation NBReflectedStruct
- (MTLDataType)dataType {return MTLDataTypeStruct;}
- (NSArray<MTLStructMember *> *)members {
 NSMutableArray *result=[NSMutableArray array];for(NSDictionary *v in _nbData[@"members"])[result addObject:nbReflected([NBReflectedMember class],v)];return [result copy];
}
- (MTLStructMember *)memberByName:(NSString *)name {for(MTLStructMember *v in self.members)if([v.name isEqualToString:name])return v;return nil;}
@end
@implementation NBReflectedArray
- (MTLDataType)dataType {return MTLDataTypeArray;}
NB_NUMBER(MTLDataType,elementType)
NB_NUMBER(NSUInteger,arrayLength)
NB_NUMBER(NSUInteger,stride)
NB_NUMBER(NSUInteger,argumentIndexStride)
NB_CHILD(MTLStructType,elementStructType,NBReflectedStruct)
NB_CHILD(MTLArrayType,elementArrayType,NBReflectedArray)
NB_CHILD(MTLPointerType,elementPointerType,NBReflectedPointer)
NB_CHILD(MTLTextureReferenceType,elementTextureReferenceType,NBReflectedTexture)
@end
@implementation NBReflectedPointer
- (MTLDataType)dataType {return MTLDataTypePointer;}
NB_NUMBER(MTLDataType,elementType)
NB_NUMBER(MTLArgumentAccess,access)
NB_NUMBER(NSUInteger,alignment)
NB_NUMBER(NSUInteger,dataSize)
NB_BOOL(elementIsArgumentBuffer)
NB_CHILD(MTLStructType,elementStructType,NBReflectedStruct)
NB_CHILD(MTLArrayType,elementArrayType,NBReflectedArray)
@end
@implementation NBReflectedTexture
- (MTLDataType)dataType {return MTLDataTypeTexture;}
NB_NUMBER(MTLDataType,textureDataType)
NB_NUMBER(MTLTextureType,textureType)
NB_NUMBER(MTLArgumentAccess,access)
NB_BOOL(isDepthTexture)
@end

@interface NBReflectedArgument : MTLArgument
NB_REFLECTION_STORAGE
@end
@implementation NBReflectedArgument
- (NSString *)name {return _nbData[@"name"];}
NB_NUMBER(MTLArgumentType,type)
NB_NUMBER(MTLArgumentAccess,access)
NB_NUMBER(NSUInteger,index)
- (BOOL)isActive {return [_nbData[@"isUsed"] boolValue];}
NB_BOOL(isUsed)
NB_BOOL(isArgument)
NB_NUMBER(NSUInteger,bufferAlignment)
NB_NUMBER(NSUInteger,bufferDataSize)
NB_NUMBER(MTLDataType,bufferDataType)
NB_CHILD(MTLStructType,bufferStructType,NBReflectedStruct)
NB_CHILD(MTLPointerType,bufferPointerType,NBReflectedPointer)
NB_NUMBER(NSUInteger,threadgroupMemoryAlignment)
NB_NUMBER(NSUInteger,threadgroupMemoryDataSize)
NB_NUMBER(MTLTextureType,textureType)
NB_NUMBER(MTLDataType,textureDataType)
NB_BOOL(isDepthTexture)
NB_NUMBER(NSUInteger,arrayLength)
NB_NUMBER(NSUInteger,objectPayloadAlignment)
NB_NUMBER(NSUInteger,objectPayloadDataSize)

@end
@interface NBReflectedBinding : NSObject
NB_REFLECTION_STORAGE
@property(nonatomic) NmbReflectedBufferBinding *nbBinding;
@end
@implementation NBReflectedBinding
- (void)dealloc {nmb_coverage_buffer_binding_release(_nbBinding);}
- (NSString *)name {return _nbData[@"name"];}
NB_NUMBER(MTLBindingType,type)
NB_NUMBER(MTLArgumentAccess,access)
NB_NUMBER(NSUInteger,index)
- (BOOL)isActive {return [_nbData[@"isUsed"] boolValue];}
NB_BOOL(isUsed)
NB_BOOL(isArgument)
NB_NUMBER(NSUInteger,bufferAlignment)
NB_NUMBER(NSUInteger,bufferDataSize)
NB_NUMBER(MTLDataType,bufferDataType)
NB_CHILD(MTLStructType,bufferStructType,NBReflectedStruct)
NB_CHILD(MTLPointerType,bufferPointerType,NBReflectedPointer)
NB_NUMBER(NSUInteger,threadgroupMemoryAlignment)
NB_NUMBER(NSUInteger,threadgroupMemoryDataSize)
NB_NUMBER(MTLTextureType,textureType)
NB_NUMBER(MTLDataType,textureDataType)
NB_BOOL(isDepthTexture)
NB_NUMBER(NSUInteger,arrayLength)
NB_NUMBER(NSUInteger,objectPayloadAlignment)
NB_NUMBER(NSUInteger,objectPayloadDataSize)

- (BOOL)conformsToProtocol:(Protocol *)protocol {
 if(protocol_isEqual(protocol,@protocol(MTLBinding)))return YES;
 if(protocol_isEqual(protocol,@protocol(MTLBufferBinding)))return self.nbData[@"bufferAlignment"]!=nil;
 if(protocol_isEqual(protocol,@protocol(MTLTextureBinding)))return self.nbData[@"textureType"]!=nil;
 if(protocol_isEqual(protocol,@protocol(MTLThreadgroupBinding)))return self.nbData[@"threadgroupMemoryAlignment"]!=nil;
 if(protocol_isEqual(protocol,@protocol(MTLObjectPayloadBinding)))return self.nbData[@"objectPayloadAlignment"]!=nil;
 return [super conformsToProtocol:protocol];
}
@end

static NSArray *nbReflectedArguments(id data) {
 if(![data isKindOfClass:[NSArray class]])return nil;
 NSMutableArray *result=[NSMutableArray array];for(NSDictionary *v in data)[result addObject:nbReflected([NBReflectedArgument class],v)];return [result copy];
}
static NSArray *nbReflectedBindings(id data,const void *handle,unsigned kind,unsigned stage,NSError **error) {
 if(![data isKindOfClass:[NSArray class]])return nil;
 NSMutableArray *result=[NSMutableArray array];NSUInteger index=0;
 for(NSDictionary *v in data){
  NBReflectedBinding *binding=nbReflected([NBReflectedBinding class],v);
  if([v[@"type"] integerValue]==MTLBindingTypeBuffer){
   binding.nbBinding=nmb_coverage_buffer_binding(handle,kind,stage,index);
   if(!binding.nbBinding){if(error)*error=nbError(lastError());return nil;}
  }
  [result addObject:binding];index++;
 }
 return [result copy];
}
@interface NBComputeReflection : MTLComputePipelineReflection
@property(nonatomic,copy) NSArray *nbBindings,*nbArguments;
@end
@implementation NBComputeReflection
- (NSArray<MTLArgument *> *)arguments {return _nbArguments;}
- (NSArray<id<MTLBinding>> *)bindings {return _nbBindings;}
@end
@interface NBRenderReflection : MTLRenderPipelineReflection
NB_REFLECTION_STORAGE
@property(nonatomic,copy) NSDictionary *nbModern;
@end
@implementation NBRenderReflection
- (NSArray<MTLArgument *> *)vertexArguments {return nbReflectedArguments(_nbData[@"vertex"]);}
- (NSArray<MTLArgument *> *)fragmentArguments {return nbReflectedArguments(_nbData[@"fragment"]);}
- (NSArray<MTLArgument *> *)tileArguments {return nbReflectedArguments(_nbData[@"tile"]);}
- (NSArray<id<MTLBinding>> *)vertexBindings {return _nbModern[@"vertex"];}
- (NSArray<id<MTLBinding>> *)fragmentBindings {return _nbModern[@"fragment"];}
- (NSArray<id<MTLBinding>> *)tileBindings {return _nbModern[@"tile"];}
- (NSArray<id<MTLBinding>> *)objectBindings {return _nbModern[@"object"];}
- (NSArray<id<MTLBinding>> *)meshBindings {return _nbModern[@"mesh"];}
@end
static NSDictionary *nbCoverageReflectionData(const void *handle,unsigned kind,NSError **error) {
 size_t size=nmb_coverage_reflection(handle,kind,nullptr,0);
 if(size==SIZE_MAX){if(error)*error=nbError(lastError());return nil;}
 std::vector<char> data(size+1);
 if(nmb_coverage_reflection(handle,kind,data.data(),data.size())==SIZE_MAX){if(error)*error=nbError(lastError());return nil;}
 return [NSJSONSerialization JSONObjectWithData:[NSData dataWithBytes:data.data() length:size] options:0 error:error];
}
static MTLComputePipelineReflection *nbCoverageComputeReflection(const NmbComputePipeline *handle,NSError **error) {
 NSDictionary *data=nbCoverageReflectionData(handle,0,error);if(!data)return nil;
 NBComputeReflection *result=[NBComputeReflection new];result.nbBindings=nbReflectedBindings(data[@"compute"],handle,0,0,error);
 if(!result.nbBindings)return nil;result.nbArguments=nbReflectedArguments(data[@"compute"]);return result;
}
static MTLRenderPipelineReflection *nbCoverageRenderReflection(const NmbRenderPipeline *handle,NSError **error) {
 NSDictionary *data=nbCoverageReflectionData(handle,1,error);if(!data)return nil;
 NBRenderReflection *result=nbReflected([NBRenderReflection class],data);NSMutableDictionary *modern=[NSMutableDictionary dictionary];
 NSArray *stages=@[@"vertex",@"fragment",@"tile",@"object",@"mesh"];
 for(NSUInteger i=0;i<stages.count;i++){
  NSString *stage=stages[i];NSArray *bindings=nbReflectedBindings(data[stage],handle,1,(unsigned)i,error);
  if(!bindings)return nil;modern[stage]=bindings;
 }
 result.nbModern=modern;return result;
}
#undef NB_REFLECTION_STORAGE
#undef NB_NUMBER
#undef NB_BOOL
#undef NB_CHILD
