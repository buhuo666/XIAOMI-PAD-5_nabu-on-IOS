0000000188214cbc: sub       sp, sp, #0x1c0
0000000188214cc0: stp       d13, d12, [sp, #0x130]
0000000188214cc4: stp       d11, d10, [sp, #0x140]
0000000188214cc8: stp       d9, d8, [sp, #0x150]
0000000188214ccc: stp       x28, x27, [sp, #0x160]
0000000188214cd0: stp       x26, x25, [sp, #0x170]
0000000188214cd4: stp       x24, x23, [sp, #0x180]
0000000188214cd8: stp       x22, x21, [sp, #0x190]
0000000188214cdc: stp       x20, x19, [sp, #0x1a0]
0000000188214ce0: stp       x29, x30, [sp, #0x1b0]
0000000188214ce4: add       x29, sp, #0x1b0
0000000188214ce8: mov       x24, x2
0000000188214cec: fmov      d8, d0
0000000188214cf0: mov       x21, x1
0000000188214cf4: mov       x20, x0
0000000188214cf8: adrp      x8, #0x1daabe000
0000000188214cfc: ldr       x8, [x8, #0x7f0] ; [0x1daabe7f0]=0x201e1adb490
0000000188214d00: ldr       x8, [x8]
0000000188214d04: stur      x8, [x29, #-0x90]
0000000188214d08: mov       x0, x1
0000000188214d0c: bl        #0x188543b00 ; call _objc_msgSend$priv
0000000188214d10: mov       x22, x0
0000000188214d14: add       x0, x20, #8
0000000188214d18: str       x0, [sp, #0x18]
0000000188214d1c: bl        #0x18db39534 ; call _os_unfair_lock_lock
0000000188214d20: ldr       x8, [x20, #0x40]
0000000188214d24: cbz       x8, #0x188214d54
0000000188214d28: adrp      x8, #0x1884d3000
0000000188214d2c: ldr       d0, [x8, #0xfe8] ; [0x1884d3fe8]=0x3f40624dd2f1a9fc
0000000188214d30: fcmp      d8, d0
0000000188214d34: b.ls      #0x188214da8
0000000188214d38: str       wzr, [sp, #0x14]
0000000188214d3c: adrp      x8, #0x1884d4000
0000000188214d40: ldr       d0, [x8, #0x258] ; [0x1884d4258]=0xbf40624dd2f1a9fc
0000000188214d44: fadd      d8, d8, d0
0000000188214d48: ldrh      w19, [x20, #0x108]
0000000188214d4c: mov       w8, #0x40000000
0000000188214d50: b         #0x188214dd0
0000000188214d54: adrp      x0, #0x1d5812000
0000000188214d58: add       x0, x0, #0xd38
0000000188214d5c: bl        #0x18db38808 ; call _NSLog
0000000188214d60: ldur      x8, [x29, #-0x90]
0000000188214d64: adrp      x9, #0x1daabe000
0000000188214d68: ldr       x9, [x9, #0x7f0] ; [0x1daabe7f0]=0x201e1adb490
0000000188214d6c: ldr       x9, [x9]
0000000188214d70: cmp       x9, x8
0000000188214d74: b.ne      #0x188215334
0000000188214d78: ldr       x0, [sp, #0x18]
0000000188214d7c: ldp       x29, x30, [sp, #0x1b0]
0000000188214d80: ldp       x20, x19, [sp, #0x1a0]
0000000188214d84: ldp       x22, x21, [sp, #0x190]
0000000188214d88: ldp       x24, x23, [sp, #0x180]
0000000188214d8c: ldp       x26, x25, [sp, #0x170]
0000000188214d90: ldp       x28, x27, [sp, #0x160]
0000000188214d94: ldp       d9, d8, [sp, #0x150]
0000000188214d98: ldp       d11, d10, [sp, #0x140]
0000000188214d9c: ldp       d13, d12, [sp, #0x130]
0000000188214da0: add       sp, sp, #0x1c0
0000000188214da4: b         #0x18db3954c
0000000188214da8: ldrh      w19, [x20, #0x108]
0000000188214dac: tst       w19, #8
0000000188214db0: cset      w9, eq
0000000188214db4: mov       w8, #2
0000000188214db8: movk      w8, #0x4000, lsl #16
0000000188214dbc: add       w10, w8, #2
0000000188214dc0: csel      w8, w8, w10, eq
0000000188214dc4: and       w9, w24, w9
0000000188214dc8: str       w9, [sp, #0x14]
0000000188214dcc: fmov      d8, xzr
0000000188214dd0: orr       w25, w8, #1
0000000188214dd4: tst       w19, #2
0000000188214dd8: csel      w23, w8, w25, eq
0000000188214ddc: tbnz      w23, #0, #0x188214df0
0000000188214de0: ldr       w0, [x22, #0xc]
0000000188214de4: bl        #0x1882cce70 ; call __ZN2CA6Render16fourcc_has_alphaEj
0000000188214de8: cmp       w0, #0
0000000188214dec: csel      w23, w23, w25, ne
0000000188214df0: orr       w8, w23, #0x20
0000000188214df4: ldr       w9, [sp, #0x14]
0000000188214df8: cmp       w9, #0
0000000188214dfc: csel      w8, w8, w23, ne
0000000188214e00: orr       w9, w8, #0x200000
0000000188214e04: tst       w19, #0x800
0000000188214e08: csel      w26, w9, w8, eq
0000000188214e0c: ldrb      w27, [x22, #0x69]
0000000188214e10: ldrb      w23, [x22, #0x68]
0000000188214e14: adrp      x25, #0x1e1b9b000
0000000188214e18: adrp      x19, #0x1e1b9b000
0000000188214e1c: cmp       w23, #3
0000000188214e20: b.eq      #0x188214e3c
0000000188214e24: cmp       w23, #2
0000000188214e28: b.eq      #0x188214e44
0000000188214e2c: cmp       w23, #1
0000000188214e30: b.ne      #0x188214e64
0000000188214e34: mov       w8, #4
0000000188214e38: b         #0x188214e68
0000000188214e3c: mov       w8, #7
0000000188214e40: b         #0x188214e68
0000000188214e44: ldr       x8, [x25, #0xbe0]
0000000188214e48: cmn       x8, #1
0000000188214e4c: b.ne      #0x18821531c
0000000188214e50: ldrb      w8, [x19, #0x7a8]
0000000188214e54: cmp       w8, #0
0000000188214e58: mov       w8, #3
0000000188214e5c: csel      x8, x8, xzr, eq
0000000188214e60: b         #0x188214e68
0000000188214e64: mov       x8, #0
0000000188214e68: adrp      x9, #0x1884e3000
0000000188214e6c: add       x9, x9, #0x378
0000000188214e70: ldrb      w28, [x9, x8]
0000000188214e74: ldr       x8, [x25, #0xbe0]
0000000188214e78: cmn       x8, #1
0000000188214e7c: b.ne      #0x188215304
0000000188214e80: ldrb      w8, [x19, #0x7a8]
0000000188214e84: cmp       w8, #0
0000000188214e88: and       w8, w23, #0xfffffffd
0000000188214e8c: ccmp      w8, #1, #0, ne
0000000188214e90: orr       w8, w28, #8
0000000188214e94: csel      w25, w8, w28, eq
0000000188214e98: add       x23, x20, #0xb0
0000000188214e9c: mov       x0, x23
0000000188214ea0: bl        #0x18db39534 ; call _os_unfair_lock_lock
0000000188214ea4: ldr       x0, [x20, #0xb8]
0000000188214ea8: mov       x2, x21
0000000188214eac: bl        #0x18853f4c0 ; call _objc_msgSend$containsObject:
0000000188214eb0: tbnz      w0, #0, #0x188214ec0
0000000188214eb4: ldr       x0, [x20, #0xb8]
0000000188214eb8: mov       x2, x21
0000000188214ebc: bl        #0x18853e420 ; call _objc_msgSend$addObject:
0000000188214ec0: mov       x0, x23
0000000188214ec4: bl        #0x18db3954c ; call _os_unfair_lock_unlock
0000000188214ec8: adrp      x8, #0x1dcc1e000
0000000188214ecc: ldr       x0, [x8, #0xe0] ; [0x1dcc1e0e0]=0x201e1b9b0e8
0000000188214ed0: bl        #0x188542840 ; call _objc_msgSend$mainDisplay
0000000188214ed4: bl        #0x188541080 ; call _objc_msgSend$hasNativeFrameRateRequest
0000000188214ed8: and       w8, w24, #2
0000000188214edc: lsr       w9, w24, #3
0000000188214ee0: lsl       w10, w8, #0x1e
0000000188214ee4: bfi       w10, w9, #0x1a, #1
0000000188214ee8: and       w9, w27, #0x10
0000000188214eec: orr       w10, w10, w26
0000000188214ef0: orr       w24, w10, w9, lsl #24
0000000188214ef4: adrp      x9, #0x1884d4000
0000000188214ef8: ldr       d0, [x9, #0x418] ; [0x1884d4418]=0x3f831d5acb6f4650
0000000188214efc: fcmp      d8, d0
0000000188214f00: ccmp      w8, #0, #4, hi
0000000188214f04: cset      w8, eq
0000000188214f08: and       w8, w8, w0
0000000188214f0c: cmp       w8, #1
0000000188214f10: b.ne      #0x188214f24
0000000188214f14: ldrh      w8, [x20, #0x108]
0000000188214f18: orr       w9, w24, #0x8000000
0000000188214f1c: tst       w8, #0x40
0000000188214f20: csel      w24, w9, w24, eq
0000000188214f24: mov       x0, x21
0000000188214f28: bl        #0x1885400e0 ; call _objc_msgSend$dirtyRect
0000000188214f2c: fmov      d11, d0
0000000188214f30: fmov      d9, d1
0000000188214f34: fmov      d12, d2
0000000188214f38: fmov      d10, d3
0000000188214f3c: adrp      x8, #0x1daad0000
0000000188214f40: ldr       x8, [x8, #0xa50] ; [0x1daad0a50]=0x20188cb7290
0000000188214f44: ldp       d4, d5, [x8]
0000000188214f48: ldp       d6, d7, [x8, #0x10]
0000000188214f4c: bl        #0x18db37b9c ; call _CGRectEqualToRect
0000000188214f50: tbz       w0, #0, #0x188214f60
0000000188214f54: adrp      x8, #0x1884d3000
0000000188214f58: ldr       q0, [x8, #0x430] ; [0x1884d3430]=0xe0000001e0000001
0000000188214f5c: b         #0x188214fac
0000000188214f60: stp       d11, d9, [sp, #0x40]
0000000188214f64: fcmp      d12, #0.0
0000000188214f68: stp       d12, d10, [sp, #0x50]
0000000188214f6c: b.pl      #0x188214f80
0000000188214f70: fadd      d0, d11, d12
0000000188214f74: fneg      d1, d12
0000000188214f78: str       d0, [sp, #0x40]
0000000188214f7c: str       d1, [sp, #0x50]
0000000188214f80: fcmp      d10, #0.0
0000000188214f84: b.pl      #0x188214f98
0000000188214f88: fadd      d0, d9, d10
0000000188214f8c: fneg      d1, d10
0000000188214f90: str       d0, [sp, #0x48]
0000000188214f94: str       d1, [sp, #0x58]
0000000188214f98: stp       xzr, xzr, [sp, #0x30]
0000000188214f9c: add       x0, sp, #0x30
0000000188214fa0: add       x1, sp, #0x40
0000000188214fa4: bl        #0x18825c9f0 ; call __ZN2CA6Bounds12set_exteriorERKNS_4RectE
0000000188214fa8: ldr       q0, [sp, #0x30]
0000000188214fac: ldr       x0, [x20, #0x10]
0000000188214fb0: ldr       x2, [x22, #0x18]
0000000188214fb4: ldr       d1, [x20, #0x20]
0000000188214fb8: ldr       d2, [x22, #0x30]
0000000188214fbc: str       q0, [sp, #0x20]
0000000188214fc0: adrp      x6, #0x188433000
0000000188214fc4: add       x6, x6, #0x5f0
0000000188214fc8: add       x5, sp, #0x20
0000000188214fcc: fmov      d0, d8
0000000188214fd0: mov       w1, #3
0000000188214fd4: mov       x3, x24
0000000188214fd8: mov       x4, x25
0000000188214fdc: mov       x7, x22
0000000188214fe0: bl        #0x188270a30 ; call _CAImageQueueInsertImage_
0000000188214fe4: cbz       w0, #0x188215100
0000000188214fe8: ldr       x8, [x20, #0x10]
0000000188214fec: ldr       x8, [x8, #0x30]
0000000188214ff0: ldr       x8, [x8, #0x18]
0000000188214ff4: ldr       w26, [x8, #0x1c]
0000000188214ff8: mov       x0, x21
0000000188214ffc: mov       x2, x26
0000000188215000: bl        #0x1885454a0 ; call _objc_msgSend$setInsertSeed:
0000000188215004: mov       x0, x21
0000000188215008: mov       w2, #1
000000018821500c: bl        #0x188546300 ; call _objc_msgSend$setStatus:
0000000188215010: bl        #0x18db38fac ; call _mach_absolute_time
0000000188215014: mov       x25, x0
0000000188215018: ldr       x19, [x20, #0xd8]
000000018821501c: fmov      d0, #1.00000000
0000000188215020: bl        #0x18822afc0 ; call _CAHostTimeWithTime
0000000188215024: add       x19, x0, x19
0000000188215028: add       x0, x20, #0xc8
000000018821502c: str       x0, [sp, #8]
0000000188215030: bl        #0x18db39534 ; call _os_unfair_lock_lock
0000000188215034: cmp       x25, x19
0000000188215038: b.ls      #0x188215160
000000018821503c: str       w26, [sp, #4]
0000000188215040: movi      v0.16b, #0
0000000188215044: stp       q0, q0, [x29, #-0xb0]
0000000188215048: stp       q0, q0, [x29, #-0xd0]
000000018821504c: ldr       x27, [x20, #0xd0]
0000000188215050: sub       x2, x29, #0xd0
0000000188215054: add       x3, sp, #0x60
0000000188215058: mov       x0, x27
000000018821505c: mov       w4, #0x10
0000000188215060: bl        #0x18853fa20 ; call _objc_msgSend$countByEnumeratingWithState:objects:count:
0000000188215064: mov       x28, x0
0000000188215068: cbz       x0, #0x1882150d8
000000018821506c: ldur      x8, [x29, #-0xc0]
0000000188215070: ldr       x19, [x8]
0000000188215074: mov       x26, #0
0000000188215078: ldur      x8, [x29, #-0xc0]
000000018821507c: ldr       x8, [x8]
0000000188215080: cmp       x8, x19
0000000188215084: b.eq      #0x188215090
0000000188215088: mov       x0, x27
000000018821508c: bl        #0x18db392b8 ; call _objc_enumerationMutation
0000000188215090: ldur      x8, [x29, #-0xc8]
0000000188215094: ldr       x25, [x8, x26, lsl #3]
0000000188215098: mov       x0, x25
000000018821509c: mov       w2, #3
00000001882150a0: bl        #0x188546300 ; call _objc_msgSend$setStatus:
00000001882150a4: fmov      d0, xzr
00000001882150a8: mov       x0, x25
00000001882150ac: bl        #0x1885400a0 ; call _objc_msgSend$didPresentAtTime:
00000001882150b0: add       x26, x26, #1
00000001882150b4: cmp       x28, x26
00000001882150b8: b.ne      #0x188215078
00000001882150bc: sub       x2, x29, #0xd0
00000001882150c0: add       x3, sp, #0x60
00000001882150c4: mov       x0, x27
00000001882150c8: mov       w4, #0x10
00000001882150cc: bl        #0x18853fa20 ; call _objc_msgSend$countByEnumeratingWithState:objects:count:
00000001882150d0: mov       x28, x0
00000001882150d4: cbnz      x0, #0x188215074
00000001882150d8: ldr       x0, [x20, #0xd0]
00000001882150dc: bl        #0x18853f8a0 ; call _objc_msgSend$copy
00000001882150e0: mov       x27, x0
00000001882150e4: ldr       x0, [x20, #0xd0]
00000001882150e8: bl        #0x188543e80 ; call _objc_msgSend$removeAllObjects
00000001882150ec: ldr       x0, [sp, #8]
00000001882150f0: bl        #0x18db3954c ; call _os_unfair_lock_unlock
00000001882150f4: bl        #0x18db393e4 ; call _objc_release_x27
00000001882150f8: ldr       w26, [sp, #4]
00000001882150fc: b         #0x188215174
0000000188215100: ldrb      w8, [x22, #0x69]
0000000188215104: and       w8, w8, #0xfffffff7
0000000188215108: strb      w8, [x22, #0x69]
000000018821510c: mov       x0, x23
0000000188215110: bl        #0x18db39534 ; call _os_unfair_lock_lock
0000000188215114: mov       x0, x21
0000000188215118: bl        #0x1885400c0 ; call _objc_msgSend$didScheduledPresent
000000018821511c: mov       x0, x21
0000000188215120: mov       w2, #1
0000000188215124: bl        #0x188545d80 ; call _objc_msgSend$setPresentScheduledInsertSeedValid:
0000000188215128: mov       x0, x23
000000018821512c: bl        #0x18db3954c ; call _os_unfair_lock_unlock
0000000188215130: adrp      x19, #0x1dcc23000
0000000188215134: ldr       x0, [x19, #0xbd8] ; [0x1dcc23bd8]=0x0
0000000188215138: mov       x1, x20
000000018821513c: bl        #0x18db39750 ; call _pthread_setspecific
0000000188215140: ldr       x1, [x22, #0x18]
0000000188215144: mov       w0, #3
0000000188215148: mov       x2, x22
000000018821514c: bl        #0x1884335f0 ; call __ZL14release_samplejyPv.8416
0000000188215150: ldr       x0, [x19, #0xbd8] ; [0x1dcc23bd8]=0x0
0000000188215154: mov       x1, #0
0000000188215158: bl        #0x18db39750 ; call _pthread_setspecific
000000018821515c: b         #0x1882152a8
0000000188215160: ldr       x0, [x20, #0xd0]
0000000188215164: mov       x2, x21
0000000188215168: bl        #0x18853e420 ; call _objc_msgSend$addObject:
000000018821516c: ldr       x0, [sp, #8]
0000000188215170: bl        #0x18db3954c ; call _os_unfair_lock_unlock
0000000188215174: ldrh      w8, [x20, #0x108]
0000000188215178: tbz       w8, #2, #0x1882151d8
000000018821517c: ldr       x8, [x20, #0x10]
0000000188215180: ldr       x10, [x8, #0x30]
0000000188215184: cbz       x10, #0x1882151d8
0000000188215188: ldr       x8, [x22, #0x50]
000000018821518c: ldr       x9, [x20, #0x40]
0000000188215190: ldr       x10, [x10, #0x18]
0000000188215194: ldr       w10, [x10, #0x18]
0000000188215198: cmp       w10, #0
000000018821519c: ccmp      w26, #3, #0, ne
00000001882151a0: b.lo      #0x1882151d8
00000001882151a4: ldrb      w10, [x22, #0x69]
00000001882151a8: tbnz      w10, #3, #0x1882151d8
00000001882151ac: cmp       x8, x9
00000001882151b0: b.ne      #0x1882151d8
00000001882151b4: mov       x0, x23
00000001882151b8: bl        #0x18db39534 ; call _os_unfair_lock_lock
00000001882151bc: mov       x0, x21
00000001882151c0: mov       x2, x26
00000001882151c4: bl        #0x188545d60 ; call _objc_msgSend$setPresentScheduledInsertSeed:
00000001882151c8: mov       x0, x21
00000001882151cc: mov       w2, #1
00000001882151d0: bl        #0x188545d80 ; call _objc_msgSend$setPresentScheduledInsertSeedValid:
00000001882151d4: b         #0x188215200
00000001882151d8: ldrb      w8, [x22, #0x69]
00000001882151dc: and       w8, w8, #0xfffffff7
00000001882151e0: strb      w8, [x22, #0x69]
00000001882151e4: mov       x0, x23
00000001882151e8: bl        #0x18db39534 ; call _os_unfair_lock_lock
00000001882151ec: mov       x0, x21
00000001882151f0: bl        #0x1885400c0 ; call _objc_msgSend$didScheduledPresent
00000001882151f4: mov       x0, x21
00000001882151f8: mov       w2, #1
00000001882151fc: bl        #0x188545d80 ; call _objc_msgSend$setPresentScheduledInsertSeedValid:
0000000188215200: mov       x0, x23
0000000188215204: bl        #0x18db3954c ; call _os_unfair_lock_unlock
0000000188215208: tbnz      w24, #1, #0x188215294
000000018821520c: tbz       w24, #2, #0x1882152a8
0000000188215210: add       x8, x20, #4
0000000188215214: ldaxr     w9, [x8]
0000000188215218: orr       w9, w9, #2
000000018821521c: stlxr     w10, w9, [x8]
0000000188215220: cbnz      w10, #0x188215214
0000000188215224: ldr       x0, [sp, #0x18]
0000000188215228: bl        #0x18db3954c ; call _os_unfair_lock_unlock
000000018821522c: adrp      x19, #0x1dcc1e000
0000000188215230: ldr       x0, [x19, #0x2f8] ; [0x1dcc1e2f8]=0x201e1b9b048
0000000188215234: bl        #0x1885426e0 ; call _objc_msgSend$lock
0000000188215238: ldr       w8, [sp, #0x14]
000000018821523c: cbz       w8, #0x18821524c
0000000188215240: ldr       x0, [x19, #0x2f8] ; [0x1dcc1e2f8]=0x201e1b9b048
0000000188215244: mov       w2, #1
0000000188215248: bl        #0x188545860 ; call _objc_msgSend$setLowLatency:
000000018821524c: ldr       d0, [x20, #0x20]
0000000188215250: fcmp      d0, #0.0
0000000188215254: b.eq      #0x188215260
0000000188215258: ldr       x0, [x19, #0x2f8]
000000018821525c: bl        #0x188545480 ; call _objc_msgSend$setInputTime:
0000000188215260: ldr       x22, [x20, #0x18]
0000000188215264: cbz       x22, #0x188215288
0000000188215268: mrs       x8, tpidrro_el0
000000018821526c: ldr       x1, [x8, #0x240]
0000000188215270: cbnz      x1, #0x18821527c
0000000188215274: bl        #0x1882d30fc ; call __ZN2CA11Transaction6createEv
0000000188215278: mov       x1, x0
000000018821527c: ldr       x0, [x22, #0x10]
0000000188215280: mov       w2, #0
0000000188215284: bl        #0x18828ba94 ; call __ZN2CA5Layer17set_commit_neededEPNS_11TransactionEj
0000000188215288: ldr       x0, [x19, #0x2f8]
000000018821528c: bl        #0x188547880 ; call _objc_msgSend$unlock
0000000188215290: b         #0x1882152b0
0000000188215294: add       x8, x20, #4
0000000188215298: ldaxr     w9, [x8]
000000018821529c: and       w9, w9, #0xfffffffd
00000001882152a0: stlxr     w10, w9, [x8]
00000001882152a4: cbnz      w10, #0x188215298
00000001882152a8: ldr       x0, [sp, #0x18]
00000001882152ac: bl        #0x18db3954c ; call _os_unfair_lock_unlock
00000001882152b0: str       xzr, [x20, #0x20]
00000001882152b4: mov       x0, x21
00000001882152b8: mov       x2, x20
00000001882152bc: bl        #0x188543e20 ; call _objc_msgSend$releasePrivateReferences:
00000001882152c0: ldur      x8, [x29, #-0x90]
00000001882152c4: adrp      x9, #0x1daabe000
00000001882152c8: ldr       x9, [x9, #0x7f0] ; [0x1daabe7f0]=0x201e1adb490
00000001882152cc: ldr       x9, [x9]
00000001882152d0: cmp       x9, x8
00000001882152d4: b.ne      #0x188215334
00000001882152d8: ldp       x29, x30, [sp, #0x1b0]
00000001882152dc: ldp       x20, x19, [sp, #0x1a0]
00000001882152e0: ldp       x22, x21, [sp, #0x190]
00000001882152e4: ldp       x24, x23, [sp, #0x180]
00000001882152e8: ldp       x26, x25, [sp, #0x170]
00000001882152ec: ldp       x28, x27, [sp, #0x160]
00000001882152f0: ldp       d9, d8, [sp, #0x150]
00000001882152f4: ldp       d11, d10, [sp, #0x140]
00000001882152f8: ldp       d13, d12, [sp, #0x130]
00000001882152fc: add       sp, sp, #0x1c0
0000000188215300: ret       
0000000188215304: adrp      x0, #0x1e1b9b000
0000000188215308: add       x0, x0, #0xbe0
000000018821530c: adrp      x1, #0x1d57fd000
0000000188215310: add       x1, x1, #0x68
0000000188215314: bl        #0x1884c950c ; x1 literal: ___block_literal_global.28
0000000188215318: b         #0x188214e80
000000018821531c: adrp      x0, #0x1e1b9b000
0000000188215320: add       x0, x0, #0xbe0
0000000188215324: adrp      x1, #0x1d57fd000
0000000188215328: add       x1, x1, #0x68
000000018821532c: bl        #0x1884c950c ; x1 literal: ___block_literal_global.28
0000000188215330: b         #0x188214e50
0000000188215334: bl        #0x18db38a60 ; call ___stack_chk_fail
0000000188215338: b         #0x18821535c
000000018821533c: b         #0x188215378
0000000188215340: b         #0x18821536c
0000000188215344: b         #0x188215378
0000000188215348: b         #0x188215378
000000018821534c: b         #0x18821536c
0000000188215350: b         #0x18821535c
0000000188215354: b         #0x18821535c
0000000188215358: b         #0x18821536c
000000018821535c: mov       x20, x0
0000000188215360: mov       x0, x23
0000000188215364: b         #0x188215380
0000000188215368: b         #0x18821536c
000000018821536c: mov       x20, x0
0000000188215370: b         #0x188215384
0000000188215374: b         #0x188215378
0000000188215378: mov       x20, x0
000000018821537c: ldr       x0, [sp, #8]
0000000188215380: bl        #0x18db3954c ; call _os_unfair_lock_unlock
0000000188215384: ldr       x0, [sp, #0x18]
0000000188215388: bl        #0x18db3954c ; call _os_unfair_lock_unlock
000000018821538c: mov       x0, x20
0000000188215390: bl        #0x18db388e0 ; call __Unwind_Resume
