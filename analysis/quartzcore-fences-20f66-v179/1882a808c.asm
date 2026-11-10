00000001882a808c: sub       sp, sp, #0xd0
00000001882a8090: stp       d9, d8, [sp, #0x60]
00000001882a8094: stp       x28, x27, [sp, #0x70]
00000001882a8098: stp       x26, x25, [sp, #0x80]
00000001882a809c: stp       x24, x23, [sp, #0x90]
00000001882a80a0: stp       x22, x21, [sp, #0xa0]
00000001882a80a4: stp       x20, x19, [sp, #0xb0]
00000001882a80a8: stp       x29, x30, [sp, #0xc0]
00000001882a80ac: add       x29, sp, #0xc0
00000001882a80b0: adrp      x8, #0x1daabe000
00000001882a80b4: ldr       x8, [x8, #0x7f0] ; [0x1daabe7f0]=0x201e1adb490
00000001882a80b8: ldr       x8, [x8]
00000001882a80bc: str       x8, [sp, #0x58]
00000001882a80c0: sub       w8, w0, #1
00000001882a80c4: cmn       w8, #3
00000001882a80c8: b.hi      #0x1882a87e0
00000001882a80cc: mov       x20, x1
00000001882a80d0: mov       x22, x0
00000001882a80d4: adrp      x8, #0x1dcc21000
00000001882a80d8: ldr       x8, [x8, #0xb88] ; [0x1dcc21b88]=0x0
00000001882a80dc: cmn       x8, #1
00000001882a80e0: b.ne      #0x1882a8998
00000001882a80e4: adrp      x0, #0x1dcc20000
00000001882a80e8: add       x0, x0, #0xb68
00000001882a80ec: bl        #0x18db39534 ; call _os_unfair_lock_lock
00000001882a80f0: str       xzr, [sp, #0x50]
00000001882a80f4: movi      v0.16b, #0
00000001882a80f8: stp       q0, q0, [sp, #0x30]
00000001882a80fc: mov       w8, #0x3f800000
00000001882a8100: str       w8, [sp, #0x50]
00000001882a8104: cbz       x20, #0x1882a8940
00000001882a8108: str       xzr, [sp, #0x10]
00000001882a810c: mov       x23, #0
00000001882a8110: adrp      x24, #0x1dcc21000
00000001882a8114: add       x27, sp, #0x1c
00000001882a8118: adrp      x28, #0x1dcc21000
00000001882a811c: fmov      d8, #0.50000000
00000001882a8120: str       w22, [sp, #4]
00000001882a8124: ldr       x0, [x24, #0xb60]
00000001882a8128: ldr       w1, [x20, #8]
00000001882a812c: bl        #0x1882ce0b8 ; call __ZNSt3__112__hash_tableINS_17__hash_value_typeIjPN2CA6Render5Fence9FenceInfoEEENS_22__unordered_map_hasherIjS7_NS_4hashIjEENS_8equal_toIjEELb1EEENS_21__unordered_map_equalIjS7_SC_SA_Lb1EEENS_9allocatorIS7_EEE4findIjEENS_15__hash_iteratorIPNS_11__hash_nodeIS7_PvEEEERKT_
00000001882a8130: cbz       x0, #0x1882a814c
00000001882a8134: ldr       x25, [x0, #0x18]
00000001882a8138: adrp      x8, #0x1dcc21000
00000001882a813c: ldr       x0, [x8, #0xb70] ; [0x1dcc21b70]=0x0
00000001882a8140: ldr       x1, [x25]
00000001882a8144: bl        #0x1882b7e48 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE4findIyEENS_15__hash_iteratorIPNS_11__hash_nodeIyPvEEEERKT_
00000001882a8148: cbz       x0, #0x1882a8158
00000001882a814c: ldr       x20, [x20]
00000001882a8150: cbnz      x20, #0x1882a8124
00000001882a8154: b         #0x1882a87e8
00000001882a8158: ldr       x19, [x20, #0x18]
00000001882a815c: cbz       x19, #0x1882a814c
00000001882a8160: mov       x26, #0
00000001882a8164: ldr       x8, [x19, #0x10]
00000001882a8168: cbz       x8, #0x1882a8748
00000001882a816c: ldrb      w9, [x8, #0xd]
00000001882a8170: tbnz      w9, #2, #0x1882a8748
00000001882a8174: ldr       w8, [x8, #0x10]
00000001882a8178: str       w8, [sp, #0x1c]
00000001882a817c: cbz       x23, #0x1882a8230
00000001882a8180: ldr       x0, [x23]
00000001882a8184: mov       x1, x25
00000001882a8188: mov       x2, x25
00000001882a818c: bl        #0x1882e0cf4 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE25__emplace_unique_key_argsIyJRKyEEENS_4pairINS_15__hash_iteratorIPNS_11__hash_nodeIyPvEEEEbEERKT_DpOT0_
00000001882a8190: ldr       x0, [x23, #8]
00000001882a8194: add       x1, sp, #0x1c
00000001882a8198: add       x2, sp, #0x1c
00000001882a819c: bl        #0x1882dff80 ; call __ZNSt3__112__hash_tableIjNS_4hashIjEENS_8equal_toIjEENS_9allocatorIjEEE25__emplace_unique_key_argsIjJRKjEEENS_4pairINS_15__hash_iteratorIPNS_11__hash_nodeIjPvEEEEbEERKT_DpOT0_
00000001882a81a0: ldr       x0, [x28, #0x678]
00000001882a81a4: ldr       w1, [sp, #0x1c]
00000001882a81a8: bl        #0x188498df4 ; call __ZNSt3__112__hash_tableINS_17__hash_value_typeIjPN2CA6Render5Fence16FenceContextInfoEEENS_22__unordered_map_hasherIjS7_NS_4hashIjEENS_8equal_toIjEELb1EEENS_21__unordered_map_equalIjS7_SC_SA_Lb1EEENS_9allocatorIS7_EEE4findIjEENS_15__hash_iteratorIPNS_11__hash_nodeIS7_PvEEEERKT_
00000001882a81ac: cbnz      x0, #0x1882a86c8
00000001882a81b0: ldr       x8, [x19, #0x10]
00000001882a81b4: add       x8, x8, #8
00000001882a81b8: ldaxr     w9, [x8]
00000001882a81bc: add       w10, w9, #1
00000001882a81c0: stlxr     w11, w10, [x8]
00000001882a81c4: cbnz      w11, #0x1882a81b8
00000001882a81c8: cbz       w9, #0x1882a87cc
00000001882a81cc: bl        #0x188238ad0 ; call __ZL15get_malloc_zonev
00000001882a81d0: mov       w1, #0x10
00000001882a81d4: bl        #0x18db390fc ; call _malloc_zone_malloc
00000001882a81d8: mov       x21, x0
00000001882a81dc: ldr       x8, [x19, #0x10]
00000001882a81e0: str       x8, [x0]
00000001882a81e4: mov       w0, #0x18
00000001882a81e8: bl        #0x1884c9194 ; call __Znwm
00000001882a81ec: stp       xzr, xzr, [x0, #8]
00000001882a81f0: str       xzr, [x0]
00000001882a81f4: str       x0, [x21, #8]
00000001882a81f8: ldr       x22, [x28, #0x678]
00000001882a81fc: ldr       w27, [sp, #0x1c]
00000001882a8200: ldr       x24, [x22, #8]
00000001882a8204: str       x21, [sp, #8]
00000001882a8208: cbz       x24, #0x1882a82c0
00000001882a820c: fmov      d0, x24
00000001882a8210: cnt       v0.8b, v0.8b
00000001882a8214: uaddlv    h0, v0.8b
00000001882a8218: fmov      w8, s0
00000001882a821c: cmp       x8, #1
00000001882a8220: b.hi      #0x1882a82c8
00000001882a8224: sub       w9, w24, #1
00000001882a8228: and       x21, x9, x27
00000001882a822c: b         #0x1882a82dc
00000001882a8230: adrp      x8, #0x1daac1000
00000001882a8234: ldr       x8, [x8, #0x330] ; [0x1daac1330]=0x201e1ad9870
00000001882a8238: ldr       w0, [x8]
00000001882a823c: mov       x1, x22
00000001882a8240: mov       x2, x22
00000001882a8244: mov       w3, #0x13
00000001882a8248: bl        #0x18db39030 ; call _mach_port_insert_right
00000001882a824c: cbz       w0, #0x1882a8258
00000001882a8250: mov       x23, #0
00000001882a8254: b         #0x1882a8748
00000001882a8258: bl        #0x188238ad0 ; call __ZL15get_malloc_zonev
00000001882a825c: mov       w1, #0x18
00000001882a8260: bl        #0x18db390fc ; call _malloc_zone_malloc
00000001882a8264: mov       x23, x0
00000001882a8268: str       w22, [x0, #0x10]
00000001882a826c: mov       w0, #0x28
00000001882a8270: bl        #0x1884c9194 ; call __Znwm
00000001882a8274: movi      v0.16b, #0
00000001882a8278: stp       q0, q0, [x0]
00000001882a827c: mov       w21, #0x3f800000
00000001882a8280: str       w21, [x0, #0x20]
00000001882a8284: str       x0, [x23]
00000001882a8288: mov       w0, #0x28
00000001882a828c: bl        #0x1884c9194 ; call __Znwm
00000001882a8290: movi      v0.16b, #0
00000001882a8294: stp       q0, q0, [x0]
00000001882a8298: str       w21, [x0, #0x20]
00000001882a829c: str       x0, [x23, #8]
00000001882a82a0: adrp      x8, #0x1dcc21000
00000001882a82a4: ldr       x21, [x8, #0xb38] ; [0x1dcc21b38]=0x0
00000001882a82a8: ldp       x8, x9, [x21, #8]
00000001882a82ac: cmp       x8, x9
00000001882a82b0: b.eq      #0x1882a84a0
00000001882a82b4: str       x23, [x8], #8
00000001882a82b8: str       x8, [x21, #8]
00000001882a82bc: b         #0x1882a8180
00000001882a82c0: mov       x21, #0
00000001882a82c4: b         #0x1882a8338
00000001882a82c8: mov       x21, x27
00000001882a82cc: cmp       x24, x27
00000001882a82d0: b.hi      #0x1882a82dc
00000001882a82d4: udiv      x9, x27, x24
00000001882a82d8: msub      x21, x9, x24, x27
00000001882a82dc: ldr       x9, [x22]
00000001882a82e0: ldr       x28, [x9, x21, lsl #3]
00000001882a82e4: cbz       x28, #0x1882a8338
00000001882a82e8: sub       x9, x24, #1
00000001882a82ec: ldr       x28, [x28]
00000001882a82f0: cbz       x28, #0x1882a8338
00000001882a82f4: ldr       x10, [x28, #8]
00000001882a82f8: cmp       x10, x27
00000001882a82fc: b.eq      #0x1882a8328
00000001882a8300: cmp       x8, #1
00000001882a8304: b.hi      #0x1882a8310
00000001882a8308: and       x10, x10, x9
00000001882a830c: b         #0x1882a8320
00000001882a8310: cmp       x10, x24
00000001882a8314: b.lo      #0x1882a8320
00000001882a8318: udiv      x11, x10, x24
00000001882a831c: msub      x10, x11, x24, x10
00000001882a8320: cmp       x10, x21
00000001882a8324: b.ne      #0x1882a8338
00000001882a8328: ldr       w10, [x28, #0x10]
00000001882a832c: cmp       w10, w27
00000001882a8330: b.ne      #0x1882a82ec
00000001882a8334: b         #0x1882a86b0
00000001882a8338: mov       w0, #0x20
00000001882a833c: bl        #0x1884c9194 ; call __Znwm
00000001882a8340: mov       x28, x0
00000001882a8344: str       w27, [x0, #0x10]
00000001882a8348: str       xzr, [x0, #0x18]
00000001882a834c: stp       xzr, x27, [x0]
00000001882a8350: ldr       x8, [x22, #0x18]
00000001882a8354: add       x8, x8, #1
00000001882a8358: ucvtf     s0, x8
00000001882a835c: ucvtf     s2, x24
00000001882a8360: ldr       s1, [x22, #0x20]
00000001882a8364: fmul      s2, s1, s2
00000001882a8368: fcmp      s2, s0
00000001882a836c: ccmp      x24, #0, #4, pl
00000001882a8370: b.ne      #0x1882a863c
00000001882a8374: lsl       x8, x24, #1
00000001882a8378: sub       x9, x24, #1
00000001882a837c: tst       x24, x9
00000001882a8380: cset      w9, ne
00000001882a8384: cmp       x24, #3
00000001882a8388: mov       w10, #1
00000001882a838c: csel      x9, x10, x9, lo
00000001882a8390: orr       x8, x9, x8
00000001882a8394: fdiv      s0, s0, s1
00000001882a8398: fcvtpu    x9, s0
00000001882a839c: cmp       x8, x9
00000001882a83a0: csel      x24, x8, x9, hi
00000001882a83a4: subs      x8, x24, #1
00000001882a83a8: b.ne      #0x1882a83b4
00000001882a83ac: mov       w24, #2
00000001882a83b0: b         #0x1882a83c8
00000001882a83b4: tst       x24, x8
00000001882a83b8: b.eq      #0x1882a83c8
00000001882a83bc: mov       x0, x24
00000001882a83c0: bl        #0x18db388f8 ; call __ZNSt3__112__next_primeEm
00000001882a83c4: mov       x24, x0
00000001882a83c8: ldr       x21, [x22, #8]
00000001882a83cc: cmp       x24, x21
00000001882a83d0: b.ls      #0x1882a8448
00000001882a83d4: lsr       x8, x24, #0x3d
00000001882a83d8: cbnz      x8, #0x1882a89b8
00000001882a83dc: lsl       x0, x24, #3
00000001882a83e0: bl        #0x1884c9194 ; call __Znwm
00000001882a83e4: mov       x8, x0
00000001882a83e8: ldr       x0, [x22]
00000001882a83ec: str       x8, [x22]
00000001882a83f0: cbz       x0, #0x1882a83f8
00000001882a83f4: bl        #0x1884c917c ; call __ZdlPv
00000001882a83f8: mov       x8, #0
00000001882a83fc: str       x24, [x22, #8]
00000001882a8400: ldr       x9, [x22]
00000001882a8404: str       xzr, [x9, x8, lsl #3]
00000001882a8408: add       x8, x8, #1
00000001882a840c: cmp       x24, x8
00000001882a8410: b.ne      #0x1882a8400
00000001882a8414: mov       x11, x22
00000001882a8418: ldr       x9, [x11, #0x10]!
00000001882a841c: cbz       x9, #0x1882a8608
00000001882a8420: ldr       x10, [x9, #8]
00000001882a8424: fmov      d0, x24
00000001882a8428: cnt       v0.8b, v0.8b
00000001882a842c: uaddlv    h0, v0.8b
00000001882a8430: fmov      w8, s0
00000001882a8434: cmp       x8, #1
00000001882a8438: b.hi      #0x1882a84ec
00000001882a843c: sub       x12, x24, #1
00000001882a8440: and       x10, x10, x12
00000001882a8444: b         #0x1882a84fc
00000001882a8448: b.hs      #0x1882a8608
00000001882a844c: ldr       x8, [x22, #0x18]
00000001882a8450: ucvtf     s0, x8
00000001882a8454: ldr       s1, [x22, #0x20]
00000001882a8458: fdiv      s0, s0, s1
00000001882a845c: fcvtpu    x0, s0
00000001882a8460: cmp       x21, #3
00000001882a8464: b.lo      #0x1882a85dc
00000001882a8468: fmov      d0, x21
00000001882a846c: cnt       v0.8b, v0.8b
00000001882a8470: uaddlv    h0, v0.8b
00000001882a8474: fmov      w8, s0
00000001882a8478: cmp       x8, #1
00000001882a847c: b.hi      #0x1882a85dc
00000001882a8480: sub       x8, x0, #1
00000001882a8484: clz       x8, x8
00000001882a8488: neg       x8, x8
00000001882a848c: mov       w9, #1
00000001882a8490: lsl       x8, x9, x8
00000001882a8494: cmp       x0, #2
00000001882a8498: csel      x0, x0, x8, lo
00000001882a849c: b         #0x1882a85e0
00000001882a84a0: ldr       x9, [x21]
00000001882a84a4: sub       x8, x8, x9
00000001882a84a8: asr       x22, x8, #3
00000001882a84ac: add       x9, x22, #1
00000001882a84b0: lsr       x10, x9, #0x3d
00000001882a84b4: cbnz      x10, #0x1882a89b4
00000001882a84b8: asr       x10, x8, #2
00000001882a84bc: cmp       x10, x9
00000001882a84c0: csel      x9, x10, x9, hi
00000001882a84c4: mov       x10, #0x7ffffffffffffff8
00000001882a84c8: cmp       x8, x10
00000001882a84cc: mov       x8, #0x1fffffffffffffff
00000001882a84d0: csel      x24, x9, x8, lo
00000001882a84d4: cbz       x24, #0x1882a8590
00000001882a84d8: lsr       x8, x24, #0x3d
00000001882a84dc: cbnz      x8, #0x1882a89b8
00000001882a84e0: lsl       x0, x24, #3
00000001882a84e4: bl        #0x1884c9194 ; call __Znwm
00000001882a84e8: b         #0x1882a8594
00000001882a84ec: cmp       x10, x24
00000001882a84f0: b.lo      #0x1882a84fc
00000001882a84f4: udiv      x12, x10, x24
00000001882a84f8: msub      x10, x12, x24, x10
00000001882a84fc: ldr       x12, [x22]
00000001882a8500: str       x11, [x12, x10, lsl #3]
00000001882a8504: ldr       x11, [x9]
00000001882a8508: cbz       x11, #0x1882a8608
00000001882a850c: sub       x12, x24, #1
00000001882a8510: ldr       x13, [x11, #8]
00000001882a8514: cmp       x8, #1
00000001882a8518: b.hi      #0x1882a8524
00000001882a851c: and       x13, x13, x12
00000001882a8520: b         #0x1882a8534
00000001882a8524: cmp       x13, x24
00000001882a8528: b.lo      #0x1882a8534
00000001882a852c: udiv      x14, x13, x24
00000001882a8530: msub      x13, x14, x24, x13
00000001882a8534: cmp       x13, x10
00000001882a8538: b.eq      #0x1882a8570
00000001882a853c: ldr       x14, [x22]
00000001882a8540: ldr       x15, [x14, x13, lsl #3]
00000001882a8544: cbz       x15, #0x1882a8588
00000001882a8548: ldr       x14, [x11]
00000001882a854c: str       x14, [x9]
00000001882a8550: ldr       x14, [x22]
00000001882a8554: ldr       x14, [x14, x13, lsl #3]
00000001882a8558: ldr       x14, [x14]
00000001882a855c: str       x14, [x11]
00000001882a8560: ldr       x14, [x22]
00000001882a8564: ldr       x13, [x14, x13, lsl #3]
00000001882a8568: str       x11, [x13]
00000001882a856c: mov       x11, x9
00000001882a8570: mov       x13, x10
00000001882a8574: mov       x9, x11
00000001882a8578: ldr       x11, [x11]
00000001882a857c: mov       x10, x13
00000001882a8580: cbnz      x11, #0x1882a8510
00000001882a8584: b         #0x1882a8608
00000001882a8588: str       x9, [x14, x13, lsl #3]
00000001882a858c: b         #0x1882a8574
00000001882a8590: mov       x0, #0
00000001882a8594: add       x8, x0, x22, lsl #3
00000001882a8598: add       x22, x0, x24, lsl #3
00000001882a859c: mov       x27, x8
00000001882a85a0: str       x23, [x27], #8
00000001882a85a4: ldp       x1, x9, [x21]
00000001882a85a8: sub       x2, x9, x1
00000001882a85ac: sub       x24, x8, x2
00000001882a85b0: mov       x0, x24
00000001882a85b4: bl        #0x1884c9908 ; call __platform_memmove
00000001882a85b8: ldr       x0, [x21]
00000001882a85bc: stp       x24, x27, [x21]
00000001882a85c0: str       x22, [x21, #0x10]
00000001882a85c4: cbz       x0, #0x1882a85cc
00000001882a85c8: bl        #0x1884c917c ; call __ZdlPv
00000001882a85cc: ldr       w22, [sp, #4]
00000001882a85d0: adrp      x24, #0x1dcc21000
00000001882a85d4: add       x27, sp, #0x1c
00000001882a85d8: b         #0x1882a8180
00000001882a85dc: bl        #0x18db388f8 ; call __ZNSt3__112__next_primeEm
00000001882a85e0: cmp       x24, x0
00000001882a85e4: csel      x24, x24, x0, hi
00000001882a85e8: cmp       x24, x21
00000001882a85ec: b.hs      #0x1882a8608
00000001882a85f0: cbnz      x24, #0x1882a83d4
00000001882a85f4: ldr       x0, [x22]
00000001882a85f8: str       xzr, [x22]
00000001882a85fc: cbz       x0, #0x1882a8604
00000001882a8600: bl        #0x1884c917c ; call __ZdlPv
00000001882a8604: str       xzr, [x22, #8]
00000001882a8608: ldr       x24, [x22, #8]
00000001882a860c: sub       x8, x24, #1
00000001882a8610: tst       x24, x8
00000001882a8614: b.ne      #0x1882a8624
00000001882a8618: sub       w8, w24, #1
00000001882a861c: and       x21, x8, x27
00000001882a8620: b         #0x1882a863c
00000001882a8624: cmp       x24, x27
00000001882a8628: b.ls      #0x1882a8634
00000001882a862c: mov       x21, x27
00000001882a8630: b         #0x1882a863c
00000001882a8634: udiv      x8, x27, x24
00000001882a8638: msub      x21, x8, x24, x27
00000001882a863c: ldr       x8, [x22]
00000001882a8640: ldr       x9, [x8, x21, lsl #3]
00000001882a8644: cbz       x9, #0x1882a8658
00000001882a8648: ldr       x8, [x9]
00000001882a864c: str       x8, [x28]
00000001882a8650: str       x28, [x9]
00000001882a8654: b         #0x1882a86a4
00000001882a8658: mov       x9, x22
00000001882a865c: ldr       x10, [x9, #0x10]!
00000001882a8660: str       x10, [x28]
00000001882a8664: str       x28, [x9]
00000001882a8668: str       x9, [x8, x21, lsl #3]
00000001882a866c: ldr       x8, [x28]
00000001882a8670: cbz       x8, #0x1882a86a4
00000001882a8674: ldr       x8, [x8, #8]
00000001882a8678: sub       x9, x24, #1
00000001882a867c: tst       x24, x9
00000001882a8680: b.ne      #0x1882a868c
00000001882a8684: and       x8, x8, x9
00000001882a8688: b         #0x1882a869c
00000001882a868c: cmp       x8, x24
00000001882a8690: b.lo      #0x1882a869c
00000001882a8694: udiv      x9, x8, x24
00000001882a8698: msub      x8, x9, x24, x8
00000001882a869c: ldr       x9, [x22]
00000001882a86a0: str       x28, [x9, x8, lsl #3]
00000001882a86a4: ldr       x8, [x22, #0x18]
00000001882a86a8: add       x8, x8, #1
00000001882a86ac: str       x8, [x22, #0x18]
00000001882a86b0: ldr       x8, [sp, #8]
00000001882a86b4: str       x8, [x28, #0x18]
00000001882a86b8: adrp      x28, #0x1dcc21000
00000001882a86bc: ldr       w22, [sp, #4]
00000001882a86c0: adrp      x24, #0x1dcc21000
00000001882a86c4: add       x27, sp, #0x1c
00000001882a86c8: str       x27, [sp, #0x28]
00000001882a86cc: add       x0, sp, #0x30
00000001882a86d0: add       x1, sp, #0x1c
00000001882a86d4: add       x3, sp, #0x28
00000001882a86d8: add       x4, sp, #0x20
00000001882a86dc: adrp      x2, #0x1884e6000
00000001882a86e0: add       x2, x2, #0xfe4
00000001882a86e4: bl        #0x18828c064 ; call __ZNSt3__112__hash_tableINS_17__hash_value_typeIjNS_13unordered_setIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEEEEENS_22__unordered_map_hasherIjSA_NS3_IjEENS5_IjEELb1EEENS_21__unordered_map_equalIjSA_SD_SC_Lb1EEENS7_ISA_EEE25__emplace_unique_key_argsIjJRKNS_21piecewise_construct_tENS_5tupleIJRKjEEENSN_IJEEEEEENS_4pairINS_15__hash_iteratorIPNS_11__hash_nodeISA_PvEEEEbEERKT_DpOT0_
00000001882a86e8: add       x0, x0, #0x18
00000001882a86ec: mov       x1, x25
00000001882a86f0: mov       x2, x25
00000001882a86f4: bl        #0x1882e0cf4 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEE25__emplace_unique_key_argsIyJRKyEEENS_4pairINS_15__hash_iteratorIPNS_11__hash_nodeIyPvEEEEbEERKT_DpOT0_
00000001882a86f8: ldrb      w8, [x25, #0x14]
00000001882a86fc: cbz       w8, #0x1882a8754
00000001882a8700: cbz       x26, #0x1882a87a0
00000001882a8704: ldr       x8, [x26, #0x18]
00000001882a8708: cbz       x8, #0x1882a8724
00000001882a870c: ldr       w9, [sp, #0x1c]
00000001882a8710: ldr       w10, [x8, #0xc]
00000001882a8714: cmp       w10, w9
00000001882a8718: b.eq      #0x1882a8748
00000001882a871c: ldr       x8, [x8]
00000001882a8720: cbnz      x8, #0x1882a8710
00000001882a8724: bl        #0x188238ad0 ; call __ZL15get_malloc_zonev
00000001882a8728: mov       w1, #0x18
00000001882a872c: bl        #0x18db390fc ; call _malloc_zone_malloc
00000001882a8730: ldr       x8, [x26, #0x18]
00000001882a8734: str       x8, [x0]
00000001882a8738: ldr       w8, [sp, #0x1c]
00000001882a873c: stp       wzr, w8, [x0, #8]
00000001882a8740: str       xzr, [x0, #0x10]
00000001882a8744: str       x0, [x26, #0x18]
00000001882a8748: ldr       x19, [x19]
00000001882a874c: cbnz      x19, #0x1882a8164
00000001882a8750: b         #0x1882a814c
00000001882a8754: mov       w8, #1
00000001882a8758: strb      w8, [x25, #0x14]
00000001882a875c: ldr       x1, [x25]
00000001882a8760: mov       w0, #0x204
00000001882a8764: movk      w0, #0x31ca, lsl #16
00000001882a8768: mov       x2, #0
00000001882a876c: mov       x3, #0
00000001882a8770: mov       x4, #0
00000001882a8774: bl        #0x18db38f70 ; call _kdebug_trace
00000001882a8778: bl        #0x18db38fac ; call _mach_absolute_time
00000001882a877c: bl        #0x188236490 ; call _CATimeWithHostTime
00000001882a8780: fadd      d0, d0, d8
00000001882a8784: str       d0, [x25, #8]
00000001882a8788: mov       w0, #3
00000001882a878c: adrp      x1, #0x188497000
00000001882a8790: add       x1, x1, #0x2d4
00000001882a8794: mov       x2, #0
00000001882a8798: bl        #0x18829cfdc ; call __ZN2CA6Render6Server12add_callbackEdNS1_16CallbackBehaviorEPFvdPvES3_ | x1 literal: __ZN2CA6Render5FenceL17ftimeout_callbackEdPv
00000001882a879c: cbnz      x26, #0x1882a8704
00000001882a87a0: bl        #0x188238ad0 ; call __ZL15get_malloc_zonev
00000001882a87a4: mov       w1, #0x20
00000001882a87a8: bl        #0x18db390fc ; call _malloc_zone_malloc
00000001882a87ac: mov       x26, x0
00000001882a87b0: ldr       x8, [sp, #0x10]
00000001882a87b4: str       x8, [x0]
00000001882a87b8: str       wzr, [x0, #8]
00000001882a87bc: ldr       x8, [x25]
00000001882a87c0: stp       x8, xzr, [x0, #0x10]
00000001882a87c4: str       x0, [sp, #0x10]
00000001882a87c8: b         #0x1882a8704
00000001882a87cc: ldaxr     w9, [x8]
00000001882a87d0: sub       w9, w9, #1
00000001882a87d4: stlxr     w10, w9, [x8]
00000001882a87d8: cbnz      w10, #0x1882a87cc
00000001882a87dc: b         #0x1882a81cc
00000001882a87e0: mov       x19, #0
00000001882a87e4: b         #0x1882a8958
00000001882a87e8: ldr       x19, [sp, #0x40]
00000001882a87ec: cbz       x19, #0x1882a8938
00000001882a87f0: mov       x22, #0x6666666666666666
00000001882a87f4: movk      x22, #0x666, lsl #48
00000001882a87f8: mov       x23, #-0x3333333333333334
00000001882a87fc: movk      x23, #0xcccd
00000001882a8800: mov       x24, #0x3333333333333333
00000001882a8804: movk      x24, #0x333, lsl #48
00000001882a8808: mov       w25, #0x28
00000001882a880c: ldr       x0, [x28, #0x678]
00000001882a8810: ldr       w1, [x19, #0x10]
00000001882a8814: bl        #0x188498df4 ; call __ZNSt3__112__hash_tableINS_17__hash_value_typeIjPN2CA6Render5Fence16FenceContextInfoEEENS_22__unordered_map_hasherIjS7_NS_4hashIjEENS_8equal_toIjEELb1EEENS_21__unordered_map_equalIjS7_SC_SA_Lb1EEENS_9allocatorIS7_EEE4findIjEENS_15__hash_iteratorIPNS_11__hash_nodeIS7_PvEEEERKT_
00000001882a8818: cbz       x0, #0x1882a89b4
00000001882a881c: ldr       x8, [x0, #0x18]
00000001882a8820: ldr       x26, [x8, #8]
00000001882a8824: add       x20, x19, #0x18
00000001882a8828: ldp       x0, x8, [x26, #8]
00000001882a882c: cmp       x0, x8
00000001882a8830: b.hs      #0x1882a8848
00000001882a8834: mov       x1, x20
00000001882a8838: bl        #0x1882e274c ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEEC2EOS7_
00000001882a883c: add       x8, x0, #0x28
00000001882a8840: str       x8, [x26, #8]
00000001882a8844: b         #0x1882a8918
00000001882a8848: ldr       x10, [x26]
00000001882a884c: sub       x9, x0, x10
00000001882a8850: asr       x9, x9, #3
00000001882a8854: mul       x21, x9, x23
00000001882a8858: add       x9, x21, #1
00000001882a885c: cmp       x9, x22
00000001882a8860: b.hi      #0x1882a89b4
00000001882a8864: sub       x8, x8, x10
00000001882a8868: asr       x8, x8, #3
00000001882a886c: mul       x8, x8, x23
00000001882a8870: lsl       x10, x8, #1
00000001882a8874: cmp       x10, x9
00000001882a8878: csel      x9, x10, x9, hi
00000001882a887c: cmp       x8, x24
00000001882a8880: csel      x27, x9, x22, lo
00000001882a8884: cbz       x27, #0x1882a88a4
00000001882a8888: cmp       x27, x22
00000001882a888c: b.hi      #0x1882a89b8
00000001882a8890: add       x8, x27, x27, lsl #2
00000001882a8894: lsl       x0, x8, #3
00000001882a8898: bl        #0x1884c9194 ; call __Znwm
00000001882a889c: mov       x8, x0
00000001882a88a0: b         #0x1882a88a8
00000001882a88a4: mov       x8, #0
00000001882a88a8: madd      x0, x21, x25, x8
00000001882a88ac: madd      x27, x27, x25, x8
00000001882a88b0: mov       x1, x20
00000001882a88b4: bl        #0x1882e274c ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEEC2EOS7_
00000001882a88b8: add       x28, x0, #0x28
00000001882a88bc: ldp       x21, x20, [x26]
00000001882a88c0: cmp       x20, x21
00000001882a88c4: b.eq      #0x1882a8924
00000001882a88c8: sub       x0, x0, #0x28
00000001882a88cc: sub       x20, x20, #0x28
00000001882a88d0: mov       x1, x20
00000001882a88d4: bl        #0x1882e274c ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEEC2EOS7_
00000001882a88d8: cmp       x20, x21
00000001882a88dc: b.ne      #0x1882a88c8
00000001882a88e0: ldp       x20, x21, [x26]
00000001882a88e4: stp       x0, x28, [x26]
00000001882a88e8: str       x27, [x26, #0x10]
00000001882a88ec: cmp       x21, x20
00000001882a88f0: b.eq      #0x1882a892c
00000001882a88f4: adrp      x28, #0x1dcc21000
00000001882a88f8: sub       x21, x21, #0x28
00000001882a88fc: mov       x0, x21
00000001882a8900: bl        #0x188261f58 ; call __ZNSt3__112__hash_tableIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEED2Ev
00000001882a8904: cmp       x21, x20
00000001882a8908: b.ne      #0x1882a88f8
00000001882a890c: cbz       x20, #0x1882a8918
00000001882a8910: mov       x0, x20
00000001882a8914: bl        #0x1884c917c ; call __ZdlPv
00000001882a8918: ldr       x19, [x19]
00000001882a891c: cbnz      x19, #0x1882a880c
00000001882a8920: b         #0x1882a8938
00000001882a8924: stp       x0, x28, [x26]
00000001882a8928: str       x27, [x26, #0x10]
00000001882a892c: adrp      x28, #0x1dcc21000
00000001882a8930: cbnz      x20, #0x1882a8910
00000001882a8934: b         #0x1882a8918
00000001882a8938: ldr       x19, [sp, #0x10]
00000001882a893c: b         #0x1882a8944
00000001882a8940: mov       x19, #0
00000001882a8944: add       x0, sp, #0x30
00000001882a8948: bl        #0x18827f4b8 ; call __ZNSt3__112__hash_tableINS_17__hash_value_typeIjNS_13unordered_setIyNS_4hashIyEENS_8equal_toIyEENS_9allocatorIyEEEEEENS_22__unordered_map_hasherIjSA_NS3_IjEENS5_IjEELb1EEENS_21__unordered_map_equalIjSA_SD_SC_Lb1EEENS7_ISA_EEED2Ev
00000001882a894c: adrp      x0, #0x1dcc20000
00000001882a8950: add       x0, x0, #0xb68
00000001882a8954: bl        #0x18db3954c ; call _os_unfair_lock_unlock
00000001882a8958: ldr       x8, [sp, #0x58]
00000001882a895c: adrp      x9, #0x1daabe000
00000001882a8960: ldr       x9, [x9, #0x7f0] ; [0x1daabe7f0]=0x201e1adb490
00000001882a8964: ldr       x9, [x9]
00000001882a8968: cmp       x9, x8
00000001882a896c: b.ne      #0x1882a89bc
00000001882a8970: mov       x0, x19
00000001882a8974: ldp       x29, x30, [sp, #0xc0]
00000001882a8978: ldp       x20, x19, [sp, #0xb0]
00000001882a897c: ldp       x22, x21, [sp, #0xa0]
00000001882a8980: ldp       x24, x23, [sp, #0x90]
00000001882a8984: ldp       x26, x25, [sp, #0x80]
00000001882a8988: ldp       x28, x27, [sp, #0x70]
00000001882a898c: ldp       d9, d8, [sp, #0x60]
00000001882a8990: add       sp, sp, #0xd0
00000001882a8994: ret
00000001882a8998: adrp      x0, #0x1dcc21000
00000001882a899c: add       x0, x0, #0xb88
00000001882a89a0: adrp      x2, #0x188497000
00000001882a89a4: add       x2, x2, #0x1c8
00000001882a89a8: mov       x1, #0
00000001882a89ac: bl        #0x1884c9518 ; call _dispatch_once_f
00000001882a89b0: b         #0x1882a80e4
00000001882a89b4: bl        #0x18db38ab4 ; call _abort
00000001882a89b8: bl        #0x18832c9d8 ; call __ZSt28__throw_bad_array_new_lengthB6v15006v
00000001882a89bc: bl        #0x18db38a60 ; call ___stack_chk_fail
