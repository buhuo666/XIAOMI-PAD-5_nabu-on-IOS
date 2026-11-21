// SPDX-License-Identifier: MIT
- (void)bindVisibleTables:(const id<MTLVisibleFunctionTable> __unsafe_unretained [])tables range:(NSRange)r stage:(unsigned)stage {
 std::vector<NmbVisibleTable *> handles;
 for(NSUInteger i=0;i<r.length;i++) {
  id table=tables[i];if(table && ![table isKindOfClass:[NBRenderVisibleTable class]]) {
   [self.commandBuffer refuse:@"foreign visible function table"];return;
  }
  handles.push_back([(NBRenderVisibleTable *)table handle]);
 }
 if([self check:nmb_render_bind_tables(self.handle,stage,handles.data(),handles.size(),r.location) what:"setVisibleFunctionTables"])
  for(NSUInteger i=0;i<r.length;i++)if(tables[i])[self.commandBuffer.resourceOwners addObject:tables[i]];
}
- (void)setVertexVisibleFunctionTable:(id<MTLVisibleFunctionTable>)table atBufferIndex:(NSUInteger)i {
 __unsafe_unretained id<MTLVisibleFunctionTable> tables[]={table};[self bindVisibleTables:tables range:NSMakeRange(i,1) stage:1];
}
- (void)setFragmentVisibleFunctionTable:(id<MTLVisibleFunctionTable>)table atBufferIndex:(NSUInteger)i {
 __unsafe_unretained id<MTLVisibleFunctionTable> tables[]={table};[self bindVisibleTables:tables range:NSMakeRange(i,1) stage:2];
}
- (void)setVertexVisibleFunctionTables:(const id<MTLVisibleFunctionTable> __unsafe_unretained [])tables withBufferRange:(NSRange)r {
 [self bindVisibleTables:tables range:r stage:1];
}
- (void)setFragmentVisibleFunctionTables:(const id<MTLVisibleFunctionTable> __unsafe_unretained [])tables withBufferRange:(NSRange)r {
 [self bindVisibleTables:tables range:r stage:2];
}
