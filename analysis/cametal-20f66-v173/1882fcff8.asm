00000001882fcff8: sub       sp, sp, #0xa0
00000001882fcffc: stp       x28, x27, [sp, #0x40]
00000001882fd000: stp       x26, x25, [sp, #0x50]
00000001882fd004: stp       x24, x23, [sp, #0x60]
00000001882fd008: stp       x22, x21, [sp, #0x70]
00000001882fd00c: stp       x20, x19, [sp, #0x80]
00000001882fd010: stp       x29, x30, [sp, #0x90]
00000001882fd014: add       x29, sp, #0x90
00000001882fd018: mov       x22, x3
00000001882fd01c: mov       x21, x1
00000001882fd020: mov       x19, x0
00000001882fd024: ldr       x0, [x0, #0x30]
00000001882fd028: cbz       x0, #0x1882fd0ec
00000001882fd02c: mov       x23, x2
00000001882fd030: ldr       x20, [x0]
00000001882fd034: bl        #0x188296ae8 ; call _x_list_remove_head
00000001882fd038: str       x0, [x19, #0x30]
00000001882fd03c: ldr       w8, [x20, #4]
00000001882fd040: ldr       w9, [x19, #0x70]
00000001882fd044: cmp       w8, w9
00000001882fd048: b.ne      #0x1882fd0d8
00000001882fd04c: ldr       w8, [x20, #8]
00000001882fd050: ldr       w9, [x19, #0x74]
00000001882fd054: cmp       w8, w9
00000001882fd058: b.ne      #0x1882fd0d8
00000001882fd05c: ldr       w8, [x20, #0xc]
00000001882fd060: ldr       w9, [x19, #0x38]
00000001882fd064: cmp       w8, w9
00000001882fd068: b.ne      #0x1882fd0d8
00000001882fd06c: ldr       x8, [x20, #0x10]
00000001882fd070: ldr       x9, [x19, #0x58]
00000001882fd074: cmp       x8, x9
00000001882fd078: b.ne      #0x1882fd0d8
00000001882fd07c: ldrb      w8, [x20, #0x69]
00000001882fd080: and       w9, w8, #1
00000001882fd084: ldrh      w10, [x19, #0x108]
00000001882fd088: ubfx      w10, w10, #4, #1
00000001882fd08c: cmp       w10, w9
00000001882fd090: b.ne      #0x1882fd0d8
00000001882fd094: ldr       x9, [x20, #0x50]
00000001882fd098: ldr       x10, [x19, #0x40]
00000001882fd09c: cmp       x9, x10
00000001882fd0a0: b.ne      #0x1882fd0d8
00000001882fd0a4: ldrb      w9, [x20, #0x68]
00000001882fd0a8: cmp       w9, w21
00000001882fd0ac: b.ne      #0x1882fd0d8
00000001882fd0b0: ldr       x9, [x20, #0x20]
00000001882fd0b4: ldr       x10, [x19, #0xf8]
00000001882fd0b8: cmp       x9, x10
00000001882fd0bc: b.ne      #0x1882fd0d8
00000001882fd0c0: ldr       x9, [x20, #0x28]
00000001882fd0c4: ldr       x10, [x19, #0x100]
00000001882fd0c8: cmp       x9, x10
00000001882fd0cc: b.ne      #0x1882fd0d8
00000001882fd0d0: tbnz      w8, #2, #0x1882fd26c
00000001882fd0d4: cbz       w23, #0x1882fd26c
00000001882fd0d8: mov       x0, x19
00000001882fd0dc: mov       x1, x20
00000001882fd0e0: bl        #0x18843375c ; call __ZL16release_drawableP20_CAMetalLayerPrivateP23_CAMetalDrawablePrivate
00000001882fd0e4: ldr       x0, [x19, #0x30]
00000001882fd0e8: cbnz      x0, #0x1882fd030
00000001882fd0ec: cbz       w22, #0x1882fd0fc
00000001882fd0f0: ldp       w8, w9, [x19, #0x78]
00000001882fd0f4: cmp       w8, w9
00000001882fd0f8: b.hs      #0x1882fd244
00000001882fd0fc: ldr       w1, [x19, #0x38]
00000001882fd100: ldr       x0, [x19, #0x40]
00000001882fd104: bl        #0x1882e880c ; call __ZL32layer_private_check_pixel_formatP20_CAMetalLayerPrivatej
00000001882fd108: ldp       w22, w23, [x19, #0x70]
00000001882fd10c: ldr       x8, [x19, #0x40]
00000001882fd110: str       x8, [sp, #0x38]
00000001882fd114: ldr       x26, [x19, #0x58]
00000001882fd118: ldrh      w8, [x19, #0x108]
00000001882fd11c: and       w9, w21, #0xfffffffd
00000001882fd120: cmp       w9, #1
00000001882fd124: csel      w1, w23, w22, eq
00000001882fd128: csel      w2, w22, w23, eq
00000001882fd12c: ands      w24, w8, #0x10
00000001882fd130: str       w21, [sp, #0x34]
00000001882fd134: ldr       w21, [x19, #0x38]
00000001882fd138: ldr       x9, [x19, #0xe0]
00000001882fd13c: ldr       x8, [x19, #0xe8]
00000001882fd140: stp       x9, x8, [sp, #0x20]
00000001882fd144: ldp       x27, x28, [x19, #0xf8]
00000001882fd148: ldr       x20, [x19, #0x10]
00000001882fd14c: mov       w8, #6
00000001882fd150: csel      w8, w8, wzr, ne
00000001882fd154: mov       x9, #0xfffff0000
00000001882fd158: movk      x9, #0xc020
00000001882fd15c: ldr       w9, [x9]
00000001882fd160: lsr       w9, w9, #9
00000001882fd164: and       w9, w9, #4
00000001882fd168: orr       w3, w9, w8
00000001882fd16c: adrp      x5, #0x1d5812000
00000001882fd170: add       x5, x5, #0xd98
00000001882fd174: mov       x0, x21
00000001882fd178: mov       x4, x27
00000001882fd17c: bl        #0x1882bcfa8 ; call __ZN2CA6Render34create_iosurface_with_pixel_formatEjjjjyPK10__CFString
00000001882fd180: cbz       x0, #0x1882fd244
00000001882fd184: mov       x25, x0
00000001882fd188: cmp       w24, #0
00000001882fd18c: cset      w8, ne
00000001882fd190: str       w8, [sp, #0x1c]
00000001882fd194: mov       w0, #1
00000001882fd198: mov       w1, #0x70
00000001882fd19c: bl        #0x1884c9398
00000001882fd1a0: str       x20, [sp, #0x10]
00000001882fd1a4: mov       x20, x0
00000001882fd1a8: stp       w22, w23, [x0, #4]
00000001882fd1ac: str       w21, [x0, #0xc]
00000001882fd1b0: str       x26, [x0, #0x10]
00000001882fd1b4: stp       x27, x28, [x0, #0x20]
00000001882fd1b8: str       x25, [x0, #0x40]
00000001882fd1bc: ldr       x21, [sp, #0x38]
00000001882fd1c0: str       x21, [x0, #0x50]
00000001882fd1c4: ldr       w27, [sp, #0x34]
00000001882fd1c8: strb      w27, [x0, #0x68]
00000001882fd1cc: ldrb      w8, [x0, #0x69]
00000001882fd1d0: and       w8, w8, #0xcccccccc
00000001882fd1d4: orr       w8, w8, w24, lsr #4
00000001882fd1d8: orr       w8, w8, #4
00000001882fd1dc: strb      w8, [x0, #0x69]
00000001882fd1e0: ldr       x1, [sp, #0x20]
00000001882fd1e4: bl        #0x18830d848 ; call __ZL23drawable_set_colorspaceP23_CAMetalDrawablePrivateP12CGColorSpace
00000001882fd1e8: mov       x0, x20
00000001882fd1ec: ldr       x1, [sp, #0x28]
00000001882fd1f0: bl        #0x188433f50 ; call __ZL25drawable_set_edr_metadataP23_CAMetalDrawablePrivateP13CAEDRMetadata
00000001882fd1f4: adrp      x8, #0x1d5812000
00000001882fd1f8: add       x8, x8, #0xd98
00000001882fd1fc: stp       x8, x28, [sp]
00000001882fd200: mov       x0, x21
00000001882fd204: mov       x1, x25
00000001882fd208: mov       x2, x22
00000001882fd20c: mov       x3, x23
00000001882fd210: mov       x4, x26
00000001882fd214: mov       x5, #0
00000001882fd218: mov       x6, x27
00000001882fd21c: ldr       w7, [sp, #0x1c]
00000001882fd220: bl        #0x188433470 ; call __ZL25allocate_drawable_texturePU19objcproto9MTLDevice11objc_objectP11__IOSurfacejj14MTLPixelFormaty20CAMetalLayerRotationbP8NSStringm
00000001882fd224: str       x0, [x20, #0x48]
00000001882fd228: mov       x0, x20
00000001882fd22c: ldr       x1, [sp, #0x10]
00000001882fd230: bl        #0x18830692c ; call __ZL17register_drawableP23_CAMetalDrawablePrivateP13_CAImageQueue
00000001882fd234: ldr       w8, [x19, #0x78]
00000001882fd238: add       w8, w8, #1
00000001882fd23c: str       w8, [x19, #0x78]
00000001882fd240: b         #0x1882fd248
00000001882fd244: mov       x20, #0
00000001882fd248: mov       x0, x20
00000001882fd24c: ldp       x29, x30, [sp, #0x90]
00000001882fd250: ldp       x20, x19, [sp, #0x80]
00000001882fd254: ldp       x22, x21, [sp, #0x70]
00000001882fd258: ldp       x24, x23, [sp, #0x60]
00000001882fd25c: ldp       x26, x25, [sp, #0x50]
00000001882fd260: ldp       x28, x27, [sp, #0x40]
00000001882fd264: add       sp, sp, #0xa0
00000001882fd268: ret       
00000001882fd26c: ldr       x1, [x19, #0xe0]
00000001882fd270: ldr       x0, [x20, #0x58]
00000001882fd274: cbz       x1, #0x1882fd28c
00000001882fd278: cbz       x0, #0x1882fd28c
00000001882fd27c: bl        #0x18db36528 ; call _CFEqual
00000001882fd280: cbnz      w0, #0x1882fd2a4
00000001882fd284: ldr       x1, [x19, #0xe0]
00000001882fd288: b         #0x1882fd294
00000001882fd28c: cmp       x0, x1
00000001882fd290: b.eq      #0x1882fd2a4
00000001882fd294: mov       x0, x20
00000001882fd298: bl        #0x18830d848 ; call __ZL23drawable_set_colorspaceP23_CAMetalDrawablePrivateP12CGColorSpace
00000001882fd29c: mov       w21, #1
00000001882fd2a0: b         #0x1882fd2a8
00000001882fd2a4: mov       w21, #0
00000001882fd2a8: ldr       x1, [x19, #0xe8]
00000001882fd2ac: ldr       x0, [x20, #0x60]
00000001882fd2b0: cbz       x1, #0x1882fd2cc
00000001882fd2b4: cbz       x0, #0x1882fd2cc
00000001882fd2b8: mov       x2, x1
00000001882fd2bc: bl        #0x188541fc0 ; call _objc_msgSend$isEqual:
00000001882fd2c0: tbnz      w0, #0, #0x1882fd2e0
00000001882fd2c4: ldr       x1, [x19, #0xe8]
00000001882fd2c8: b         #0x1882fd2d4
00000001882fd2cc: cmp       x0, x1
00000001882fd2d0: b.eq      #0x1882fd2e0
00000001882fd2d4: mov       x0, x20
00000001882fd2d8: bl        #0x188433f50 ; call __ZL25drawable_set_edr_metadataP23_CAMetalDrawablePrivateP13CAEDRMetadata
00000001882fd2dc: b         #0x1882fd2e4
00000001882fd2e0: cbz       w21, #0x1882fd248
00000001882fd2e4: ldr       x1, [x19, #0x10]
00000001882fd2e8: mov       x0, x20
00000001882fd2ec: bl        #0x18830692c ; call __ZL17register_drawableP23_CAMetalDrawablePrivateP13_CAImageQueue
00000001882fd2f0: b         #0x1882fd248
