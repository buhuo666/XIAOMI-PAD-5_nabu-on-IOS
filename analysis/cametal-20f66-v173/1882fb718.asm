00000001882fb718: stp       x20, x19, [sp, #-0x20]!
00000001882fb71c: stp       x29, x30, [sp, #0x10]
00000001882fb720: add       x29, sp, #0x10
00000001882fb724: bl        #0x18db3927c ; call _objc_autoreleasePoolPush
00000001882fb728: mov       x19, x0
00000001882fb72c: adrp      x8, #0x1dcc22000
00000001882fb730: ldr       x8, [x8, #0xb0] ; [0x1dcc220b0]=0x0
00000001882fb734: cmn       x8, #1
00000001882fb738: b.ne      #0x1882fb75c
00000001882fb73c: bl        #0x18db387c0 ; call _MTLCreateSystemDefaultDevice
00000001882fb740: mov       x20, x0
00000001882fb744: mov       x0, x19
00000001882fb748: bl        #0x1884c9a4c
00000001882fb74c: mov       x0, x20
00000001882fb750: ldp       x29, x30, [sp, #0x10]
00000001882fb754: ldp       x20, x19, [sp], #0x20
00000001882fb758: ret       
00000001882fb75c: adrp      x0, #0x1dcc22000
00000001882fb760: add       x0, x0, #0xb0
00000001882fb764: adrp      x1, #0x1d5800000
00000001882fb768: add       x1, x1, #0x5c8
00000001882fb76c: bl        #0x1884c950c ; x1 literal: ___block_literal_global.16993
00000001882fb770: b         #0x1882fb73c
00000001882fb774: mov       x20, x0
00000001882fb778: mov       x0, x19
00000001882fb77c: bl        #0x1884c9a4c
00000001882fb780: mov       x0, x20
00000001882fb784: bl        #0x18db388e0 ; call __Unwind_Resume
