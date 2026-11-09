000000018829cbf4: stp       x20, x19, [sp, #-0x20]!
000000018829cbf8: stp       x29, x30, [sp, #0x10]
000000018829cbfc: add       x29, sp, #0x10
000000018829cc00: mov       x19, x0
000000018829cc04: ldr       x8, [x0, #8]
000000018829cc08: cbnz      x8, #0x18829cc1c
000000018829cc0c: adrp      x8, #0x1dcc23000
000000018829cc10: ldr       x8, [x8, #0xbd0] ; [0x1dcc23bd0]=0x0
000000018829cc14: cmn       x8, #1
000000018829cc18: b.ne      #0x18829cc2c
000000018829cc1c: ldr       x0, [x19, #0x10]
000000018829cc20: ldp       x29, x30, [sp, #0x10]
000000018829cc24: ldp       x20, x19, [sp], #0x20
000000018829cc28: ret       
000000018829cc2c: adrp      x0, #0x1dcc23000
000000018829cc30: add       x0, x0, #0xbd0
000000018829cc34: adrp      x1, #0x1d57fc000
000000018829cc38: add       x1, x1, #0xc60
000000018829cc3c: bl        #0x1884c950c ; x1 literal: ___block_literal_global.8426
000000018829cc40: b         #0x18829cc1c
