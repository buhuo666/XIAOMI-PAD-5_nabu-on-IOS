// SPDX-License-Identifier: MIT
#include "NativeMetalResourceAliasing.h"

@implementation NBBuffer (NabuResourceAliasing)
- (void)makeAliasable {
 if(!nmb_buffer_make_aliasable(_handle))NBLOG(@"native-metal: buffer makeAliasable refused: %@",lastError());
}
- (BOOL)isAliasable {return nmb_buffer_is_aliasable(_handle);}
@end

@implementation NBTexture (NabuResourceAliasing)
- (void)makeAliasable {
 // 20F66 MTLIOAccelTexture at 0x181aae9b0: a buffer texture or view does not unpin
 // its parent. Only its isAliasable query is delegated to that parent.
 if(_buffer || _parent)return;
 if(!nmb_texture_make_aliasable(_handle))NBLOG(@"native-metal: texture makeAliasable refused: %@",lastError());
}
- (BOOL)isAliasable {
 if(_buffer)return [_buffer isAliasable];
 if(_parent)return [_parent isAliasable];
 return nmb_texture_is_aliasable(_handle);
}
@end
