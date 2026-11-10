000000018829d99c: sub       sp, sp, #0x150
000000018829d9a0: stp       d9, d8, [sp, #0xe0]
000000018829d9a4: stp       x28, x27, [sp, #0xf0]
000000018829d9a8: stp       x26, x25, [sp, #0x100]
000000018829d9ac: stp       x24, x23, [sp, #0x110]
000000018829d9b0: stp       x22, x21, [sp, #0x120]
000000018829d9b4: stp       x20, x19, [sp, #0x130]
000000018829d9b8: stp       x29, x30, [sp, #0x140]
000000018829d9bc: add       x29, sp, #0x140
000000018829d9c0: add       x8, sp, #0xa0
000000018829d9c4: adrp      x9, #0x1daabe000
000000018829d9c8: ldr       x9, [x9, #0x7f0] ; [0x1daabe7f0]=0x201e1adb490
000000018829d9cc: ldr       x9, [x9]
000000018829d9d0: stur      x9, [x29, #-0x78]
000000018829d9d4: str       xzr, [x8, #0x20]
000000018829d9d8: movi      v0.16b, #0
000000018829d9dc: stp       q0, q0, [sp, #0xa0]
000000018829d9e0: mov       w20, #0x3f800000
000000018829d9e4: str       w20, [sp, #0xc0]
000000018829d9e8: str       xzr, [sp, #0x90]
000000018829d9ec: stp       q0, q0, [sp, #0x70]
000000018829d9f0: str       w20, [sp, #0x90]
000000018829d9f4: adrp      x19, #0x1dcc21000
000000018829d9f8: ldr       x8, [x19, #0xb70] ; [0x1dcc21b70]=0x0
000000018829d9fc: ldr       x8, [x8, #0x18]
000000018829da00: ucvtf     s0, x8
000000018829da04: fcvtzu    x1, s0
000000018829da08: add       x0, sp, #0xa0
000000018829da0c: bl        #0x1883b45b4 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE8__rehashILb1EEEvm
000000018829da10: adrp      x28, #0x1dcc21000
000000018829da14: ldr       x8, [x28, #0xb48] ; [0x1dcc21b48]=0x0
000000018829da18: ldr       x8, [x8, #0x18]
000000018829da1c: ucvtf     s0, x8
000000018829da20: fcvtzu    x1, s0
000000018829da24: add       x0, sp, #0x70
000000018829da28: bl        #0x1883b45b4 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE8__rehashILb1EEEvm
000000018829da2c: ldr       x8, [x19, #0xb70] ; [0x1dcc21b70]=0x0
000000018829da30: ldr       x21, [x8, #0x10]
000000018829da34: cbz       x21, #0x18829dab4
000000018829da38: ldr       x19, [x21, #0x10]
000000018829da3c: add       x0, sp, #0xa0
000000018829da40: mov       x1, x19
000000018829da44: bl        #0x1882b7e48 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE4findIyEENS_15__hash_iteratorIPNS_11__hash_nodeIyPvEEEERKT_
000000018829da48: cbnz      x0, #0x18829daac
000000018829da4c: add       x0, sp, #0x70
000000018829da50: mov       x1, x19
000000018829da54: bl        #0x1882b7e48 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE4findIyEENS_15__hash_iteratorIPNS_11__hash_nodeIyPvEEEERKT_
000000018829da58: cbnz      x0, #0x18829daac
000000018829da5c: str       xzr, [sp, #0x60]
000000018829da60: movi      v0.16b, #0
000000018829da64: stp       q0, q0, [sp, #0x40]
000000018829da68: str       w20, [sp, #0x60]
000000018829da6c: add       x1, sp, #0x40
000000018829da70: add       x2, sp, #0xa0
000000018829da74: add       x3, sp, #0x70
000000018829da78: mov       x0, x19
000000018829da7c: bl        #0x188281f44 ; call __ZN2CA6Render5FenceL17is_fence_resolvedEyRNSt3__113unordered_setIyNS2_4hashIyEENS2_8equal_toIyEENS2_9allocatorIyEEEERKSA_SB_
000000018829da80: cbz       w0, #0x18829daa4
000000018829da84: ldr       x19, [sp, #0x50]
000000018829da88: cbz       x19, #0x18829daa4
000000018829da8c: add       x1, x19, #0x10
000000018829da90: add       x0, sp, #0xa0
000000018829da94: mov       x2, x1
000000018829da98: bl        #0x1882e0cf4 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE25__emplace_unique_key_argsIyJRKyEEENS_4pairINS_15__hash_iteratorIPNS_11__hash_nodeIyPvEEEEbEERKT_DpOT0_
000000018829da9c: ldr       x19, [x19]
000000018829daa0: cbnz      x19, #0x18829da8c
000000018829daa4: add       x0, sp, #0x40
000000018829daa8: bl        #0x188261f58 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEED2Ev
000000018829daac: ldr       x21, [x21]
000000018829dab0: cbnz      x21, #0x18829da38
000000018829dab4: ldr       x19, [sp, #0xb8]
000000018829dab8: cbz       x19, #0x18829e6e4
000000018829dabc: adrp      x8, #0x1dcc20000
000000018829dac0: ldr       w9, [x8, #0x410] ; [0x1dcc20410]=0x0
000000018829dac4: add       w9, w9, #1
000000018829dac8: str       x9, [sp, #0x10]
000000018829dacc: str       w9, [x8, #0x410]
000000018829dad0: adrp      x8, #0x1dcc21000
000000018829dad4: ldr       x8, [x8, #0xb88] ; [0x1dcc21b88]=0x0
000000018829dad8: cmn       x8, #1
000000018829dadc: b.ne      #0x18829e73c
000000018829dae0: str       x19, [sp, #8]
000000018829dae4: str       wzr, [sp, #0x40]
000000018829dae8: adrp      x27, #0x1daac1000
000000018829daec: ldr       x27, [x27, #0x330] ; [0x1daac1330]=0x201e1ad9870
000000018829daf0: ldr       w0, [x27]
000000018829daf4: add       x2, sp, #0x40
000000018829daf8: mov       w1, #1
000000018829dafc: bl        #0x18db39000 ; call _mach_port_allocate
000000018829db00: cbz       w0, #0x18829db0c
000000018829db04: mov       x19, #0
000000018829db08: b         #0x18829df68
000000018829db0c: bl        #0x18db38fac ; call _mach_absolute_time
000000018829db10: bl        #0x188236490 ; call _CATimeWithHostTime
000000018829db14: fmov      d1, #0.50000000
000000018829db18: fadd      d8, d0, d1
000000018829db1c: bl        #0x188238ad0 ; call __ZL15get_malloc_zonev
000000018829db20: mov       w1, #0x20
000000018829db24: bl        #0x18db390fc ; call _malloc_zone_malloc
000000018829db28: mov       x19, x0
000000018829db2c: ldr       w20, [sp, #0x40]
000000018829db30: str       w20, [x0, #0x18]
000000018829db34: str       d8, [x0]
000000018829db38: str       xzr, [x0, #8]
000000018829db3c: mov       w0, #0x28
000000018829db40: bl        #0x1884c9194 ; call __Znwm
000000018829db44: movi      v0.16b, #0
000000018829db48: stp       q0, q0, [x0]
000000018829db4c: mov       w8, #0x3f800000
000000018829db50: str       w8, [x0, #0x20]
000000018829db54: str       x0, [x19, #0x10]
000000018829db58: adrp      x8, #0x1dcc21000
000000018829db5c: ldr       x24, [x8, #0x648] ; [0x1dcc21648]=0x0
000000018829db60: ldr       x21, [x24, #8]
000000018829db64: cbz       x21, #0x18829db8c
000000018829db68: fmov      d0, x21
000000018829db6c: cnt       v0.8b, v0.8b
000000018829db70: uaddlv    h0, v0.8b
000000018829db74: fmov      w8, s0
000000018829db78: cmp       x8, #1
000000018829db7c: b.hi      #0x18829db94
000000018829db80: sub       w9, w21, #1
000000018829db84: and       x23, x9, x20
000000018829db88: b         #0x18829dba8
000000018829db8c: mov       x23, #0
000000018829db90: b         #0x18829dc04
000000018829db94: mov       x23, x20
000000018829db98: cmp       x21, x20
000000018829db9c: b.hi      #0x18829dba8
000000018829dba0: udiv      x9, x20, x21
000000018829dba4: msub      x23, x9, x21, x20
000000018829dba8: ldr       x9, [x24]
000000018829dbac: ldr       x22, [x9, x23, lsl #3]
000000018829dbb0: cbz       x22, #0x18829dc04
000000018829dbb4: sub       x9, x21, #1
000000018829dbb8: ldr       x22, [x22]
000000018829dbbc: cbz       x22, #0x18829dc04
000000018829dbc0: ldr       x10, [x22, #8]
000000018829dbc4: cmp       x10, x20
000000018829dbc8: b.eq      #0x18829dbf4
000000018829dbcc: cmp       x8, #1
000000018829dbd0: b.hi      #0x18829dbdc
000000018829dbd4: and       x10, x10, x9
000000018829dbd8: b         #0x18829dbec
000000018829dbdc: cmp       x10, x21
000000018829dbe0: b.lo      #0x18829dbec
000000018829dbe4: udiv      x11, x10, x21
000000018829dbe8: msub      x10, x11, x21, x10
000000018829dbec: cmp       x10, x23
000000018829dbf0: b.ne      #0x18829dc04
000000018829dbf4: ldr       w10, [x22, #0x10]
000000018829dbf8: cmp       w10, w20
000000018829dbfc: b.ne      #0x18829dbb8
000000018829dc00: b         #0x18829dee8
000000018829dc04: mov       w0, #0x20
000000018829dc08: bl        #0x1884c9194 ; call __Znwm
000000018829dc0c: mov       x22, x0
000000018829dc10: str       w20, [x0, #0x10]
000000018829dc14: str       xzr, [x0, #0x18]
000000018829dc18: stp       xzr, x20, [x0]
000000018829dc1c: ldr       x8, [x24, #0x18]
000000018829dc20: add       x8, x8, #1
000000018829dc24: ucvtf     s0, x8
000000018829dc28: ucvtf     s2, x21
000000018829dc2c: ldr       s1, [x24, #0x20]
000000018829dc30: fmul      s2, s1, s2
000000018829dc34: fcmp      s2, s0
000000018829dc38: ccmp      x21, #0, #4, pl
000000018829dc3c: b.ne      #0x18829de70
000000018829dc40: lsl       x8, x21, #1
000000018829dc44: mov       w9, #1
000000018829dc48: sub       x10, x21, #1
000000018829dc4c: tst       x21, x10
000000018829dc50: cset      w10, ne
000000018829dc54: cmp       x21, #3
000000018829dc58: csel      x9, x9, x10, lo
000000018829dc5c: orr       x8, x9, x8
000000018829dc60: fdiv      s0, s0, s1
000000018829dc64: fcvtpu    x9, s0
000000018829dc68: cmp       x8, x9
000000018829dc6c: csel      x23, x8, x9, hi
000000018829dc70: subs      x8, x23, #1
000000018829dc74: b.ne      #0x18829dc80
000000018829dc78: mov       w23, #2
000000018829dc7c: b         #0x18829dc94
000000018829dc80: tst       x23, x8
000000018829dc84: b.eq      #0x18829dc94
000000018829dc88: mov       x0, x23
000000018829dc8c: bl        #0x18db388f8 ; call __ZNSt3__112__next_primeEm
000000018829dc90: mov       x23, x0
000000018829dc94: ldr       x21, [x24, #8]
000000018829dc98: cmp       x23, x21
000000018829dc9c: b.ls      #0x18829dd14
000000018829dca0: lsr       x8, x23, #0x3d
000000018829dca4: cbnz      x8, #0x18829e760
000000018829dca8: lsl       x0, x23, #3
000000018829dcac: bl        #0x1884c9194 ; call __Znwm
000000018829dcb0: mov       x8, x0
000000018829dcb4: ldr       x0, [x24]
000000018829dcb8: str       x8, [x24]
000000018829dcbc: cbz       x0, #0x18829dcc4
000000018829dcc0: bl        #0x1884c917c ; call __ZdlPv
000000018829dcc4: mov       x8, #0
000000018829dcc8: str       x23, [x24, #8]
000000018829dccc: ldr       x9, [x24]
000000018829dcd0: str       xzr, [x9, x8, lsl #3]
000000018829dcd4: add       x8, x8, #1
000000018829dcd8: cmp       x23, x8
000000018829dcdc: b.ne      #0x18829dccc
000000018829dce0: mov       x11, x24
000000018829dce4: ldr       x9, [x11, #0x10]!
000000018829dce8: cbz       x9, #0x18829de3c
000000018829dcec: ldr       x10, [x9, #8]
000000018829dcf0: fmov      d0, x23
000000018829dcf4: cnt       v0.8b, v0.8b
000000018829dcf8: uaddlv    h0, v0.8b
000000018829dcfc: fmov      w8, s0
000000018829dd00: cmp       x8, #1
000000018829dd04: b.hi      #0x18829dd6c
000000018829dd08: sub       x12, x23, #1
000000018829dd0c: and       x10, x10, x12
000000018829dd10: b         #0x18829dd7c
000000018829dd14: b.hs      #0x18829de3c
000000018829dd18: ldr       x8, [x24, #0x18]
000000018829dd1c: ucvtf     s0, x8
000000018829dd20: ldr       s1, [x24, #0x20]
000000018829dd24: fdiv      s0, s0, s1
000000018829dd28: fcvtpu    x0, s0
000000018829dd2c: cmp       x21, #3
000000018829dd30: b.lo      #0x18829de10
000000018829dd34: fmov      d0, x21
000000018829dd38: cnt       v0.8b, v0.8b
000000018829dd3c: uaddlv    h0, v0.8b
000000018829dd40: fmov      w8, s0
000000018829dd44: cmp       x8, #1
000000018829dd48: b.hi      #0x18829de10
000000018829dd4c: sub       x8, x0, #1
000000018829dd50: clz       x8, x8
000000018829dd54: neg       x8, x8
000000018829dd58: mov       w9, #1
000000018829dd5c: lsl       x8, x9, x8
000000018829dd60: cmp       x0, #2
000000018829dd64: csel      x0, x0, x8, lo
000000018829dd68: b         #0x18829de14
000000018829dd6c: cmp       x10, x23
000000018829dd70: b.lo      #0x18829dd7c
000000018829dd74: udiv      x12, x10, x23
000000018829dd78: msub      x10, x12, x23, x10
000000018829dd7c: ldr       x12, [x24]
000000018829dd80: str       x11, [x12, x10, lsl #3]
000000018829dd84: ldr       x11, [x9]
000000018829dd88: cbz       x11, #0x18829de3c
000000018829dd8c: sub       x12, x23, #1
000000018829dd90: ldr       x13, [x11, #8]
000000018829dd94: cmp       x8, #1
000000018829dd98: b.hi      #0x18829dda4
000000018829dd9c: and       x13, x13, x12
000000018829dda0: b         #0x18829ddb4
000000018829dda4: cmp       x13, x23
000000018829dda8: b.lo      #0x18829ddb4
000000018829ddac: udiv      x14, x13, x23
000000018829ddb0: msub      x13, x14, x23, x13
000000018829ddb4: cmp       x13, x10
000000018829ddb8: b.eq      #0x18829ddf0
000000018829ddbc: ldr       x14, [x24]
000000018829ddc0: ldr       x15, [x14, x13, lsl #3]
000000018829ddc4: cbz       x15, #0x18829de08
000000018829ddc8: ldr       x14, [x11]
000000018829ddcc: str       x14, [x9]
000000018829ddd0: ldr       x14, [x24]
000000018829ddd4: ldr       x14, [x14, x13, lsl #3]
000000018829ddd8: ldr       x14, [x14]
000000018829dddc: str       x14, [x11]
000000018829dde0: ldr       x14, [x24]
000000018829dde4: ldr       x13, [x14, x13, lsl #3]
000000018829dde8: str       x11, [x13]
000000018829ddec: mov       x11, x9
000000018829ddf0: mov       x13, x10
000000018829ddf4: mov       x9, x11
000000018829ddf8: ldr       x11, [x11]
000000018829ddfc: mov       x10, x13
000000018829de00: cbnz      x11, #0x18829dd90
000000018829de04: b         #0x18829de3c
000000018829de08: str       x9, [x14, x13, lsl #3]
000000018829de0c: b         #0x18829ddf4
000000018829de10: bl        #0x18db388f8 ; call __ZNSt3__112__next_primeEm
000000018829de14: cmp       x23, x0
000000018829de18: csel      x23, x23, x0, hi
000000018829de1c: cmp       x23, x21
000000018829de20: b.hs      #0x18829de3c
000000018829de24: cbnz      x23, #0x18829dca0
000000018829de28: ldr       x0, [x24]
000000018829de2c: str       xzr, [x24]
000000018829de30: cbz       x0, #0x18829de38
000000018829de34: bl        #0x1884c917c ; call __ZdlPv
000000018829de38: str       xzr, [x24, #8]
000000018829de3c: ldr       x21, [x24, #8]
000000018829de40: sub       x8, x21, #1
000000018829de44: tst       x21, x8
000000018829de48: b.ne      #0x18829de58
000000018829de4c: sub       w8, w21, #1
000000018829de50: and       x23, x8, x20
000000018829de54: b         #0x18829de70
000000018829de58: cmp       x21, x20
000000018829de5c: b.ls      #0x18829de68
000000018829de60: mov       x23, x20
000000018829de64: b         #0x18829de70
000000018829de68: udiv      x8, x20, x21
000000018829de6c: msub      x23, x8, x21, x20
000000018829de70: ldr       x8, [x24]
000000018829de74: ldr       x9, [x8, x23, lsl #3]
000000018829de78: cbz       x9, #0x18829de8c
000000018829de7c: ldr       x8, [x9]
000000018829de80: str       x8, [x22]
000000018829de84: str       x22, [x9]
000000018829de88: b         #0x18829ded8
000000018829de8c: mov       x9, x24
000000018829de90: ldr       x10, [x9, #0x10]!
000000018829de94: str       x10, [x22]
000000018829de98: str       x22, [x9]
000000018829de9c: str       x9, [x8, x23, lsl #3]
000000018829dea0: ldr       x8, [x22]
000000018829dea4: cbz       x8, #0x18829ded8
000000018829dea8: ldr       x8, [x8, #8]
000000018829deac: sub       x9, x21, #1
000000018829deb0: tst       x21, x9
000000018829deb4: b.ne      #0x18829dec0
000000018829deb8: and       x8, x8, x9
000000018829debc: b         #0x18829ded0
000000018829dec0: cmp       x8, x21
000000018829dec4: b.lo      #0x18829ded0
000000018829dec8: udiv      x9, x8, x21
000000018829decc: msub      x8, x9, x21, x8
000000018829ded0: ldr       x9, [x24]
000000018829ded4: str       x22, [x9, x8, lsl #3]
000000018829ded8: ldr       x8, [x24, #0x18]
000000018829dedc: add       x8, x8, #1
000000018829dee0: str       x8, [x24, #0x18]
000000018829dee4: ldr       w20, [sp, #0x40]
000000018829dee8: str       x19, [x22, #0x18]
000000018829deec: ldr       w0, [x27]
000000018829def0: mov       x1, x20
000000018829def4: mov       x2, x20
000000018829def8: mov       w3, #0x14
000000018829defc: bl        #0x18db39030 ; call _mach_port_insert_right
000000018829df00: str       wzr, [sp, #0x3c]
000000018829df04: ldr       w20, [x27]
000000018829df08: ldr       w22, [sp, #0x40]
000000018829df0c: bl        #0x188239588 ; call __ZN2CA6Render6Server11notify_portEv
000000018829df10: mov       x4, x0
000000018829df14: add       x6, sp, #0x3c
000000018829df18: mov       x0, x20
000000018829df1c: mov       x1, x22
000000018829df20: mov       w2, #0x46
000000018829df24: mov       w3, #0
000000018829df28: mov       w5, #0x15
000000018829df2c: bl        #0x18db39054 ; call _mach_port_request_notification
000000018829df30: ldr       w1, [sp, #0x40]
000000018829df34: mov       w8, #0x202
000000018829df38: movk      w8, #0x31ca, lsl #16
000000018829df3c: add       w0, w8, #0x37
000000018829df40: mov       x2, #0
000000018829df44: mov       x3, #0
000000018829df48: mov       x4, #0
000000018829df4c: bl        #0x18db38f70 ; call _kdebug_trace
000000018829df50: adrp      x1, #0x188497000
000000018829df54: add       x1, x1, #0x53c
000000018829df58: fmov      d0, d8
000000018829df5c: mov       w0, #3
000000018829df60: mov       x2, #0
000000018829df64: bl        #0x18829cfdc ; call __ZN2CA6Render6Server12add_callbackEdNS1_16CallbackBehaviorEPFvdPvES3_ | x1 literal: __ZN2CA6Render5FenceL17btimeout_callbackEdPv
000000018829df68: adrp      x8, #0x1dcc21000
000000018829df6c: ldr       x8, [x8, #0x678] ; [0x1dcc21678]=0x0
000000018829df70: ldr       x20, [x8, #0x10]
000000018829df74: cbz       x20, #0x18829e2d8
000000018829df78: add       x22, x19, #0x18
000000018829df7c: ldr       x21, [x20, #0x18]
000000018829df80: ldp       x24, x25, [x21]
000000018829df84: ldp       x26, x8, [x25]
000000018829df88: cmp       x26, x8
000000018829df8c: b.eq      #0x18829e27c
000000018829df90: stp       x21, x20, [sp, #0x18]
000000018829df94: add       x9, x24, #0x2b0
000000018829df98: add       x8, x24, #0x2b8
000000018829df9c: stp       x8, x9, [sp, #0x28]
000000018829dfa0: add       x28, x24, #8
000000018829dfa4: ldr       x21, [sp, #0xb0]
000000018829dfa8: cbnz      x21, #0x18829dfc4
000000018829dfac: b         #0x18829e130
000000018829dfb0: ldaxr     w8, [x28]
000000018829dfb4: sub       w8, w8, #1
000000018829dfb8: stlxr     w9, w8, [x28]
000000018829dfbc: cbnz      w9, #0x18829dfb0
000000018829dfc0: b         #0x18829e0b0
000000018829dfc4: ldr       x20, [x21, #0x10]
000000018829dfc8: mov       x0, x26
000000018829dfcc: mov       x1, x20
000000018829dfd0: bl        #0x1882b7e48 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE4findIyEENS_15__hash_iteratorIPNS_11__hash_nodeIyPvEEEERKT_
000000018829dfd4: cbz       x0, #0x18829e128
000000018829dfd8: cbz       x19, #0x18829e11c
000000018829dfdc: ldrb      w8, [x24, #0xd]
000000018829dfe0: tbnz      w8, #2, #0x18829e11c
000000018829dfe4: ldr       w8, [x24, #0x10]
000000018829dfe8: str       w8, [sp, #0x3c]
000000018829dfec: ldr       x0, [x19, #0x10]
000000018829dff0: add       x1, sp, #0x3c
000000018829dff4: bl        #0x1882d2ed0 ; call __ZNSt3__112__hash_tableIjNS_4hashIjEENS_8equal_toIjEENS_9allocatorIjEEE4findIjEENS_15__hash_iteratorIPNS_11__hash_nodeIjPvEEEERKT_
000000018829dff8: cbnz      x0, #0x18829e11c
000000018829dffc: ldr       x0, [x19, #0x10]
000000018829e000: add       x1, sp, #0x3c
000000018829e004: add       x2, sp, #0x3c
000000018829e008: bl        #0x1882dff80 ; call __ZNSt3__112__hash_tableIjNS_4hashIjEENS_8equal_toIjEENS_9allocatorIjEEE25__emplace_unique_key_argsIjJRKjEEENS_4pairINS_15__hash_iteratorIPNS_11__hash_nodeIjPvEEEEbEERKT_DpOT0_
000000018829e00c: ldr       w1, [sp, #0x3c]
000000018829e010: ldr       w2, [x19, #0x18]
000000018829e014: mov       w8, #0x202
000000018829e018: movk      w8, #0x31ca, lsl #16
000000018829e01c: add       w0, w8, #0x17
000000018829e020: mov       x3, #0
000000018829e024: mov       x4, #0
000000018829e028: bl        #0x18db38f70 ; call _kdebug_trace
000000018829e02c: ldr       w8, [x19, #0x18]
000000018829e030: str       w8, [sp, #0x40]
000000018829e034: sub       w8, w8, #1
000000018829e038: cmn       w8, #3
000000018829e03c: b.hi      #0x18829e080
000000018829e040: ldr       x27, [sp, #0x30]
000000018829e044: mov       x0, x27
000000018829e048: bl        #0x18db39534 ; call _os_unfair_lock_lock
000000018829e04c: ldr       x23, [x24, #0x2d0]
000000018829e050: add       x1, sp, #0x40
000000018829e054: add       x2, sp, #0x40
000000018829e058: ldr       x0, [sp, #0x28]
000000018829e05c: bl        #0x1882dff80 ; call __ZNSt3__112__hash_tableIjNS_4hashIjEENS_8equal_toIjEENS_9allocatorIjEEE25__emplace_unique_key_argsIjJRKjEEENS_4pairINS_15__hash_iteratorIPNS_11__hash_nodeIjPvEEEEbEERKT_DpOT0_
000000018829e060: mov       x0, x27
000000018829e064: bl        #0x18db3954c ; call _os_unfair_lock_unlock
000000018829e068: cbnz      x23, #0x18829e080
000000018829e06c: mov       w0, #6
000000018829e070: mov       x1, x24
000000018829e074: mov       x2, #0
000000018829e078: mov       w3, #0
000000018829e07c: bl        #0x18823777c ; call __ZN2CA6Render17post_notificationENS0_16NotificationNameEPNS0_6ObjectEPvb
000000018829e080: adrp      x8, #0x1dcc21000
000000018829e084: ldr       x0, [x8, #0x660] ; [0x1dcc21660]=0x0
000000018829e088: ldr       w1, [sp, #0x3c]
000000018829e08c: bl        #0x188497800 ; call __ZNSt3__112__hash_tableINS_17__hash_value_typeIjPN2CA6Render5Fence16BatchContextInfoEEENS_22__unordered_map_hasherIjS7_NS_4hashIjEENS_8equal_toIjEELb1EEENS_21__unordered_map_equalIjS7_SC_SA_Lb1EEENS_9allocatorIS7_EEE4findIjEENS_15__hash_iteratorIPNS_11__hash_nodeIS7_PvEEEERKT_
000000018829e090: cbz       x0, #0x18829e09c
000000018829e094: ldr       x23, [x0, #0x18]
000000018829e098: b         #0x18829e10c
000000018829e09c: ldaxr     w8, [x28]
000000018829e0a0: add       w9, w8, #1
000000018829e0a4: stlxr     w10, w9, [x28]
000000018829e0a8: cbnz      w10, #0x18829e09c
000000018829e0ac: cbz       w8, #0x18829dfb0
000000018829e0b0: bl        #0x188238ad0 ; call __ZL15get_malloc_zonev
000000018829e0b4: mov       w1, #0x18
000000018829e0b8: bl        #0x18db390fc ; call _malloc_zone_malloc
000000018829e0bc: mov       x23, x0
000000018829e0c0: str       x24, [x0]
000000018829e0c4: mov       w0, #0x18
000000018829e0c8: bl        #0x1884c9194 ; call __Znwm
000000018829e0cc: stp       xzr, xzr, [x0, #8]
000000018829e0d0: str       xzr, [x0]
000000018829e0d4: str       x0, [x23, #8]
000000018829e0d8: mov       w0, #0x28
000000018829e0dc: bl        #0x1884c9194 ; call __Znwm
000000018829e0e0: movi      v0.16b, #0
000000018829e0e4: stp       q0, q0, [x0]
000000018829e0e8: mov       w8, #0x3f800000
000000018829e0ec: str       w8, [x0, #0x20]
000000018829e0f0: str       x0, [x23, #0x10]
000000018829e0f4: adrp      x8, #0x1dcc21000
000000018829e0f8: ldr       x0, [x8, #0x660] ; [0x1dcc21660]=0x0
000000018829e0fc: ldr       w1, [sp, #0x3c]
000000018829e100: add       x2, sp, #0x3c
000000018829e104: bl        #0x1884978b4 ; call __ZNSt3__112__hash_tableINS_17__hash_value_typeIjPN2CA6Render5Fence16BatchContextInfoEEENS_22__unordered_map_hasherIjS7_NS_4hashIjEENS_8equal_toIjEELb1EEENS_21__unordered_map_equalIjS7_SC_SA_Lb1EEENS_9allocatorIS7_EEE25__emplace_unique_key_argsIjJRKNS_21piecewise_construct_tENS_5tupleIJRKjEEENSN_IJEEEEEENS_4pairINS_15__hash_iteratorIPNS_11__hash_nodeIS7_PvEEEEbEERKT_DpOT0_
000000018829e108: str       x23, [x0, #0x18]
000000018829e10c: ldr       x0, [x23, #0x10]
000000018829e110: mov       x1, x22
000000018829e114: mov       x2, x22
000000018829e118: bl        #0x1882dff80 ; call __ZNSt3__112__hash_tableIjNS_4hashIjEENS_8equal_toIjEENS_9allocatorIjEEE25__emplace_unique_key_argsIjJRKjEEENS_4pairINS_15__hash_iteratorIPNS_11__hash_nodeIjPvEEEEbEERKT_DpOT0_
000000018829e11c: mov       x0, x26
000000018829e120: mov       x1, x20
000000018829e124: bl        #0x1882dc990 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE14__erase_uniqueIyEEmRKT_
000000018829e128: ldr       x21, [x21]
000000018829e12c: cbnz      x21, #0x18829dfc4
000000018829e130: ldr       x8, [x26, #0x18]
000000018829e134: cbz       x8, #0x18829e144
000000018829e138: add       x26, x26, #0x28
000000018829e13c: ldr       x21, [x25, #8]
000000018829e140: b         #0x18829e24c
000000018829e144: add       x20, x26, #0x28
000000018829e148: ldr       x23, [x25, #8]
000000018829e14c: mov       x21, x26
000000018829e150: cmp       x20, x23
000000018829e154: b.eq      #0x18829e240
000000018829e158: ldr       x8, [x21, #0x18]
000000018829e15c: cbz       x8, #0x18829e1a0
000000018829e160: ldr       x0, [x21, #0x10]
000000018829e164: cbz       x0, #0x18829e178
000000018829e168: ldr       x27, [x0]
000000018829e16c: bl        #0x1884c917c ; call __ZdlPv
000000018829e170: mov       x0, x27
000000018829e174: cbnz      x27, #0x18829e168
000000018829e178: str       xzr, [x21, #0x10]
000000018829e17c: ldr       x8, [x21, #8]
000000018829e180: cbz       x8, #0x18829e19c
000000018829e184: mov       x9, #0
000000018829e188: ldr       x10, [x21]
000000018829e18c: str       xzr, [x10, x9, lsl #3]
000000018829e190: add       x9, x9, #1
000000018829e194: cmp       x8, x9
000000018829e198: b.ne      #0x18829e188
000000018829e19c: str       xzr, [x21, #0x18]
000000018829e1a0: ldr       x8, [x20]
000000018829e1a4: str       xzr, [x20]
000000018829e1a8: ldr       x0, [x21]
000000018829e1ac: str       x8, [x21]
000000018829e1b0: cbz       x0, #0x18829e1b8
000000018829e1b4: bl        #0x1884c917c ; call __ZdlPv
000000018829e1b8: mov       x8, x20
000000018829e1bc: ldr       x11, [x8, #0x10]!
000000018829e1c0: ldur      x10, [x8, #-8]
000000018829e1c4: mov       x9, x21
000000018829e1c8: str       x11, [x9, #0x10]!
000000018829e1cc: stur      x10, [x9, #-8]
000000018829e1d0: stur      xzr, [x8, #-8]
000000018829e1d4: ldr       x12, [x8, #8]
000000018829e1d8: str       x12, [x9, #8]
000000018829e1dc: ldr       s0, [x8, #0x10]
000000018829e1e0: str       s0, [x9, #0x10]
000000018829e1e4: cbz       x12, #0x18829e21c
000000018829e1e8: ldr       x11, [x11, #8]
000000018829e1ec: sub       x12, x10, #1
000000018829e1f0: tst       x10, x12
000000018829e1f4: b.ne      #0x18829e200
000000018829e1f8: and       x11, x12, x11
000000018829e1fc: b         #0x18829e210
000000018829e200: cmp       x11, x10
000000018829e204: b.lo      #0x18829e210
000000018829e208: udiv      x12, x11, x10
000000018829e20c: msub      x11, x12, x10, x11
000000018829e210: ldr       x10, [x21]
000000018829e214: str       x9, [x10, x11, lsl #3]
000000018829e218: stp       xzr, xzr, [x8]
000000018829e21c: add       x20, x20, #0x28
000000018829e220: add       x21, x21, #0x28
000000018829e224: cmp       x20, x23
000000018829e228: b.ne      #0x18829e158
000000018829e22c: ldr       x20, [x25, #8]
000000018829e230: b         #0x18829e240
000000018829e234: sub       x20, x20, #0x28
000000018829e238: mov       x0, x20
000000018829e23c: bl        #0x188261f58 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEED2Ev
000000018829e240: cmp       x20, x21
000000018829e244: b.ne      #0x18829e234
000000018829e248: str       x21, [x25, #8]
000000018829e24c: cmp       x26, x21
000000018829e250: b.ne      #0x18829dfa4
000000018829e254: ldr       x8, [x25]
000000018829e258: cmp       x8, x21
000000018829e25c: adrp      x27, #0x1daac1000
000000018829e260: ldr       x27, [x27, #0x330] ; [0x1daac1330]=0x201e1ad9870
000000018829e264: adrp      x28, #0x1dcc21000
000000018829e268: ldp       x21, x20, [sp, #0x18]
000000018829e26c: b.eq      #0x18829e27c
000000018829e270: ldr       x20, [x20]
000000018829e274: cbnz      x20, #0x18829df7c
000000018829e278: b         #0x18829e2d8
000000018829e27c: mov       x0, x25
000000018829e280: bl        #0x188497c88 ; call __ZNSt3__16vectorINS_13unordered_setIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEEENS6_IS8_EEED2B6v15006Ev
000000018829e284: bl        #0x1884c917c ; call __ZdlPv
000000018829e288: cbz       x24, #0x18829e2b4
000000018829e28c: add       x8, x24, #8
000000018829e290: ldaxr     w9, [x8]
000000018829e294: subs      w9, w9, #1
000000018829e298: stlxr     w10, w9, [x8]
000000018829e29c: cbnz      w10, #0x18829e290
000000018829e2a0: b.ne      #0x18829e2b4
000000018829e2a4: ldr       x8, [x24]
000000018829e2a8: ldr       x8, [x8, #0x10]
000000018829e2ac: mov       x0, x24
000000018829e2b0: blr       x8
000000018829e2b4: bl        #0x188238ad0 ; call __ZL15get_malloc_zonev
000000018829e2b8: mov       x1, x21
000000018829e2bc: bl        #0x18db390f0 ; call _malloc_zone_free
000000018829e2c0: adrp      x8, #0x1dcc21000
000000018829e2c4: ldr       x0, [x8, #0x678] ; [0x1dcc21678]=0x0
000000018829e2c8: mov       x1, x20
000000018829e2cc: bl        #0x188497ce0 ; call __ZNSt3__112__hash_tableINS_17__hash_value_typeIjPN2CA6Render5Fence16FenceContextInfoEEENS_22__unordered_map_hasherIjS7_NS_4hashIjEENS_8equal_toIjEELb1EEENS_21__unordered_map_equalIjS7_SC_SA_Lb1EEENS_9allocatorIS7_EEE5eraseENS_21__hash_const_iteratorIPNS_11__hash_nodeIS7_PvEEEE
000000018829e2d0: mov       x20, x0
000000018829e2d4: cbnz      x20, #0x18829df7c
000000018829e2d8: ldr       x23, [sp, #0xb0]
000000018829e2dc: cbz       x23, #0x18829e5c8
000000018829e2e0: adrp      x24, #0x1dcc21000
000000018829e2e4: ldr       x22, [x23, #0x10]
000000018829e2e8: ldr       x0, [x28, #0xb48]
000000018829e2ec: mov       x1, x22
000000018829e2f0: bl        #0x1882f157c ; call __ZNSt3__112__hash_tableINS_17__hash_value_typeIyPN2CA6Render5Fence9FenceInfoEEENS_22__unordered_map_hasherIyS7_NS_4hashIyEENS_8equal_toIyEELb1EEENS_21__unordered_map_equalIyS7_SC_SA_Lb1EEENS_9allocatorIS7_EEE4findIyEENS_15__hash_iteratorIPNS_11__hash_nodeIS7_PvEEEERKT_
000000018829e2f4: cbz       x0, #0x18829e758
000000018829e2f8: ldr       x21, [x0, #0x18]
000000018829e2fc: ldr       x1, [x21]
000000018829e300: ldr       w3, [x19, #0x18]
000000018829e304: mov       w0, #0x202
000000018829e308: movk      w0, #0x31ca, lsl #16
000000018829e30c: ldr       x2, [sp, #0x10]
000000018829e310: mov       x4, #0
000000018829e314: bl        #0x18db38f70 ; call _kdebug_trace
000000018829e318: ldr       x20, [x28, #0xb48]
000000018829e31c: mov       x0, x20
000000018829e320: mov       x1, x22
000000018829e324: bl        #0x1882f157c ; call __ZNSt3__112__hash_tableINS_17__hash_value_typeIyPN2CA6Render5Fence9FenceInfoEEENS_22__unordered_map_hasherIyS7_NS_4hashIyEENS_8equal_toIyEELb1EEENS_21__unordered_map_equalIyS7_SC_SA_Lb1EEENS_9allocatorIS7_EEE4findIyEENS_15__hash_iteratorIPNS_11__hash_nodeIS7_PvEEEERKT_
000000018829e328: cbz       x0, #0x18829e454
000000018829e32c: ldr       x9, [x20, #8]
000000018829e330: ldr       x8, [x0, #8]
000000018829e334: fmov      d0, x9
000000018829e338: cnt       v0.8b, v0.8b
000000018829e33c: uaddlv    h0, v0.8b
000000018829e340: fmov      w11, s0
000000018829e344: cmp       x11, #1
000000018829e348: b.hi      #0x18829e358
000000018829e34c: sub       x10, x9, #1
000000018829e350: and       x8, x10, x8
000000018829e354: b         #0x18829e368
000000018829e358: cmp       x8, x9
000000018829e35c: b.lo      #0x18829e368
000000018829e360: udiv      x10, x8, x9
000000018829e364: msub      x8, x10, x9, x8
000000018829e368: ldr       x12, [x20]
000000018829e36c: ldr       x13, [x12, x8, lsl #3]
000000018829e370: mov       x10, x13
000000018829e374: ldr       x13, [x13]
000000018829e378: cmp       x13, x0
000000018829e37c: b.ne      #0x18829e370
000000018829e380: add       x13, x20, #0x10
000000018829e384: cmp       x10, x13
000000018829e388: b.eq      #0x18829e3bc
000000018829e38c: ldr       x13, [x10, #8]
000000018829e390: cmp       x11, #1
000000018829e394: b.hi      #0x18829e3a4
000000018829e398: sub       x14, x9, #1
000000018829e39c: and       x13, x13, x14
000000018829e3a0: b         #0x18829e3b4
000000018829e3a4: cmp       x13, x9
000000018829e3a8: b.lo      #0x18829e3b4
000000018829e3ac: udiv      x14, x13, x9
000000018829e3b0: msub      x13, x14, x9, x13
000000018829e3b4: cmp       x13, x8
000000018829e3b8: b.eq      #0x18829e3f8
000000018829e3bc: ldr       x13, [x0]
000000018829e3c0: cbz       x13, #0x18829e3f4
000000018829e3c4: ldr       x13, [x13, #8]
000000018829e3c8: cmp       x11, #1
000000018829e3cc: b.hi      #0x18829e3dc
000000018829e3d0: sub       x14, x9, #1
000000018829e3d4: and       x13, x13, x14
000000018829e3d8: b         #0x18829e3ec
000000018829e3dc: cmp       x13, x9
000000018829e3e0: b.lo      #0x18829e3ec
000000018829e3e4: udiv      x14, x13, x9
000000018829e3e8: msub      x13, x14, x9, x13
000000018829e3ec: cmp       x13, x8
000000018829e3f0: b.eq      #0x18829e3f8
000000018829e3f4: str       xzr, [x12, x8, lsl #3]
000000018829e3f8: ldr       x12, [x0]
000000018829e3fc: cbz       x12, #0x18829e43c
000000018829e400: ldr       x13, [x12, #8]
000000018829e404: cmp       x11, #1
000000018829e408: b.hi      #0x18829e418
000000018829e40c: sub       x9, x9, #1
000000018829e410: and       x13, x13, x9
000000018829e414: b         #0x18829e428
000000018829e418: cmp       x13, x9
000000018829e41c: b.lo      #0x18829e428
000000018829e420: udiv      x11, x13, x9
000000018829e424: msub      x13, x11, x9, x13
000000018829e428: cmp       x13, x8
000000018829e42c: b.eq      #0x18829e43c
000000018829e430: ldr       x8, [x20]
000000018829e434: str       x10, [x8, x13, lsl #3]
000000018829e438: ldr       x12, [x0]
000000018829e43c: str       x12, [x10]
000000018829e440: str       xzr, [x0]
000000018829e444: ldr       x8, [x20, #0x18]
000000018829e448: sub       x8, x8, #1
000000018829e44c: str       x8, [x20, #0x18]
000000018829e450: bl        #0x1884c917c ; call __ZdlPv
000000018829e454: ldr       x20, [x24, #0xb60]
000000018829e458: ldr       w1, [x21, #0x10]
000000018829e45c: mov       x0, x20
000000018829e460: bl        #0x1882ce0b8 ; call __ZNSt3__112__hash_tableINS_17__hash_value_typeIjPN2CA6Render5Fence9FenceInfoEEENS_22__unordered_map_hasherIjS7_NS_4hashIjEENS_8equal_toIjEELb1EEENS_21__unordered_map_equalIjS7_SC_SA_Lb1EEENS_9allocatorIS7_EEE4findIjEENS_15__hash_iteratorIPNS_11__hash_nodeIS7_PvEEEERKT_
000000018829e464: cbz       x0, #0x18829e590
000000018829e468: ldr       x9, [x20, #8]
000000018829e46c: ldr       x8, [x0, #8]
000000018829e470: fmov      d0, x9
000000018829e474: cnt       v0.8b, v0.8b
000000018829e478: uaddlv    h0, v0.8b
000000018829e47c: fmov      w11, s0
000000018829e480: cmp       x11, #1
000000018829e484: b.hi      #0x18829e494
000000018829e488: sub       x10, x9, #1
000000018829e48c: and       x8, x10, x8
000000018829e490: b         #0x18829e4a4
000000018829e494: cmp       x8, x9
000000018829e498: b.lo      #0x18829e4a4
000000018829e49c: udiv      x10, x8, x9
000000018829e4a0: msub      x8, x10, x9, x8
000000018829e4a4: ldr       x12, [x20]
000000018829e4a8: ldr       x13, [x12, x8, lsl #3]
000000018829e4ac: mov       x10, x13
000000018829e4b0: ldr       x13, [x13]
000000018829e4b4: cmp       x13, x0
000000018829e4b8: b.ne      #0x18829e4ac
000000018829e4bc: add       x13, x20, #0x10
000000018829e4c0: cmp       x10, x13
000000018829e4c4: b.eq      #0x18829e4f8
000000018829e4c8: ldr       x13, [x10, #8]
000000018829e4cc: cmp       x11, #1
000000018829e4d0: b.hi      #0x18829e4e0
000000018829e4d4: sub       x14, x9, #1
000000018829e4d8: and       x13, x13, x14
000000018829e4dc: b         #0x18829e4f0
000000018829e4e0: cmp       x13, x9
000000018829e4e4: b.lo      #0x18829e4f0
000000018829e4e8: udiv      x14, x13, x9
000000018829e4ec: msub      x13, x14, x9, x13
000000018829e4f0: cmp       x13, x8
000000018829e4f4: b.eq      #0x18829e534
000000018829e4f8: ldr       x13, [x0]
000000018829e4fc: cbz       x13, #0x18829e530
000000018829e500: ldr       x13, [x13, #8]
000000018829e504: cmp       x11, #1
000000018829e508: b.hi      #0x18829e518
000000018829e50c: sub       x14, x9, #1
000000018829e510: and       x13, x13, x14
000000018829e514: b         #0x18829e528
000000018829e518: cmp       x13, x9
000000018829e51c: b.lo      #0x18829e528
000000018829e520: udiv      x14, x13, x9
000000018829e524: msub      x13, x14, x9, x13
000000018829e528: cmp       x13, x8
000000018829e52c: b.eq      #0x18829e534
000000018829e530: str       xzr, [x12, x8, lsl #3]
000000018829e534: ldr       x12, [x0]
000000018829e538: cbz       x12, #0x18829e578
000000018829e53c: ldr       x13, [x12, #8]
000000018829e540: cmp       x11, #1
000000018829e544: b.hi      #0x18829e554
000000018829e548: sub       x9, x9, #1
000000018829e54c: and       x13, x13, x9
000000018829e550: b         #0x18829e564
000000018829e554: cmp       x13, x9
000000018829e558: b.lo      #0x18829e564
000000018829e55c: udiv      x11, x13, x9
000000018829e560: msub      x13, x11, x9, x13
000000018829e564: cmp       x13, x8
000000018829e568: b.eq      #0x18829e578
000000018829e56c: ldr       x8, [x20]
000000018829e570: str       x10, [x8, x13, lsl #3]
000000018829e574: ldr       x12, [x0]
000000018829e578: str       x12, [x10]
000000018829e57c: str       xzr, [x0]
000000018829e580: ldr       x8, [x20, #0x18]
000000018829e584: sub       x8, x8, #1
000000018829e588: str       x8, [x20, #0x18]
000000018829e58c: bl        #0x1884c917c ; call __ZdlPv
000000018829e590: adrp      x8, #0x1dcc21000
000000018829e594: ldr       x0, [x8, #0xb70] ; [0x1dcc21b70]=0x0
000000018829e598: mov       x1, x22
000000018829e59c: bl        #0x1882dc990 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE14__erase_uniqueIyEEmRKT_
000000018829e5a0: ldr       w0, [x27]
000000018829e5a4: ldr       w1, [x21, #0x10]
000000018829e5a8: mov       w2, #1
000000018829e5ac: mov       w3, #-1
000000018829e5b0: bl        #0x18db3903c ; call _mach_port_mod_refs
000000018829e5b4: bl        #0x188238ad0 ; call __ZL15get_malloc_zonev
000000018829e5b8: mov       x1, x21
000000018829e5bc: bl        #0x18db390f0 ; call _malloc_zone_free
000000018829e5c0: ldr       x23, [x23]
000000018829e5c4: cbnz      x23, #0x18829e2e4
000000018829e5c8: bl        #0x18db38fac ; call _mach_absolute_time
000000018829e5cc: bl        #0x188236490 ; call _CATimeWithHostTime
000000018829e5d0: adrp      x23, #0x1dcc21000
000000018829e5d4: ldr       x8, [x23, #0xb38] ; [0x1dcc21b38]=0x0
000000018829e5d8: ldp       x20, x8, [x8]
000000018829e5dc: cmp       x20, x8
000000018829e5e0: b.eq      #0x18829e6c8
000000018829e5e4: fmov      d8, d0
000000018829e5e8: ldr       x21, [x20]
000000018829e5ec: ldr       x24, [sp, #0xb0]
000000018829e5f0: cbz       x24, #0x18829e64c
000000018829e5f4: mov       w25, #0
000000018829e5f8: ldr       x22, [x21]
000000018829e5fc: ldr       x1, [x24, #0x10]
000000018829e600: mov       x0, x22
000000018829e604: bl        #0x1882b7e48 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE4findIyEENS_15__hash_iteratorIPNS_11__hash_nodeIyPvEEEERKT_
000000018829e608: cbnz      x0, #0x18829e618
000000018829e60c: ldr       x24, [x24]
000000018829e610: cbnz      x24, #0x18829e5fc
000000018829e614: b         #0x18829e634
000000018829e618: mov       x1, x0
000000018829e61c: mov       x0, x22
000000018829e620: bl        #0x18830e728 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE5eraseENS_21__hash_const_iteratorIPNS_11__hash_nodeIyPvEEEE
000000018829e624: ldr       x24, [x24]
000000018829e628: mov       w25, #1
000000018829e62c: cbnz      x24, #0x18829e5f8
000000018829e630: b         #0x18829e638
000000018829e634: tbz       w25, #0, #0x18829e64c
000000018829e638: ldr       w0, [x21, #0x10]
000000018829e63c: ldr       w1, [x19, #0x18]
000000018829e640: ldp       x2, x3, [sp, #0xb0]
000000018829e644: fmov      d0, d8
000000018829e648: bl        #0x18830f9e8 ; call __ZN2CA6Render5FenceL13send_rlfg_msgEjdjRKNSt3__113unordered_setIyNS2_4hashIyEENS2_8equal_toIyEENS2_9allocatorIyEEEE
000000018829e64c: ldr       x8, [x21]
000000018829e650: ldr       x8, [x8, #0x18]
000000018829e654: cbz       x8, #0x18829e668
000000018829e658: add       x20, x20, #8
000000018829e65c: ldr       x8, [x23, #0xb38]
000000018829e660: ldr       x8, [x8, #8]
000000018829e664: b         #0x18829e6c0
000000018829e668: ldr       w0, [x27]
000000018829e66c: ldr       w1, [x21, #0x10]
000000018829e670: bl        #0x18db3900c ; call _mach_port_deallocate
000000018829e674: ldr       x0, [x21]
000000018829e678: cbz       x0, #0x18829e684
000000018829e67c: bl        #0x188261f58 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEED2Ev
000000018829e680: bl        #0x1884c917c ; call __ZdlPv
000000018829e684: ldr       x0, [x21, #8]
000000018829e688: cbz       x0, #0x18829e694
000000018829e68c: bl        #0x18823fadc ; call __ZNSt3__112__hash_tableIjNS_4hashIjEENS_8equal_toIjEENS_9allocatorIjEEED2Ev
000000018829e690: bl        #0x1884c917c ; call __ZdlPv
000000018829e694: bl        #0x188238ad0 ; call __ZL15get_malloc_zonev
000000018829e698: mov       x1, x21
000000018829e69c: bl        #0x18db390f0 ; call _malloc_zone_free
000000018829e6a0: ldr       x21, [x23, #0xb38]
000000018829e6a4: add       x1, x20, #8
000000018829e6a8: ldr       x22, [x21, #8]
000000018829e6ac: sub       x2, x22, x1
000000018829e6b0: mov       x0, x20
000000018829e6b4: bl        #0x1884c9908 ; call __platform_memmove
000000018829e6b8: sub       x8, x22, #8
000000018829e6bc: str       x8, [x21, #8]
000000018829e6c0: cmp       x20, x8
000000018829e6c4: b.ne      #0x18829e5e8
000000018829e6c8: ldr       w1, [x19, #0x18]
000000018829e6cc: add       w8, w1, #1
000000018829e6d0: cmp       w8, #2
000000018829e6d4: ldr       x19, [sp, #8]
000000018829e6d8: b.lo      #0x18829e6e4
000000018829e6dc: ldr       w0, [x27]
000000018829e6e0: bl        #0x18db3900c ; call _mach_port_deallocate
000000018829e6e4: cmp       x19, #0
000000018829e6e8: cset      w19, ne
000000018829e6ec: add       x0, sp, #0x70
000000018829e6f0: bl        #0x188261f58 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEED2Ev
000000018829e6f4: add       x0, sp, #0xa0
000000018829e6f8: bl        #0x188261f58 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEED2Ev
000000018829e6fc: ldur      x8, [x29, #-0x78]
000000018829e700: adrp      x9, #0x1daabe000
000000018829e704: ldr       x9, [x9, #0x7f0] ; [0x1daabe7f0]=0x201e1adb490
000000018829e708: ldr       x9, [x9]
000000018829e70c: cmp       x9, x8
000000018829e710: b.ne      #0x18829e75c
000000018829e714: mov       x0, x19
000000018829e718: ldp       x29, x30, [sp, #0x140]
000000018829e71c: ldp       x20, x19, [sp, #0x130]
000000018829e720: ldp       x22, x21, [sp, #0x120]
000000018829e724: ldp       x24, x23, [sp, #0x110]
000000018829e728: ldp       x26, x25, [sp, #0x100]
000000018829e72c: ldp       x28, x27, [sp, #0xf0]
000000018829e730: ldp       d9, d8, [sp, #0xe0]
000000018829e734: add       sp, sp, #0x150
000000018829e738: ret
000000018829e73c: adrp      x0, #0x1dcc21000
000000018829e740: add       x0, x0, #0xb88
000000018829e744: adrp      x2, #0x188497000
000000018829e748: add       x2, x2, #0x1c8
000000018829e74c: mov       x1, #0
000000018829e750: bl        #0x1884c9518 ; call _dispatch_once_f
000000018829e754: b         #0x18829dae0
000000018829e758: bl        #0x18db38ab4 ; call _abort
000000018829e75c: bl        #0x18db38a60 ; call ___stack_chk_fail
000000018829e760: bl        #0x18832c9d8 ; call __ZSt28__throw_bad_array_new_lengthB6v15006v
