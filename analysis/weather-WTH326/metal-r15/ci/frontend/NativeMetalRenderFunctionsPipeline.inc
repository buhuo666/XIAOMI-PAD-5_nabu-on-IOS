// SPDX-License-Identifier: MIT
- (id<MTLFunctionHandle>)functionHandleWithFunction:(id<MTLFunction>)f stage:(MTLRenderStages)stage {
 if(![(id)f isKindOfClass:[NBFunction class]])return nil;
 auto handle=nmb_render_function_handle(_handle,[(NBFunction *)f handle],stage);
 if(!handle)return nil;
 NBRenderFunctionHandle *result=[NBRenderFunctionHandle new];result.handle=handle;
 result.name=f.name;result.functionType=f.functionType;return (id<MTLFunctionHandle>)result;
}
- (id<MTLVisibleFunctionTable>)newVisibleFunctionTableWithDescriptor:(MTLVisibleFunctionTableDescriptor *)descriptor stage:(MTLRenderStages)stage {
 auto handle=nmb_render_visible_table(_handle,descriptor.functionCount,stage);
 if(!handle)return nil;
 NBRenderVisibleTable *result=[NBRenderVisibleTable new];result.handle=handle;return (id<MTLVisibleFunctionTable>)result;
}
