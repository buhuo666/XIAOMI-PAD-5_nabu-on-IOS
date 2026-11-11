00000001af134850: stp       x22, x21, [sp, #-0x30]!
00000001af134854: stp       x20, x19, [sp, #0x10]
00000001af134858: stp       x29, x30, [sp, #0x20]
00000001af13485c: add       x29, sp, #0x20
00000001af134860: cbz       x0, #0x1af13489c
00000001af134864: mov       x20, x2
00000001af134868: mov       x19, x0
00000001af13486c: ldrb      w8, [x0, #0xb30]
00000001af134870: cbz       w8, #0x1af134890
00000001af134874: mov       w0, #0x100
00000001af134878: movk      w0, #0x3180, lsl #16
00000001af13487c: mov       x1, x19
00000001af134880: mov       x2, #0
00000001af134884: mov       x3, #0
00000001af134888: mov       x4, #0
00000001af13488c: bl        #0x1afaa36a0 ; call _kdebug_signpost
00000001af134890: ldr       x0, [x19, #0x5d0]
00000001af134894: bl        #0x1af1348f4 ; call _iomfb_GetMachMessageCount
00000001af134898: cbz       w0, #0x1af1348ac
00000001af13489c: ldp       x29, x30, [sp, #0x20]
00000001af1348a0: ldp       x20, x19, [sp, #0x10]
00000001af1348a4: ldp       x22, x21, [sp], #0x30
00000001af1348a8: ret
00000001af1348ac: ldp       x9, x8, [x20]
00000001af1348b0: orr       x21, x9, x8, lsl #32
00000001af1348b4: ldp       x9, x8, [x20, #0x10]
00000001af1348b8: orr       x1, x9, x8, lsl #32
00000001af1348bc: ldr       x8, [x19, #0x930]
00000001af1348c0: mov       x0, x19
00000001af1348c4: blr       x8
00000001af1348c8: mov       x2, x0
00000001af1348cc: ldp       x9, x8, [x20, #0x20]
00000001af1348d0: orr       x3, x9, x8, lsl #32
00000001af1348d4: ldr       x5, [x19, #0x5e8]
00000001af1348d8: ldr       x4, [x19, #0x5c8]
00000001af1348dc: mov       x0, x19
00000001af1348e0: mov       x1, x21
00000001af1348e4: ldp       x29, x30, [sp, #0x20]
00000001af1348e8: ldp       x20, x19, [sp, #0x10]
00000001af1348ec: ldp       x22, x21, [sp], #0x30
00000001af1348f0: br        x5
