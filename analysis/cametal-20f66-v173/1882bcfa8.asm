00000001882bcfa8: sub       sp, sp, #0xa0
00000001882bcfac: stp       x28, x27, [sp, #0x40]
00000001882bcfb0: stp       x26, x25, [sp, #0x50]
00000001882bcfb4: stp       x24, x23, [sp, #0x60]
00000001882bcfb8: stp       x22, x21, [sp, #0x70]
00000001882bcfbc: stp       x20, x19, [sp, #0x80]
00000001882bcfc0: stp       x29, x30, [sp, #0x90]
00000001882bcfc4: add       x29, sp, #0x90
00000001882bcfc8: mov       x23, x0
00000001882bcfcc: mov       x0, #0
00000001882bcfd0: adrp      x8, #0x1daabe000
00000001882bcfd4: ldr       x8, [x8, #0x7f0] ; [0x1daabe7f0]=0x201e1adb490
00000001882bcfd8: ldr       x8, [x8]
00000001882bcfdc: str       x8, [sp, #0x38]
00000001882bcfe0: cbz       w1, #0x1882bd134
00000001882bcfe4: mov       x20, x2
00000001882bcfe8: cbz       w2, #0x1882bd134
00000001882bcfec: mov       x22, x5
00000001882bcff0: mov       x19, x4
00000001882bcff4: mov       x27, x3
00000001882bcff8: mov       x21, x1
00000001882bcffc: lsl       w8, w3, #1
00000001882bd000: and       w24, w8, #0x10
00000001882bd004: bfi       w24, w3, #3, #1
00000001882bd008: ubfx      w8, w3, #5, #1
00000001882bd00c: tst       w3, #0x10
00000001882bd010: mov       w9, #2
00000001882bd014: csel      w25, w8, w9, eq
00000001882bd018: adrp      x8, #0x1daac2000
00000001882bd01c: ldr       x8, [x8, #0xf58] ; [0x1daac2f58]=0x201e1ad9868
00000001882bd020: ldr       x28, [x8]
00000001882bd024: mov       w8, #0x1c6
00000001882bd028: tst       w3, w8
00000001882bd02c: mov       w8, #0x700
00000001882bd030: mov       w9, #0x400
00000001882bd034: csel      w26, w9, w8, eq
00000001882bd038: adrp      x8, #0x1e1b9c000
00000001882bd03c: ldr       x8, [x8, #0x1e0] ; [0x1e1b9c1e0]=0x0
00000001882bd040: cmn       x8, #1
00000001882bd044: b.ne      #0x1882bd088
00000001882bd048: tbz       w27, #1, #0x1882bd0a0
00000001882bd04c: adrp      x8, #0x1e1b9b000
00000001882bd050: ldrb      w8, [x8, #0x8c8]
00000001882bd054: cbz       w8, #0x1882bd0a0
00000001882bd058: adrp      x8, #0x1e1b9b000
00000001882bd05c: ldr       x8, [x8, #0xbe0] ; [0x1e1b9bbe0]=0x0
00000001882bd060: cmn       x8, #1
00000001882bd064: b.ne      #0x1882bd16c
00000001882bd068: adrp      x8, #0x1e1b9b000
00000001882bd06c: ldrb      w8, [x8, #0x7a8]
00000001882bd070: cmp       w8, #0
00000001882bd074: mov       w8, #2
00000001882bd078: cinc      w1, w8, ne
00000001882bd07c: mov       x0, x23
00000001882bd080: mov       w2, #0
00000001882bd084: b         #0x1882bd0ec
00000001882bd088: adrp      x0, #0x1e1b9c000
00000001882bd08c: add       x0, x0, #0x1e0
00000001882bd090: adrp      x1, #0x1d57fc000
00000001882bd094: add       x1, x1, #0xfe8
00000001882bd098: bl        #0x1884c950c ; x1 literal: ___block_literal_global.16
00000001882bd09c: tbnz      w27, #1, #0x1882bd04c
00000001882bd0a0: adrp      x8, #0x1e1b9b000
00000001882bd0a4: ldr       x8, [x8, #0x9d0] ; [0x1e1b9b9d0]=0x0
00000001882bd0a8: cmn       x8, #1
00000001882bd0ac: b.ne      #0x1882bd184
00000001882bd0b0: tst       w27, #0x1c0
00000001882bd0b4: b.eq      #0x1882bd0f4
00000001882bd0b8: adrp      x8, #0x1dcc22000
00000001882bd0bc: ldrb      w8, [x8, #0x98]
00000001882bd0c0: cbz       w8, #0x1882bd0f4
00000001882bd0c4: tbnz      w27, #6, #0x1882bd0d8
00000001882bd0c8: tbnz      w27, #7, #0x1882bd0e0
00000001882bd0cc: sbfx      w8, w27, #8, #1
00000001882bd0d0: and       w2, w8, #3
00000001882bd0d4: b         #0x1882bd0e4
00000001882bd0d8: mov       w2, #1
00000001882bd0dc: b         #0x1882bd0e4
00000001882bd0e0: mov       w2, #2
00000001882bd0e4: mov       x0, x23
00000001882bd0e8: mov       w1, #4
00000001882bd0ec: bl        #0x188251684 ; call __ZN2CA6Render25fourcc_compressed_of_typeEj24IOSurfaceCompressionType29IOSurfaceCompressionFootprint
00000001882bd0f0: mov       x23, x0
00000001882bd0f4: adrp      x8, #0x1884d3000
00000001882bd0f8: ldr       q0, [x8, #0x180] ; [0x1884d3180]=0x40
00000001882bd0fc: str       q0, [sp, #0x10]
00000001882bd100: mov       w8, #1
00000001882bd104: stp       x8, x28, [sp, #0x20]
00000001882bd108: str       xzr, [sp, #0x30]
00000001882bd10c: str       x22, [sp]
00000001882bd110: add       x7, sp, #0x10
00000001882bd114: mov       x0, x21
00000001882bd118: mov       x1, x20
00000001882bd11c: mov       x2, x23
00000001882bd120: mov       x3, x26
00000001882bd124: mov       x4, x25
00000001882bd128: mov       x5, x24
00000001882bd12c: mov       x6, x19
00000001882bd130: bl        #0x188297cd4 ; call __ZN2CA11SurfaceUtil17CAIOSurfaceCreateEjjjjjjyNS0_16SurfaceAlignmentEPK10__CFString
00000001882bd134: ldr       x8, [sp, #0x38]
00000001882bd138: adrp      x9, #0x1daabe000
00000001882bd13c: ldr       x9, [x9, #0x7f0] ; [0x1daabe7f0]=0x201e1adb490
00000001882bd140: ldr       x9, [x9]
00000001882bd144: cmp       x9, x8
00000001882bd148: b.ne      #0x1882bd19c
00000001882bd14c: ldp       x29, x30, [sp, #0x90]
00000001882bd150: ldp       x20, x19, [sp, #0x80]
00000001882bd154: ldp       x22, x21, [sp, #0x70]
00000001882bd158: ldp       x24, x23, [sp, #0x60]
00000001882bd15c: ldp       x26, x25, [sp, #0x50]
00000001882bd160: ldp       x28, x27, [sp, #0x40]
00000001882bd164: add       sp, sp, #0xa0
00000001882bd168: ret
00000001882bd16c: adrp      x0, #0x1e1b9b000
00000001882bd170: add       x0, x0, #0xbe0
00000001882bd174: adrp      x1, #0x1d57fd000
00000001882bd178: add       x1, x1, #0x68
00000001882bd17c: bl        #0x1884c950c ; x1 literal: ___block_literal_global.28
00000001882bd180: b         #0x1882bd068
00000001882bd184: adrp      x0, #0x1e1b9b000
00000001882bd188: add       x0, x0, #0x9d0
00000001882bd18c: adrp      x1, #0x1d57fd000
00000001882bd190: add       x1, x1, #0xa8
00000001882bd194: bl        #0x1884c950c ; x1 literal: ___block_literal_global.34.9370
00000001882bd198: b         #0x1882bd0b0
00000001882bd19c: bl        #0x18db38a60 ; call ___stack_chk_fail
