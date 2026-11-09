0000000181a2cb3c: sub       sp, sp, #0x80
0000000181a2cb40: stp       x20, x19, [sp, #0x60]
0000000181a2cb44: stp       x29, x30, [sp, #0x70]
0000000181a2cb48: add       x29, sp, #0x70
0000000181a2cb4c: adrp      x8, #0x1e1b2f000
0000000181a2cb50: ldr       x8, [x8, #0xbb8]
0000000181a2cb54: cmn       x8, #1
0000000181a2cb58: b.ne      #0x181a2cbf0
0000000181a2cb5c: add       x8, sp, #0x30
0000000181a2cb60: stp       xzr, x8, [sp, #0x30]
0000000181a2cb64: adrp      x9, #0x181b40000
0000000181a2cb68: ldr       d0, [x9, #0x3b0]
0000000181a2cb6c: str       d0, [sp, #0x40]
0000000181a2cb70: adrp      x9, #0x181ac4000
0000000181a2cb74: add       x9, x9, #0xeb8
0000000181a2cb78: adrp      x10, #0x181ac4000
0000000181a2cb7c: add       x10, x10, #0xec8
0000000181a2cb80: stp       x9, x10, [sp, #0x48]
0000000181a2cb84: str       xzr, [sp, #0x58]
0000000181a2cb88: adrp      x9, #0x1e1b2f000
0000000181a2cb8c: adrp      x10, #0x1daabe000
0000000181a2cb90: ldr       x10, [x10, #0x5c8]
0000000181a2cb94: ldr       x0, [x9, #0xbb0]
0000000181a2cb98: str       x10, [sp, #8]
0000000181a2cb9c: adrp      x9, #0x181b3e000
0000000181a2cba0: ldr       d0, [x9, #0x788]
0000000181a2cba4: adrp      x9, #0x181a2c000
0000000181a2cba8: add       x9, x9, #0x42c
0000000181a2cbac: str       d0, [sp, #0x10]
0000000181a2cbb0: adrp      x10, #0x1d5682000
0000000181a2cbb4: add       x10, x10, #0x948
0000000181a2cbb8: stp       x9, x10, [sp, #0x18]
0000000181a2cbbc: str       x8, [sp, #0x28]
0000000181a2cbc0: add       x1, sp, #8
0000000181a2cbc4: bl        #0x181b284c0 ; _dispatch_sync
0000000181a2cbc8: ldr       x8, [sp, #0x38]
0000000181a2cbcc: ldr       x19, [x8, #0x28]
0000000181a2cbd0: add       x0, sp, #0x30
0000000181a2cbd4: mov       w1, #8
0000000181a2cbd8: bl        #0x186cfe00c ; __Block_object_dispose
0000000181a2cbdc: mov       x0, x19
0000000181a2cbe0: ldp       x29, x30, [sp, #0x70]
0000000181a2cbe4: ldp       x20, x19, [sp, #0x60]
0000000181a2cbe8: add       sp, sp, #0x80
0000000181a2cbec: ret
0000000181a2cbf0: adrp      x0, #0x1e1b2f000
0000000181a2cbf4: add       x0, x0, #0xbb8
0000000181a2cbf8: adrp      x1, #0x1d5682000
0000000181a2cbfc: add       x1, x1, #0xa20
0000000181a2cc00: bl        #0x181b28400 ; _dispatch_once
0000000181a2cc04: b         #0x181a2cb5c
