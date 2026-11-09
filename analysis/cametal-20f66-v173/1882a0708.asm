00000001882a0708: sub       sp, sp, #0x90
00000001882a070c: stp       d11, d10, [sp, #0x20]
00000001882a0710: stp       d9, d8, [sp, #0x30]
00000001882a0714: stp       x26, x25, [sp, #0x40]
00000001882a0718: stp       x24, x23, [sp, #0x50]
00000001882a071c: stp       x22, x21, [sp, #0x60]
00000001882a0720: stp       x20, x19, [sp, #0x70]
00000001882a0724: stp       x29, x30, [sp, #0x80]
00000001882a0728: add       x29, sp, #0x80
00000001882a072c: adrp      x8, #0x1daabe000
00000001882a0730: ldr       x8, [x8, #0x7f0] ; [0x1daabe7f0]=0x201e1adb490
00000001882a0734: ldr       x8, [x8]
00000001882a0738: str       x8, [sp, #0x18]
00000001882a073c: ldr       x25, [x0, #8]
00000001882a0740: cbz       x25, #0x1882a081c
00000001882a0744: mov       x19, x0
00000001882a0748: ldr       x20, [x25, #0x38]
00000001882a074c: ldrh      w8, [x20, #0x108]
00000001882a0750: mov       w9, #0x400
00000001882a0754: bic       w9, w9, w8, lsl #1
00000001882a0758: mov       w10, #9
00000001882a075c: tst       w8, w10
00000001882a0760: csel      w9, w9, wzr, eq
00000001882a0764: and       w8, w8, #0xfffffbff
00000001882a0768: orr       w8, w9, w8
00000001882a076c: strh      w8, [x20, #0x108]
00000001882a0770: ldr       x0, [x25, #0x40]
00000001882a0774: bl        #0x18db38634 ; call _IOSurfaceGetID
00000001882a0778: mov       w1, w0
00000001882a077c: mov       w0, #0x150
00000001882a0780: movk      w0, #0x31ca, lsl #16
00000001882a0784: mov       x2, #0
00000001882a0788: mov       x3, #0
00000001882a078c: mov       x4, #0
00000001882a0790: bl        #0x18db38f70 ; call _kdebug_trace
00000001882a0794: adrp      x23, #0x1e1b9c000
00000001882a0798: ldr       x8, [x23, #0x5a0] ; [0x1e1b9c5a0]=0x0
00000001882a079c: cmn       x8, #1
00000001882a07a0: b.ne      #0x1882a0a3c
00000001882a07a4: adrp      x24, #0x1e1b9b000
00000001882a07a8: ldrb      w8, [x24, #0x788]
00000001882a07ac: cmp       w8, #0
00000001882a07b0: cset      w8, eq
00000001882a07b4: adrp      x9, #0x1884d3000
00000001882a07b8: add       x9, x9, #0x610
00000001882a07bc: ldr       d9, [x9, w8, uxtw #3]
00000001882a07c0: bl        #0x18db38fac ; call _mach_absolute_time
00000001882a07c4: bl        #0x188236490 ; call _CATimeWithHostTime
00000001882a07c8: ldr       d8, [x25, #0x30]
00000001882a07cc: fsub      d10, d0, d8
00000001882a07d0: stp       xzr, xzr, [sp]
00000001882a07d4: mov       x8, sp
00000001882a07d8: add       x1, x8, #8
00000001882a07dc: mov       x0, sp
00000001882a07e0: mov       x2, #0
00000001882a07e4: bl        #0x18db38fd0 ; call _mach_get_times
00000001882a07e8: ldp       x21, x26, [sp]
00000001882a07ec: fmov      d0, d8
00000001882a07f0: bl        #0x18822afc0 ; call _CAHostTimeWithTime
00000001882a07f4: mov       x22, x0
00000001882a07f8: adrp      x8, #0x1e1b9b000
00000001882a07fc: ldr       x8, [x8, #0x718] ; [0x1e1b9b718]=0x0
00000001882a0800: cmn       x8, #1
00000001882a0804: b.ne      #0x1882a0a54
00000001882a0808: fcmp      d10, d9
00000001882a080c: b.ge      #0x1882a0830
00000001882a0810: adrp      x8, #0x1e1b9b000
00000001882a0814: add       x8, x8, #0x710
00000001882a0818: b         #0x1882a0848
00000001882a081c: adrp      x8, #0x1dcc23000
00000001882a0820: ldr       x8, [x8, #0xc08] ; [0x1dcc23c08]=0x0
00000001882a0824: cmn       x8, #1
00000001882a0828: b.ne      #0x1882a0a84
00000001882a082c: b         #0x1882a09a8
00000001882a0830: adrp      x8, #0x1e1b9b000
00000001882a0834: ldr       x8, [x8, #0x6a8] ; [0x1e1b9b6a8]=0x0
00000001882a0838: cmn       x8, #1
00000001882a083c: b.ne      #0x1882a0ad0
00000001882a0840: adrp      x8, #0x1e1b9b000
00000001882a0844: add       x8, x8, #0x6e0
00000001882a0848: sub       x10, x26, x21
00000001882a084c: ldr       x21, [x8]
00000001882a0850: ldr       x8, [x20, #0x10]
00000001882a0854: cbz       x8, #0x1882a0868
00000001882a0858: ldr       x9, [x8, #0x30]
00000001882a085c: cbz       x9, #0x1882a086c
00000001882a0860: ldr       x9, [x9, #0x18]
00000001882a0864: b         #0x1882a086c
00000001882a0868: mov       x9, #0
00000001882a086c: add       x26, x22, x10
00000001882a0870: ldrh      w10, [x20, #0x108]
00000001882a0874: tbz       w10, #2, #0x1882a08dc
00000001882a0878: ldr       x8, [x8, #0x30]
00000001882a087c: cbz       x8, #0x1882a08dc
00000001882a0880: ldr       x8, [x8, #0x18]
00000001882a0884: ldr       w8, [x8, #0x18]
00000001882a0888: cbz       w8, #0x1882a08dc
00000001882a088c: ldr       w22, [x9, #0x48]
00000001882a0890: cbz       w22, #0x1882a0940
00000001882a0894: mov       x0, x21
00000001882a0898: bl        #0x18db3951c ; call _os_signpost_enabled
00000001882a089c: cbz       w0, #0x1882a0940
00000001882a08a0: ldr       x0, [x25, #0x40]
00000001882a08a4: bl        #0x18db38634 ; call _IOSurfaceGetID
00000001882a08a8: mov       w8, #0x200
00000001882a08ac: movk      w8, #0x402, lsl #16
00000001882a08b0: stp       w8, w0, [sp]
00000001882a08b4: mov       w8, #0x802
00000001882a08b8: strh      w8, [sp, #8]
00000001882a08bc: stur      x26, [sp, #0xa]
00000001882a08c0: adrp      x0, #0x1881fb000
00000001882a08c4: add       x0, x0, #0
00000001882a08c8: adrp      x4, #0x188520000
00000001882a08cc: add       x4, x4, #0x2ab
00000001882a08d0: adrp      x5, #0x188520000
00000001882a08d4: add       x5, x5, #0x2ba
00000001882a08d8: b         #0x1882a0928
00000001882a08dc: ldr       w22, [x9, #0x48]
00000001882a08e0: cbz       w22, #0x1882a0940
00000001882a08e4: mov       x0, x21
00000001882a08e8: bl        #0x18db3951c ; call _os_signpost_enabled
00000001882a08ec: cbz       w0, #0x1882a0940
00000001882a08f0: ldr       x0, [x25, #0x40]
00000001882a08f4: bl        #0x18db38634 ; call _IOSurfaceGetID
00000001882a08f8: mov       w8, #0x200
00000001882a08fc: movk      w8, #0x402, lsl #16
00000001882a0900: stp       w8, w0, [sp]
00000001882a0904: mov       w8, #0x802
00000001882a0908: strh      w8, [sp, #8]
00000001882a090c: stur      x26, [sp, #0xa]
00000001882a0910: adrp      x0, #0x1881fb000
00000001882a0914: add       x0, x0, #0
00000001882a0918: adrp      x4, #0x188520000
00000001882a091c: add       x4, x4, #0x2ab
00000001882a0920: adrp      x5, #0x188520000
00000001882a0924: add       x5, x5, #0x332
00000001882a0928: mov       x6, sp
00000001882a092c: mov       x1, x21
00000001882a0930: mov       w2, #0
00000001882a0934: mov       x3, x22
00000001882a0938: mov       w7, #0x12
00000001882a093c: bl        #0x18db38a9c ; call __os_signpost_emit_with_name_impl
00000001882a0940: adrp      x8, #0x1e1b9b000
00000001882a0944: ldr       x8, [x8, #0x6f0] ; [0x1e1b9b6f0]=0x0
00000001882a0948: cmn       x8, #1
00000001882a094c: b.ne      #0x1882a0a6c
00000001882a0950: adrp      x8, #0x1e1b9b000
00000001882a0954: ldrb      w8, [x8, #0x6c9]
00000001882a0958: cbz       w8, #0x1882a09e4
00000001882a095c: ldrh      w8, [x20, #0x108]
00000001882a0960: lsr       w9, w8, #7
00000001882a0964: and       w9, w9, #4
00000001882a0968: bfxil     w9, w8, #0, #1
00000001882a096c: tst       w8, #0x400
00000001882a0970: cset      w8, eq
00000001882a0974: adrp      x10, #0x1e1b9c000
00000001882a0978: ldrb      w10, [x10, #0xdf5]
00000001882a097c: orr       w8, w8, w10
00000001882a0980: orr       w10, w9, #2
00000001882a0984: tst       w8, #1
00000001882a0988: csel      w2, w9, w10, ne
00000001882a098c: adrp      x8, #0x1884d4000
00000001882a0990: ldr       d0, [x8, #0xf8] ; [0x1884d40f8]=0x3f70624dd2f1a9fc
00000001882a0994: fmov      d1, xzr
00000001882a0998: fcsel     d0, d1, d0, ne
00000001882a099c: mov       x0, x20
00000001882a09a0: mov       x1, x19
00000001882a09a4: bl        #0x18821567c ; call __ZL21layer_private_presentP20_CAMetalLayerPrivateP15CAMetalDrawabledj
00000001882a09a8: ldr       x8, [sp, #0x18]
00000001882a09ac: adrp      x9, #0x1daabe000
00000001882a09b0: ldr       x9, [x9, #0x7f0] ; [0x1daabe7f0]=0x201e1adb490
00000001882a09b4: ldr       x9, [x9]
00000001882a09b8: cmp       x9, x8
00000001882a09bc: b.ne      #0x1882a0b18
00000001882a09c0: ldp       x29, x30, [sp, #0x80]
00000001882a09c4: ldp       x20, x19, [sp, #0x70]
00000001882a09c8: ldp       x22, x21, [sp, #0x60]
00000001882a09cc: ldp       x24, x23, [sp, #0x50]
00000001882a09d0: ldp       x26, x25, [sp, #0x40]
00000001882a09d4: ldp       d9, d8, [sp, #0x30]
00000001882a09d8: ldp       d11, d10, [sp, #0x20]
00000001882a09dc: add       sp, sp, #0x90
00000001882a09e0: ret
00000001882a09e4: ldr       x8, [x23, #0x5a0]
00000001882a09e8: cmn       x8, #1
00000001882a09ec: b.ne      #0x1882a0ae8
00000001882a09f0: ldrb      w8, [x24, #0x788]
00000001882a09f4: cbz       w8, #0x1882a0a00
00000001882a09f8: bl        #0x18829f23c ; call _CADeviceDisableMinimumFrameDuration
00000001882a09fc: cbz       w0, #0x1882a0a24
00000001882a0a00: bl        #0x1884431a0 ; call _CADevicePrefers60HzAPT
00000001882a0a04: cbz       w0, #0x1882a095c
00000001882a0a08: adrp      x8, #0x1dcc23000
00000001882a0a0c: ldr       x8, [x8, #0xe20] ; [0x1dcc23e20]=0x0
00000001882a0a10: cmn       x8, #1
00000001882a0a14: b.ne      #0x1882a0b00
00000001882a0a18: adrp      x8, #0x1dcc23000
00000001882a0a1c: ldrb      w8, [x8, #0xe28]
00000001882a0a20: cbnz      w8, #0x1882a095c
00000001882a0a24: adrp      x8, #0x1884d4000
00000001882a0a28: ldr       d0, [x8, #0x260] ; [0x1884d4260]=0x3f8cac083126e979
00000001882a0a2c: mov       x0, x20
00000001882a0a30: mov       x1, x19
00000001882a0a34: mov       w2, #2
00000001882a0a38: b         #0x1882a09a4
00000001882a0a3c: adrp      x0, #0x1e1b9c000
00000001882a0a40: add       x0, x0, #0x5a0
00000001882a0a44: adrp      x1, #0x1d57eb000
00000001882a0a48: add       x1, x1, #0x8d8
00000001882a0a4c: bl        #0x1884c950c ; x1 literal: ___block_literal_global.38
00000001882a0a50: b         #0x1882a07a4
00000001882a0a54: adrp      x0, #0x1e1b9b000
00000001882a0a58: add       x0, x0, #0x718
00000001882a0a5c: adrp      x1, #0x1d57fc000
00000001882a0a60: add       x1, x1, #0xcd0
00000001882a0a64: bl        #0x1884c950c ; x1 literal: ___block_literal_global.363
00000001882a0a68: b         #0x1882a0808
00000001882a0a6c: adrp      x0, #0x1e1b9b000
00000001882a0a70: add       x0, x0, #0x6f0
00000001882a0a74: adrp      x1, #0x1d57fd000
00000001882a0a78: add       x1, x1, #0x8c8
00000001882a0a7c: bl        #0x1884c950c ; x1 literal: ___block_literal_global.195
00000001882a0a80: b         #0x1882a0950
00000001882a0a84: ldr       x8, [sp, #0x18]
00000001882a0a88: adrp      x9, #0x1daabe000
00000001882a0a8c: ldr       x9, [x9, #0x7f0] ; [0x1daabe7f0]=0x201e1adb490
00000001882a0a90: ldr       x9, [x9]
00000001882a0a94: cmp       x9, x8
00000001882a0a98: b.ne      #0x1882a0b18
00000001882a0a9c: adrp      x0, #0x1dcc23000
00000001882a0aa0: add       x0, x0, #0xc08
00000001882a0aa4: adrp      x1, #0x1d57fc000
00000001882a0aa8: add       x1, x1, #0xcb0
00000001882a0aac: ldp       x29, x30, [sp, #0x80]
00000001882a0ab0: ldp       x20, x19, [sp, #0x70]
00000001882a0ab4: ldp       x22, x21, [sp, #0x60]
00000001882a0ab8: ldp       x24, x23, [sp, #0x50]
00000001882a0abc: ldp       x26, x25, [sp, #0x40]
00000001882a0ac0: ldp       d9, d8, [sp, #0x30]
00000001882a0ac4: ldp       d11, d10, [sp, #0x20]
00000001882a0ac8: add       sp, sp, #0x90
00000001882a0acc: b         #0x1884c950c
00000001882a0ad0: adrp      x0, #0x1e1b9b000
00000001882a0ad4: add       x0, x0, #0x6a8
00000001882a0ad8: adrp      x1, #0x1d57fc000
00000001882a0adc: add       x1, x1, #0xcf0
00000001882a0ae0: bl        #0x1884c950c ; x1 literal: ___block_literal_global.366
00000001882a0ae4: b         #0x1882a0840
00000001882a0ae8: adrp      x0, #0x1e1b9c000
00000001882a0aec: add       x0, x0, #0x5a0
00000001882a0af0: adrp      x1, #0x1d57eb000
00000001882a0af4: add       x1, x1, #0x8d8
00000001882a0af8: bl        #0x1884c950c ; x1 literal: ___block_literal_global.38
00000001882a0afc: b         #0x1882a09f0
00000001882a0b00: adrp      x0, #0x1dcc23000
00000001882a0b04: add       x0, x0, #0xe20
00000001882a0b08: adrp      x1, #0x1d57fd000
00000001882a0b0c: add       x1, x1, #0x4e8
00000001882a0b10: bl        #0x1884c950c ; x1 literal: ___block_literal_global.118
00000001882a0b14: b         #0x1882a0a18
00000001882a0b18: bl        #0x18db38a60 ; call ___stack_chk_fail
