00000001d031cdc0: sub       x3, x0, x1
00000001d031cdc4: cmp       x3, x2
00000001d031cdc8: b.lo      #0x1d031d010
00000001d031cdcc: mov       x3, x0
00000001d031cdd0: cmp       x2, #0x40
00000001d031cdd4: b.lo      #0x1d031cfec
00000001d031cdd8: sub       x4, x1, x0
00000001d031cddc: cmp       x4, x2
00000001d031cde0: b.lo      #0x1d031cee4
00000001d031cde4: cmp       x2, #4, lsl #12
00000001d031cde8: b.lo      #0x1d031ce68
00000001d031cdec: add       x3, x3, #0x20
00000001d031cdf0: and       x3, x3, #0xffffffffffffffe0
00000001d031cdf4: ldnp      x12, x13, [x1]
00000001d031cdf8: ldnp      x14, x15, [x1, #0x10]
00000001d031cdfc: sub       x5, x3, x0
00000001d031ce00: add       x1, x1, x5
00000001d031ce04: ldnp      x8, x9, [x1]
00000001d031ce08: ldnp      x10, x11, [x1, #0x10]
00000001d031ce0c: add       x1, x1, #0x20
00000001d031ce10: sub       x2, x2, x5
00000001d031ce14: stnp      x12, x13, [x0]
00000001d031ce18: stnp      x14, x15, [x0, #0x10]
00000001d031ce1c: subs      x2, x2, #0x40
00000001d031ce20: b.ls      #0x1d031ce44
00000001d031ce24: stnp      x8, x9, [x3]
00000001d031ce28: stnp      x10, x11, [x3, #0x10]
00000001d031ce2c: add       x3, x3, #0x20
00000001d031ce30: ldnp      x8, x9, [x1]
00000001d031ce34: ldnp      x10, x11, [x1, #0x10]
00000001d031ce38: add       x1, x1, #0x20
00000001d031ce3c: subs      x2, x2, #0x20
00000001d031ce40: b.hi      #0x1d031ce24
00000001d031ce44: add       x1, x1, x2
00000001d031ce48: ldnp      x12, x13, [x1]
00000001d031ce4c: ldnp      x14, x15, [x1, #0x10]
00000001d031ce50: stnp      x8, x9, [x3]
00000001d031ce54: stnp      x10, x11, [x3, #0x10]
00000001d031ce58: add       x3, x3, x2
00000001d031ce5c: stnp      x12, x13, [x3, #0x20]
00000001d031ce60: stnp      x14, x15, [x3, #0x30]
00000001d031ce64: ret
00000001d031ce68: add       x3, x3, #0x20
00000001d031ce6c: and       x3, x3, #0xffffffffffffffe0
00000001d031ce70: ldnp      x12, x13, [x1]
00000001d031ce74: ldnp      x14, x15, [x1, #0x10]
00000001d031ce78: sub       x5, x3, x0
00000001d031ce7c: add       x1, x1, x5
00000001d031ce80: ldnp      x8, x9, [x1]
00000001d031ce84: ldnp      x10, x11, [x1, #0x10]
00000001d031ce88: add       x1, x1, #0x20
00000001d031ce8c: sub       x2, x2, x5
00000001d031ce90: stp       x12, x13, [x0]
00000001d031ce94: stp       x14, x15, [x0, #0x10]
00000001d031ce98: subs      x2, x2, #0x40
00000001d031ce9c: b.ls      #0x1d031cec0
00000001d031cea0: stp       x8, x9, [x3]
00000001d031cea4: stp       x10, x11, [x3, #0x10]
00000001d031cea8: add       x3, x3, #0x20
00000001d031ceac: ldnp      x8, x9, [x1]
00000001d031ceb0: ldnp      x10, x11, [x1, #0x10]
00000001d031ceb4: add       x1, x1, #0x20
00000001d031ceb8: subs      x2, x2, #0x20
00000001d031cebc: b.hi      #0x1d031cea0
00000001d031cec0: add       x1, x1, x2
00000001d031cec4: ldnp      x12, x13, [x1]
00000001d031cec8: ldnp      x14, x15, [x1, #0x10]
00000001d031cecc: stp       x8, x9, [x3]
00000001d031ced0: stp       x10, x11, [x3, #0x10]
00000001d031ced4: add       x3, x3, x2
00000001d031ced8: stp       x12, x13, [x3, #0x20]
00000001d031cedc: stp       x14, x15, [x3, #0x30]
00000001d031cee0: ret
00000001d031cee4: cmp       x2, #4, lsl #12
00000001d031cee8: b.lo      #0x1d031cf68
00000001d031ceec: add       x3, x3, #0x20
00000001d031cef0: and       x3, x3, #0xffffffffffffffe0
00000001d031cef4: ldp       x12, x13, [x1]
00000001d031cef8: ldp       x14, x15, [x1, #0x10]
00000001d031cefc: sub       x5, x3, x0
00000001d031cf00: add       x1, x1, x5
00000001d031cf04: ldp       x8, x9, [x1]
00000001d031cf08: ldp       x10, x11, [x1, #0x10]
00000001d031cf0c: add       x1, x1, #0x20
00000001d031cf10: sub       x2, x2, x5
00000001d031cf14: stnp      x12, x13, [x0]
00000001d031cf18: stnp      x14, x15, [x0, #0x10]
00000001d031cf1c: subs      x2, x2, #0x40
00000001d031cf20: b.ls      #0x1d031cf44
00000001d031cf24: stnp      x8, x9, [x3]
00000001d031cf28: stnp      x10, x11, [x3, #0x10]
00000001d031cf2c: add       x3, x3, #0x20
00000001d031cf30: ldp       x8, x9, [x1]
00000001d031cf34: ldp       x10, x11, [x1, #0x10]
00000001d031cf38: add       x1, x1, #0x20
00000001d031cf3c: subs      x2, x2, #0x20
00000001d031cf40: b.hi      #0x1d031cf24
00000001d031cf44: add       x1, x1, x2
00000001d031cf48: ldp       x12, x13, [x1]
00000001d031cf4c: ldp       x14, x15, [x1, #0x10]
00000001d031cf50: stnp      x8, x9, [x3]
00000001d031cf54: stnp      x10, x11, [x3, #0x10]
00000001d031cf58: add       x3, x3, x2
00000001d031cf5c: stnp      x12, x13, [x3, #0x20]
00000001d031cf60: stnp      x14, x15, [x3, #0x30]
00000001d031cf64: ret
00000001d031cf68: add       x3, x3, #0x20
00000001d031cf6c: and       x3, x3, #0xffffffffffffffe0
00000001d031cf70: ldp       x12, x13, [x1]
00000001d031cf74: ldp       x14, x15, [x1, #0x10]
00000001d031cf78: sub       x5, x3, x0
00000001d031cf7c: add       x1, x1, x5
00000001d031cf80: ldp       x8, x9, [x1]
00000001d031cf84: ldp       x10, x11, [x1, #0x10]
00000001d031cf88: add       x1, x1, #0x20
00000001d031cf8c: sub       x2, x2, x5
00000001d031cf90: stp       x12, x13, [x0]
00000001d031cf94: stp       x14, x15, [x0, #0x10]
00000001d031cf98: subs      x2, x2, #0x40
00000001d031cf9c: b.ls      #0x1d031cfc0
00000001d031cfa0: stp       x8, x9, [x3]
00000001d031cfa4: stp       x10, x11, [x3, #0x10]
00000001d031cfa8: add       x3, x3, #0x20
00000001d031cfac: ldp       x8, x9, [x1]
00000001d031cfb0: ldp       x10, x11, [x1, #0x10]
00000001d031cfb4: add       x1, x1, #0x20
00000001d031cfb8: subs      x2, x2, #0x20
00000001d031cfbc: b.hi      #0x1d031cfa0
00000001d031cfc0: add       x1, x1, x2
00000001d031cfc4: ldp       x12, x13, [x1]
00000001d031cfc8: ldp       x14, x15, [x1, #0x10]
00000001d031cfcc: stp       x8, x9, [x3]
00000001d031cfd0: stp       x10, x11, [x3, #0x10]
00000001d031cfd4: add       x3, x3, x2
00000001d031cfd8: stp       x12, x13, [x3, #0x20]
00000001d031cfdc: stp       x14, x15, [x3, #0x30]
00000001d031cfe0: ret
00000001d031cfe4: ldr       x6, [x1], #8
00000001d031cfe8: str       x6, [x3], #8
00000001d031cfec: subs      x2, x2, #8
00000001d031cff0: b.hs      #0x1d031cfe4
00000001d031cff4: adds      x2, x2, #8
00000001d031cff8: b.eq      #0x1d031d00c
00000001d031cffc: ldrb      w6, [x1], #1
00000001d031d000: strb      w6, [x3], #1
00000001d031d004: subs      x2, x2, #1
00000001d031d008: b.ne      #0x1d031cffc
00000001d031d00c: ret
00000001d031d010: cbz       x3, #0x1d031d144
00000001d031d014: add       x4, x0, x2
00000001d031d018: add       x1, x1, x2
00000001d031d01c: cmp       x2, #0x40
00000001d031d020: b.lo      #0x1d031d124
00000001d031d024: cmp       x2, #4, lsl #12
00000001d031d028: b.lo      #0x1d031d0a4
00000001d031d02c: ldp       x12, x13, [x1, #-0x10]
00000001d031d030: ldp       x14, x15, [x1, #-0x20]
00000001d031d034: sub       x3, x4, #1
00000001d031d038: and       x3, x3, #0xffffffffffffffe0
00000001d031d03c: sub       x5, x4, x3
00000001d031d040: sub       x1, x1, x5
00000001d031d044: sub       x2, x2, x5
00000001d031d048: ldp       x8, x9, [x1, #-0x10]
00000001d031d04c: ldp       x10, x11, [x1, #-0x20]
00000001d031d050: stnp      x12, x13, [x4, #-0x10]
00000001d031d054: stnp      x14, x15, [x4, #-0x20]
00000001d031d058: sub       x1, x1, #0x20
00000001d031d05c: subs      x2, x2, #0x40
00000001d031d060: b.ls      #0x1d031d084
00000001d031d064: stnp      x8, x9, [x3, #-0x10]
00000001d031d068: stnp      x10, x11, [x3, #-0x20]
00000001d031d06c: sub       x3, x3, #0x20
00000001d031d070: ldp       x8, x9, [x1, #-0x10]
00000001d031d074: ldp       x10, x11, [x1, #-0x20]
00000001d031d078: sub       x1, x1, #0x20
00000001d031d07c: subs      x2, x2, #0x20
00000001d031d080: b.hi      #0x1d031d064
00000001d031d084: sub       x1, x1, x2
00000001d031d088: ldp       x12, x13, [x1, #-0x10]
00000001d031d08c: ldp       x14, x15, [x1, #-0x20]
00000001d031d090: stnp      x8, x9, [x3, #-0x10]
00000001d031d094: stnp      x10, x11, [x3, #-0x20]
00000001d031d098: stnp      x12, x13, [x0, #0x10]
00000001d031d09c: stnp      x14, x15, [x0]
00000001d031d0a0: ret
00000001d031d0a4: ldp       x12, x13, [x1, #-0x10]
00000001d031d0a8: ldp       x14, x15, [x1, #-0x20]
00000001d031d0ac: sub       x3, x4, #1
00000001d031d0b0: and       x3, x3, #0xffffffffffffffe0
00000001d031d0b4: sub       x5, x4, x3
00000001d031d0b8: sub       x1, x1, x5
00000001d031d0bc: sub       x2, x2, x5
00000001d031d0c0: ldp       x8, x9, [x1, #-0x10]
00000001d031d0c4: ldp       x10, x11, [x1, #-0x20]
00000001d031d0c8: stp       x12, x13, [x4, #-0x10]
00000001d031d0cc: stp       x14, x15, [x4, #-0x20]
00000001d031d0d0: sub       x1, x1, #0x20
00000001d031d0d4: subs      x2, x2, #0x40
00000001d031d0d8: b.ls      #0x1d031d0fc
00000001d031d0dc: stp       x8, x9, [x3, #-0x10]
00000001d031d0e0: stp       x10, x11, [x3, #-0x20]
00000001d031d0e4: sub       x3, x3, #0x20
00000001d031d0e8: ldp       x8, x9, [x1, #-0x10]
00000001d031d0ec: ldp       x10, x11, [x1, #-0x20]
00000001d031d0f0: sub       x1, x1, #0x20
00000001d031d0f4: subs      x2, x2, #0x20
00000001d031d0f8: b.hi      #0x1d031d0dc
00000001d031d0fc: sub       x1, x1, x2
00000001d031d100: ldp       x12, x13, [x1, #-0x10]
00000001d031d104: ldp       x14, x15, [x1, #-0x20]
00000001d031d108: stp       x8, x9, [x3, #-0x10]
00000001d031d10c: stp       x10, x11, [x3, #-0x20]
00000001d031d110: stp       x12, x13, [x0, #0x10]
00000001d031d114: stp       x14, x15, [x0]
00000001d031d118: ret
00000001d031d11c: ldr       x6, [x1, #-8]!
00000001d031d120: str       x6, [x4, #-8]!
00000001d031d124: subs      x2, x2, #8
00000001d031d128: b.hs      #0x1d031d11c
00000001d031d12c: adds      x2, x2, #8
00000001d031d130: b.eq      #0x1d031d144
00000001d031d134: ldrb      w6, [x1, #-1]!
00000001d031d138: strb      w6, [x4, #-1]!
00000001d031d13c: subs      x2, x2, #1
00000001d031d140: b.ne      #0x1d031d134
00000001d031d144: ret
