0000000188281f44: sub       sp, sp, #0x90
0000000188281f48: stp       x26, x25, [sp, #0x40]
0000000188281f4c: stp       x24, x23, [sp, #0x50]
0000000188281f50: stp       x22, x21, [sp, #0x60]
0000000188281f54: stp       x20, x19, [sp, #0x70]
0000000188281f58: stp       x29, x30, [sp, #0x80]
0000000188281f5c: add       x29, sp, #0x80
0000000188281f60: mov       x19, x3
0000000188281f64: mov       x20, x2
0000000188281f68: mov       x21, x1
0000000188281f6c: adrp      x8, #0x1daabe000
0000000188281f70: ldr       x8, [x8, #0x7f0] ; [0x1daabe7f0]=0x201e1adb490
0000000188281f74: ldr       x8, [x8]
0000000188281f78: str       x8, [sp, #0x38]
0000000188281f7c: str       x0, [sp, #8]
0000000188281f80: add       x1, sp, #8
0000000188281f84: add       x2, sp, #8
0000000188281f88: mov       x0, x21
0000000188281f8c: bl        #0x1882e0cf4 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE25__emplace_unique_key_argsIyJRKyEEENS_4pairINS_15__hash_iteratorIPNS_11__hash_nodeIyPvEEEEbEERKT_DpOT0_
0000000188281f90: adrp      x8, #0x1dcc21000
0000000188281f94: ldr       x0, [x8, #0xb70] ; [0x1dcc21b70]=0x0
0000000188281f98: ldr       x1, [sp, #8]
0000000188281f9c: bl        #0x1882b7e48 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE4findIyEENS_15__hash_iteratorIPNS_11__hash_nodeIyPvEEEERKT_
0000000188281fa0: cbz       x0, #0x1882820d0
0000000188281fa4: adrp      x8, #0x1dcc21000
0000000188281fa8: ldr       x8, [x8, #0x678] ; [0x1dcc21678]=0x0
0000000188281fac: ldr       x23, [x8, #0x10]
0000000188281fb0: cbz       x23, #0x1882820e8
0000000188281fb4: ldr       x8, [x23, #0x18]
0000000188281fb8: ldr       x24, [x8, #8]
0000000188281fbc: ldp       x8, x25, [x24]
0000000188281fc0: cmp       x25, x8
0000000188281fc4: b.eq      #0x1882820a4
0000000188281fc8: mov       w22, #0
0000000188281fcc: str       xzr, [sp, #0x30]
0000000188281fd0: movi      v0.16b, #0
0000000188281fd4: stp       q0, q0, [sp, #0x10]
0000000188281fd8: ldur      w8, [x25, #-8]
0000000188281fdc: str       w8, [sp, #0x30]
0000000188281fe0: ldur      x1, [x25, #-0x20]
0000000188281fe4: add       x0, sp, #0x10
0000000188281fe8: bl        #0x1883b45b4 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE8__rehashILb1EEEvm
0000000188281fec: ldur      x26, [x25, #-0x18]
0000000188281ff0: cbz       x26, #0x18828200c
0000000188281ff4: add       x1, x26, #0x10
0000000188281ff8: add       x0, sp, #0x10
0000000188281ffc: mov       x2, x1
0000000188282000: bl        #0x1882e0cf4 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE25__emplace_unique_key_argsIyJRKyEEENS_4pairINS_15__hash_iteratorIPNS_11__hash_nodeIyPvEEEEbEERKT_DpOT0_
0000000188282004: ldr       x26, [x26]
0000000188282008: cbnz      x26, #0x188281ff4
000000018828200c: tbnz      w22, #0, #0x188282020
0000000188282010: ldr       x1, [sp, #8]
0000000188282014: add       x0, sp, #0x10
0000000188282018: bl        #0x1882b7e48 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE4findIyEENS_15__hash_iteratorIPNS_11__hash_nodeIyPvEEEERKT_
000000018828201c: cbz       x0, #0x188282088
0000000188282020: ldr       x26, [sp, #0x20]
0000000188282024: cbz       x26, #0x188282080
0000000188282028: ldr       x1, [x26, #0x10]
000000018828202c: str       x1, [sp]
0000000188282030: mov       x0, x21
0000000188282034: bl        #0x1882b7e48 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE4findIyEENS_15__hash_iteratorIPNS_11__hash_nodeIyPvEEEERKT_
0000000188282038: cbnz      x0, #0x188282078
000000018828203c: mov       x1, sp
0000000188282040: mov       x0, x20
0000000188282044: bl        #0x1882dec48 ; call __ZNKSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE4findIyEENS_21__hash_const_iteratorIPNS_11__hash_nodeIyPvEEEERKT_
0000000188282048: cbnz      x0, #0x188282078
000000018828204c: ldr       x22, [sp]
0000000188282050: mov       x0, x19
0000000188282054: mov       x1, x22
0000000188282058: bl        #0x1882b7e48 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE4findIyEENS_15__hash_iteratorIPNS_11__hash_nodeIyPvEEEERKT_
000000018828205c: cbnz      x0, #0x1882820b4
0000000188282060: mov       x0, x22
0000000188282064: mov       x1, x21
0000000188282068: mov       x2, x20
000000018828206c: mov       x3, x19
0000000188282070: bl        #0x188281f44 ; call __ZN2CA6Render5FenceL17is_fence_resolvedEyRNSt3__113unordered_setIyNS2_4hashIyEENS2_8equal_toIyEENS2_9allocatorIyEEEERKSA_SB_
0000000188282074: cbz       w0, #0x1882820b4
0000000188282078: ldr       x26, [x26]
000000018828207c: cbnz      x26, #0x188282028
0000000188282080: mov       w22, #1
0000000188282084: b         #0x18828208c
0000000188282088: mov       w22, #0
000000018828208c: sub       x25, x25, #0x28
0000000188282090: add       x0, sp, #0x10
0000000188282094: bl        #0x188261f58 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEED2Ev
0000000188282098: ldr       x8, [x24]
000000018828209c: cmp       x25, x8
00000001882820a0: b.ne      #0x188281fcc
00000001882820a4: ldr       x23, [x23]
00000001882820a8: mov       w0, #1
00000001882820ac: cbnz      x23, #0x188281fb4
00000001882820b0: b         #0x1882820ec
00000001882820b4: add       x1, sp, #8
00000001882820b8: add       x2, sp, #8
00000001882820bc: mov       x0, x19
00000001882820c0: bl        #0x1882e0cf4 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE25__emplace_unique_key_argsIyJRKyEEENS_4pairINS_15__hash_iteratorIPNS_11__hash_nodeIyPvEEEEbEERKT_DpOT0_
00000001882820c4: add       x0, sp, #0x10
00000001882820c8: bl        #0x188261f58 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEED2Ev
00000001882820cc: b         #0x1882820e0
00000001882820d0: add       x1, sp, #8
00000001882820d4: add       x2, sp, #8
00000001882820d8: mov       x0, x19
00000001882820dc: bl        #0x1882e0cf4 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE25__emplace_unique_key_argsIyJRKyEEENS_4pairINS_15__hash_iteratorIPNS_11__hash_nodeIyPvEEEEbEERKT_DpOT0_
00000001882820e0: mov       w0, #0
00000001882820e4: b         #0x1882820ec
00000001882820e8: mov       w0, #1
00000001882820ec: ldr       x8, [sp, #0x38]
00000001882820f0: adrp      x9, #0x1daabe000
00000001882820f4: ldr       x9, [x9, #0x7f0] ; [0x1daabe7f0]=0x201e1adb490
00000001882820f8: ldr       x9, [x9]
00000001882820fc: cmp       x9, x8
0000000188282100: b.ne      #0x188282120
0000000188282104: ldp       x29, x30, [sp, #0x80]
0000000188282108: ldp       x20, x19, [sp, #0x70]
000000018828210c: ldp       x22, x21, [sp, #0x60]
0000000188282110: ldp       x24, x23, [sp, #0x50]
0000000188282114: ldp       x26, x25, [sp, #0x40]
0000000188282118: add       sp, sp, #0x90
000000018828211c: ret
0000000188282120: bl        #0x18db38a60 ; call ___stack_chk_fail
