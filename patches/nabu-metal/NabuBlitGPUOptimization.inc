// This bridge has one texture representation. Runtime accesses already manage
// Vulkan image transitions, so there is no separate CPU layout to convert here.
// Retain the texture and its normal IOSurface synchronization through the command.
- (void)optimizeContentsForGPUAccess:(id<MTLTexture>)texture {
 (void)[self textures:NB_OBJECTS(texture) count:1];
}
