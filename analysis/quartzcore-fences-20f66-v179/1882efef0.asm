00000001882efef0: stp       x22, x21, [sp, #-0x30]!
00000001882efef4: stp       x20, x19, [sp, #0x10]
00000001882efef8: stp       x29, x30, [sp, #0x20]
00000001882efefc: add       x29, sp, #0x20
00000001882eff00: mov       x19, x2
00000001882eff04: ldr       w8, [x0, #0x14]
00000001882eff08: mov       w9, #0x6663
00000001882eff0c: movk      w9, #0x726d, lsl #16
00000001882eff10: cmp       w8, w9
00000001882eff14: b.eq      #0x1882eff6c
00000001882eff18: mov       w9, #0x6667
00000001882eff1c: movk      w9, #0x726c, lsl #16
00000001882eff20: cmp       w8, w9
00000001882eff24: b.ne      #0x1882efff4
00000001882eff28: cmp       x1, #0x40
00000001882eff2c: b.lo      #0x1882efff4
00000001882eff30: ldr       w8, [x0, #4]
00000001882eff34: cmp       w8, #0x40
00000001882eff38: b.lo      #0x1882efff4
00000001882eff3c: ldr       w8, [x0]
00000001882eff40: tbz       w8, #0x1f, #0x1882efff4
00000001882eff44: ldr       w9, [x0, #0x18]
00000001882eff48: cmp       w9, #1
00000001882eff4c: b.eq      #0x1882effd0
00000001882eff50: mov       w8, #0
00000001882eff54: cmp       w9, #2
00000001882eff58: b.ne      #0x1882efff8
00000001882eff5c: ldrb      w8, [x0, #0x37]
00000001882eff60: cbnz      w8, #0x1882effd0
00000001882eff64: ldr       w9, [x0, #0x2c]
00000001882eff68: b         #0x1882effd4
00000001882eff6c: cmp       x1, #0x34
00000001882eff70: b.lo      #0x1882efff4
00000001882eff74: ldr       w8, [x0, #4]
00000001882eff78: cmp       w8, #0x34
00000001882eff7c: b.lo      #0x1882efff4
00000001882eff80: ldr       w8, [x0]
00000001882eff84: tbz       w8, #0x1f, #0x1882efff4
00000001882eff88: ldr       w8, [x0, #0x18]
00000001882eff8c: cmp       w8, #1
00000001882eff90: b.ne      #0x1882efff4
00000001882eff94: ldrb      w8, [x0, #0x27]
00000001882eff98: cmp       w8, #1
00000001882eff9c: b.ne      #0x1882efff4
00000001882effa0: ldur      x20, [x0, #0x1c]
00000001882effa4: cbz       x20, #0x1882efff4
00000001882effa8: ldr       w8, [x0, #0x28]
00000001882effac: cmp       w8, #8
00000001882effb0: b.lo      #0x1882efff4
00000001882effb4: cbz       x5, #0x1882effc0
00000001882effb8: ldr       w9, [x0, #0x2c]
00000001882effbc: str       w9, [x5]
00000001882effc0: cbz       x6, #0x1882f0018
00000001882effc4: ldr       w9, [x0, #0x30]
00000001882effc8: str       w9, [x6]
00000001882effcc: b         #0x1882f0018
00000001882effd0: mov       w9, #0
00000001882effd4: ldrb      w8, [x0, #0x27]
00000001882effd8: cmp       w8, #1
00000001882effdc: b.ne      #0x1882efff4
00000001882effe0: ldur      x20, [x0, #0x1c]
00000001882effe4: cbz       x20, #0x1882efff4
00000001882effe8: ldr       w8, [x0, #0x28]
00000001882effec: cmp       w8, #8
00000001882efff0: b.hs      #0x1882f000c
00000001882efff4: mov       w8, #0
00000001882efff8: mov       x0, x8
00000001882efffc: ldp       x29, x30, [sp, #0x20]
00000001882f0000: ldp       x20, x19, [sp, #0x10]
00000001882f0004: ldp       x22, x21, [sp], #0x30
00000001882f0008: ret
00000001882f000c: ldr       d0, [x0, #0x38]
00000001882f0010: str       d0, [x3]
00000001882f0014: str       w9, [x4]
00000001882f0018: lsr       w21, w8, #3
00000001882f001c: ucvtf     s0, w21
00000001882f0020: ldr       s1, [x19, #0x20]
00000001882f0024: fdiv      s0, s0, s1
00000001882f0028: fcvtpu    x1, s0
00000001882f002c: mov       x0, x19
00000001882f0030: bl        #0x1883b45b4 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE8__rehashILb1EEEvm
00000001882f0034: mov       x0, x19
00000001882f0038: mov       x1, x20
00000001882f003c: mov       x2, x20
00000001882f0040: bl        #0x1882e0cf4 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE25__emplace_unique_key_argsIyJRKyEEENS_4pairINS_15__hash_iteratorIPNS_11__hash_nodeIyPvEEEEbEERKT_DpOT0_
00000001882f0044: add       x20, x20, #8
00000001882f0048: mov       w8, #1
00000001882f004c: subs      x21, x21, #1
00000001882f0050: b.ne      #0x1882f0034
00000001882f0054: b         #0x1882efff8
