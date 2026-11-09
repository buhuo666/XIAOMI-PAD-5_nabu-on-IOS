000000018821de60: sub       sp, sp, #0xb0
000000018821de64: stp       d13, d12, [sp, #0x20]
000000018821de68: stp       d11, d10, [sp, #0x30]
000000018821de6c: stp       d9, d8, [sp, #0x40]
000000018821de70: stp       x28, x27, [sp, #0x50]
000000018821de74: stp       x26, x25, [sp, #0x60]
000000018821de78: stp       x24, x23, [sp, #0x70]
000000018821de7c: stp       x22, x21, [sp, #0x80]
000000018821de80: stp       x20, x19, [sp, #0x90]
000000018821de84: stp       x29, x30, [sp, #0xa0]
000000018821de88: add       x29, sp, #0xa0
000000018821de8c: mov       x23, x0
000000018821de90: adrp      x8, #0x1dcc1e000
000000018821de94: ldrsw     x8, [x8, #0xbe4]
000000018821de98: ldr       x21, [x0, x8]
000000018821de9c: ldr       x8, [x21, #0x10]
000000018821dea0: ldr       x8, [x8, #0x30]
000000018821dea4: cbz       x8, #0x18821deb4
000000018821dea8: ldr       x8, [x8, #0x18]
000000018821deac: ldr       w20, [x8, #0xc]
000000018821deb0: b         #0x18821deb8
000000018821deb4: mov       w20, #0
000000018821deb8: add       x19, x21, #8
000000018821debc: mov       x0, x19
000000018821dec0: bl        #0x18db39534 ; call _os_unfair_lock_lock
000000018821dec4: ldr       x8, [x21, #0x40]
000000018821dec8: cbz       x8, #0x18821dfb0
000000018821decc: mov       x22, x21
000000018821ded0: ldr       w8, [x22, #4]!
000000018821ded4: tbnz      w8, #0, #0x18821df20
000000018821ded8: mov       x0, x23
000000018821dedc: bl        #0x188546b40 ; call _objc_msgSend$size
000000018821dee0: fmov      d8, d0
000000018821dee4: fmov      d9, d1
000000018821dee8: mov       x0, x23
000000018821deec: bl        #0x18853f6a0 ; call _objc_msgSend$contentsScale
000000018821def0: fmul      d1, d8, d0
000000018821def4: fmul      d0, d9, d0
000000018821def8: fcvtzu    w8, d1
000000018821defc: fcvtzu    w9, d0
000000018821df00: stp       w8, w9, [x21, #0x70]
000000018821df04: ldaxr     w8, [x22]
000000018821df08: orr       w8, w8, #1
000000018821df0c: stlxr     w9, w8, [x22]
000000018821df10: cbnz      w9, #0x18821df04
000000018821df14: ldr       x0, [x21, #0x10]
000000018821df18: ldp       w1, w2, [x21, #0x70]
000000018821df1c: bl        #0x1882ed100 ; call _CAImageQueueSetSize
000000018821df20: str       x23, [sp, #0x10]
000000018821df24: mov       w22, #0
000000018821df28: tst       w20, #0x8000000
000000018821df2c: cset      w27, eq
000000018821df30: ldrh      w8, [x21, #0x108]
000000018821df34: tbz       w8, #4, #0x18821dfc4
000000018821df38: tbnz      w27, #0, #0x18821dfc4
000000018821df3c: adrp      x8, #0x1e1b9c000
000000018821df40: ldr       x8, [x8, #0x1e0] ; [0x1e1b9c1e0]=0x0
000000018821df44: cmn       x8, #1
000000018821df48: b.ne      #0x18821e4b8
000000018821df4c: adrp      x8, #0x1e1b9b000
000000018821df50: ldrb      w8, [x8, #0x8c8]
000000018821df54: cbz       w8, #0x18821df74
000000018821df58: adrp      x8, #0x1e1b9b000
000000018821df5c: ldr       x8, [x8, #0xbe0] ; [0x1e1b9bbe0]=0x0
000000018821df60: cmn       x8, #1
000000018821df64: b.ne      #0x18821e4d0
000000018821df68: adrp      x8, #0x1e1b9b000
000000018821df6c: ldrb      w8, [x8, #0x7a8]
000000018821df70: cbz       w8, #0x18821dfc0
000000018821df74: ldr       x8, [x21, #0x10]
000000018821df78: ldr       x8, [x8, #0x30]
000000018821df7c: ldr       x8, [x8, #0x18]
000000018821df80: ldrb      w8, [x8, #0x4c]
000000018821df84: ands      w9, w8, #3
000000018821df88: cset      w10, ne
000000018821df8c: lsl       w10, w10, #1
000000018821df90: mov       w11, #3
000000018821df94: csinc     w11, w11, wzr, ne
000000018821df98: tst       w8, #4
000000018821df9c: csel      w8, w10, w11, eq
000000018821dfa0: cmp       w9, #3
000000018821dfa4: ccmp      w9, #0, #4, ne
000000018821dfa8: csel      w22, wzr, w8, ne
000000018821dfac: b         #0x18821dfc4
000000018821dfb0: adrp      x0, #0x1d5812000
000000018821dfb4: add       x0, x0, #0xc18
000000018821dfb8: bl        #0x18db38808 ; call _NSLog
000000018821dfbc: b         #0x18821e464
000000018821dfc0: mov       w22, #0
000000018821dfc4: ldrh      w8, [x21, #0x108]
000000018821dfc8: ldr       x0, [x21, #0x10]
000000018821dfcc: adrp      x28, #0x1dcc23000
000000018821dfd0: ubfx      w9, w20, #0x1b, #1
000000018821dfd4: str       w9, [sp, #0x1c]
000000018821dfd8: tbz       w8, #2, #0x18821dff0
000000018821dfdc: ldr       x8, [x0, #0x30]
000000018821dfe0: cbz       x8, #0x18821dff0
000000018821dfe4: ldr       x8, [x8, #0x18]
000000018821dfe8: ldr       w8, [x8, #0x18]
000000018821dfec: cbnz      w8, #0x18821e004
000000018821dff0: mov       w1, #0
000000018821dff4: bl        #0x1882f2160 ; call _CAImageQueueConsumeUnconsumed_
000000018821dff8: mov       w26, #0
000000018821dffc: ldrh      w8, [x21, #0x108]
000000018821e000: tbz       w8, #2, #0x18821e368
000000018821e004: mov       w25, #0
000000018821e008: str       wzr, [sp, #0x18]
000000018821e00c: add       x24, x21, #0x90
000000018821e010: fmov      d10, xzr
000000018821e014: adrp      x8, #0x1884d4000
000000018821e018: ldr       d8, [x8, #0x180] ; [0x1884d4180]=0x3fc999999999999a
000000018821e01c: mov       w20, #1
000000018821e020: adrp      x8, #0x1884d4000
000000018821e024: ldr       d11, [x8, #0x268] ; [0x1884d4268]=0x41cdcd6500000000
000000018821e028: adrp      x8, #0x1884d3000
000000018821e02c: ldr       d12, [x8, #0xc98] ; [0x1884d3c98]=0x3fa999999999999a
000000018821e030: ldr       x8, [x21, #0x10]
000000018821e034: ldr       x8, [x8, #0x30]
000000018821e038: cbz       x8, #0x18821e364
000000018821e03c: ldr       x8, [x8, #0x18]
000000018821e040: ldr       w8, [x8, #0x18]
000000018821e044: cmp       w8, #0
000000018821e048: cset      w26, ne
000000018821e04c: cset      w8, eq
000000018821e050: orr       w8, w8, w25
000000018821e054: tbnz      w8, #0, #0x18821e368
000000018821e058: ldr       x23, [x21, #0xc0]
000000018821e05c: fmov      d0, d8
000000018821e060: bl        #0x18822afc0 ; call _CAHostTimeWithTime
000000018821e064: mov       x25, x0
000000018821e068: bl        #0x18db38fac ; call _mach_absolute_time
000000018821e06c: add       x8, x25, x23
000000018821e070: cmp       x0, x8
000000018821e074: b.hi      #0x18821e368
000000018821e078: ldr       x8, [x21, #0x40]
000000018821e07c: cbz       x8, #0x18821e448
000000018821e080: ldrh      w8, [x21, #0x108]
000000018821e084: lsr       w9, w8, #1
000000018821e088: and       w9, w9, #0x40
000000018821e08c: and       w8, w8, #0xffffffbf
000000018821e090: orr       w8, w9, w8
000000018821e094: strh      w8, [x21, #0x108]
000000018821e098: ldr       x0, [x21, #0x10]
000000018821e09c: lsl       w2, w9, #0x18
000000018821e0a0: mov       w1, #0x40000000
000000018821e0a4: bl        #0x1882e6788 ; call _CAImageQueueSetFlags
000000018821e0a8: ldrh      w8, [x21, #0x108]
000000018821e0ac: mov       w9, #0x48
000000018821e0b0: tst       w8, w9
000000018821e0b4: b.eq      #0x18821e0c8
000000018821e0b8: ldr       w8, [x21, #0x7c]
000000018821e0bc: cmp       w8, #3
000000018821e0c0: cset      w25, eq
000000018821e0c4: b         #0x18821e0cc
000000018821e0c8: mov       w25, #0
000000018821e0cc: ldr       x0, [x28, #0xbd8]
000000018821e0d0: mov       x1, x21
000000018821e0d4: bl        #0x18db39750 ; call _pthread_setspecific
000000018821e0d8: ldr       x0, [x21, #0x10]
000000018821e0dc: mov       w1, #0
000000018821e0e0: mov       x2, x25
000000018821e0e4: bl        #0x18826ee4c ; call _CAImageQueueCollect_
000000018821e0e8: mov       x25, x0
000000018821e0ec: ldr       x0, [x28, #0xbd8]
000000018821e0f0: mov       x1, #0
000000018821e0f4: bl        #0x18db39750 ; call _pthread_setspecific
000000018821e0f8: cbz       x25, #0x18821e138
000000018821e0fc: ldr       w8, [x21, #0x7c]
000000018821e100: cmp       x8, #2
000000018821e104: cset      w9, hi
000000018821e108: orr       w9, w9, w27
000000018821e10c: tbnz      w9, #0, #0x18821e11c
000000018821e110: add       x8, x8, x25
000000018821e114: subs      x25, x8, #3
000000018821e118: b.eq      #0x18821e138
000000018821e11c: mov       x0, x21
000000018821e120: mov       x1, x22
000000018821e124: ldr       w2, [sp, #0x1c]
000000018821e128: mov       w3, #1
000000018821e12c: bl        #0x1882fcff8 ; call __ZL19get_unused_drawableP20_CAMetalLayerPrivate20CAMetalLayerRotationbb
000000018821e130: mov       x26, x0
000000018821e134: cbnz      x0, #0x18821e2fc
000000018821e138: mov       x0, x19
000000018821e13c: bl        #0x18db3954c ; call _os_unfair_lock_unlock
000000018821e140: bl        #0x18db38fac ; call _mach_absolute_time
000000018821e144: bl        #0x188236490 ; call _CATimeWithHostTime
000000018821e148: fmov      d9, d0
000000018821e14c: fcmp      d10, #0.0
000000018821e150: b.ne      #0x18821e224
000000018821e154: fmov      d10, d9
000000018821e158: mov       w0, #0x141
000000018821e15c: movk      w0, #0x31ca, lsl #16
000000018821e160: mov       x1, #0
000000018821e164: mov       x2, #0
000000018821e168: mov       x3, #0
000000018821e16c: mov       x4, #0
000000018821e170: bl        #0x18db38f70 ; call _kdebug_trace
000000018821e174: ldaxr     w8, [x24]
000000018821e178: cmp       w8, #2
000000018821e17c: b.ne      #0x18821e194
000000018821e180: stlxr     w8, wzr, [x24]
000000018821e184: cbnz      w8, #0x18821e174
000000018821e188: mov       w25, #1
000000018821e18c: tbz       w25, #0, #0x18821e1a0
000000018821e190: b         #0x18821e29c
000000018821e194: mov       w25, #0
000000018821e198: clrex
000000018821e19c: tbnz      w25, #0, #0x18821e29c
000000018821e1a0: ldaxr     w8, [x24]
000000018821e1a4: cbnz      w8, #0x18821e1d8
000000018821e1a8: stlxr     w8, w20, [x24]
000000018821e1ac: cbnz      w8, #0x18821e1a0
000000018821e1b0: ldr       d0, [x21, #0x28]
000000018821e1b4: fmul      d0, d0, d11
000000018821e1b8: fcvtzs    x1, d0
000000018821e1bc: mov       x0, #0
000000018821e1c0: bl        #0x1884c9608
000000018821e1c4: mov       x1, x0
000000018821e1c8: ldr       x0, [x21, #0x88]
000000018821e1cc: bl        #0x1884c9584
000000018821e1d0: cbz       x0, #0x18821e1dc
000000018821e1d4: b         #0x18821e20c
000000018821e1d8: clrex
000000018821e1dc: ldaxr     w8, [x24]
000000018821e1e0: cmp       w8, #2
000000018821e1e4: b.ne      #0x18821e1fc
000000018821e1e8: stlxr     w8, wzr, [x24]
000000018821e1ec: cbnz      w8, #0x18821e1dc
000000018821e1f0: mov       w25, #1
000000018821e1f4: cbz       w25, #0x18821e1a0
000000018821e1f8: b         #0x18821e29c
000000018821e1fc: mov       w25, #0
000000018821e200: clrex
000000018821e204: cbz       w25, #0x18821e1a0
000000018821e208: b         #0x18821e29c
000000018821e20c: ldaxr     w8, [x24]
000000018821e210: cmp       w8, #1
000000018821e214: b.ne      #0x18821e28c
000000018821e218: stlxr     w8, wzr, [x24]
000000018821e21c: cbnz      w8, #0x18821e20c
000000018821e220: b         #0x18821e29c
000000018821e224: ldr       w8, [sp, #0x18]
000000018821e228: tbnz      w8, #0, #0x18821e248
000000018821e22c: fadd      d0, d10, d12
000000018821e230: fcmp      d9, d0
000000018821e234: b.le      #0x18821e248
000000018821e238: mov       x0, #2
000000018821e23c: movk      x0, #4, lsl #48
000000018821e240: bl        #0x18db38e74 ; call _dyld_program_sdk_at_least
000000018821e244: tbz       w0, #0, #0x18821e264
000000018821e248: ldrh      w8, [x21, #0x108]
000000018821e24c: tbz       w8, #5, #0x18821e158
000000018821e250: ldr       d0, [x21, #0x28]
000000018821e254: fadd      d0, d10, d0
000000018821e258: fcmp      d9, d0
000000018821e25c: b.le      #0x18821e158
000000018821e260: b         #0x18821e4a0
000000018821e264: bl        #0x18db3927c ; call _objc_autoreleasePoolPush
000000018821e268: mov       x26, x0
000000018821e26c: adrp      x8, #0x1dcc1e000
000000018821e270: ldr       x0, [x8, #0x2f8] ; [0x1dcc1e2f8]=0x201e1b9b048
000000018821e274: bl        #0x188540c20 ; call _objc_msgSend$flush
000000018821e278: mov       x0, x26
000000018821e27c: bl        #0x1884c9a4c
000000018821e280: mov       w8, #1
000000018821e284: str       w8, [sp, #0x18]
000000018821e288: b         #0x18821e158
000000018821e28c: clrex
000000018821e290: ldr       x0, [x21, #0x88]
000000018821e294: mov       x1, #-1
000000018821e298: bl        #0x1884c9584
000000018821e29c: eor       w25, w25, #1
000000018821e2a0: mov       w0, #0x142
000000018821e2a4: movk      w0, #0x31ca, lsl #16
000000018821e2a8: mov       x1, #0
000000018821e2ac: mov       x2, #0
000000018821e2b0: mov       x3, #0
000000018821e2b4: mov       x4, #0
000000018821e2b8: bl        #0x18db38f70 ; call _kdebug_trace
000000018821e2bc: mov       x0, x19
000000018821e2c0: bl        #0x18db39534 ; call _os_unfair_lock_lock
000000018821e2c4: ldrh      w8, [x21, #0x108]
000000018821e2c8: tbnz      w8, #2, #0x18821e030
000000018821e2cc: b         #0x18821e364
000000018821e2d0: mov       x25, x0
000000018821e2d4: cmp       w1, #1
000000018821e2d8: b.ne      #0x18821e51c
000000018821e2dc: mov       x0, x25
000000018821e2e0: bl        #0x18db39288 ; call _objc_begin_catch
000000018821e2e4: str       x0, [sp]
000000018821e2e8: adrp      x0, #0x1d5806000
000000018821e2ec: add       x0, x0, #0x4f8
000000018821e2f0: bl        #0x18db38808 ; call _NSLog
000000018821e2f4: bl        #0x18db392ac ; call _objc_end_catch
000000018821e2f8: b         #0x18821e278
000000018821e2fc: ldaxr     w8, [x26]
000000018821e300: add       w8, w8, #1
000000018821e304: stlxr     w9, w8, [x26]
000000018821e308: cbnz      w9, #0x18821e2fc
000000018821e30c: str       x21, [x26, #0x38]
000000018821e310: bl        #0x18db38fac ; call _mach_absolute_time
000000018821e314: bl        #0x188236490 ; call _CATimeWithHostTime
000000018821e318: str       d0, [x26, #0x30]
000000018821e31c: ldr       x0, [x26, #0x40]
000000018821e320: bl        #0x18db38634 ; call _IOSurfaceGetID
000000018821e324: ldr       x20, [sp, #0x10]
000000018821e328: mov       w1, w0
000000018821e32c: mov       w0, #0x14c
000000018821e330: movk      w0, #0x31ca, lsl #16
000000018821e334: mov       w2, #1
000000018821e338: mov       x3, x25
000000018821e33c: mov       x4, #0
000000018821e340: bl        #0x18db38f70 ; call _kdebug_trace
000000018821e344: adrp      x8, #0x1dcc1e000
000000018821e348: ldr       x0, [x8, #0x430] ; [0x1dcc1e430]=0x201e1b9a738
000000018821e34c: bl        #0x18db3924c ; call _objc_alloc
000000018821e350: mov       x2, x26
000000018821e354: mov       x3, x20
000000018821e358: bl        #0x188541780 ; call _objc_msgSend$initWithDrawablePrivate:layer:
000000018821e35c: bl        #0x18db39264 ; call _objc_autorelease
000000018821e360: b         #0x18821e440
000000018821e364: mov       w26, #0
000000018821e368: mov       x0, x19
000000018821e36c: bl        #0x18db3954c ; call _os_unfair_lock_unlock
000000018821e370: mov       x0, x21
000000018821e374: bl        #0x188214650 ; call __ZL31layer_private_cleanup_callbacksP20_CAMetalLayerPrivate
000000018821e378: mov       x0, x19
000000018821e37c: bl        #0x18db39534 ; call _os_unfair_lock_lock
000000018821e380: ldr       x8, [x21, #0x40]
000000018821e384: cbz       x8, #0x18821e448
000000018821e388: ldr       x0, [x28, #0xbd8]
000000018821e38c: mov       x1, x21
000000018821e390: bl        #0x18db39750 ; call _pthread_setspecific
000000018821e394: ldr       x0, [x21, #0x10]
000000018821e398: mov       w1, #0
000000018821e39c: mov       w2, #0
000000018821e3a0: bl        #0x18826ee4c ; call _CAImageQueueCollect_
000000018821e3a4: mov       x24, x0
000000018821e3a8: ldr       x0, [x28, #0xbd8]
000000018821e3ac: mov       x1, #0
000000018821e3b0: bl        #0x18db39750 ; call _pthread_setspecific
000000018821e3b4: mov       x0, x21
000000018821e3b8: mov       x1, x22
000000018821e3bc: ldr       w2, [sp, #0x1c]
000000018821e3c0: mov       w3, #0
000000018821e3c4: bl        #0x1882fcff8 ; call __ZL19get_unused_drawableP20_CAMetalLayerPrivate20CAMetalLayerRotationbb
000000018821e3c8: ldr       x20, [sp, #0x10]
000000018821e3cc: mov       x22, x0
000000018821e3d0: cbz       x0, #0x18821e458
000000018821e3d4: ldrb      w8, [x22, #0x69]
000000018821e3d8: orr       w8, w8, #8
000000018821e3dc: strb      w8, [x22, #0x69]
000000018821e3e0: ldaxr     w8, [x22]
000000018821e3e4: add       w8, w8, #1
000000018821e3e8: stlxr     w9, w8, [x22]
000000018821e3ec: cbnz      w9, #0x18821e3e0
000000018821e3f0: str       x21, [x22, #0x38]
000000018821e3f4: bl        #0x18db38fac ; call _mach_absolute_time
000000018821e3f8: bl        #0x188236490 ; call _CATimeWithHostTime
000000018821e3fc: str       d0, [x22, #0x30]
000000018821e400: ldr       x0, [x22, #0x40]
000000018821e404: bl        #0x18db38634 ; call _IOSurfaceGetID
000000018821e408: mov       w1, w0
000000018821e40c: mov       w2, w26
000000018821e410: mov       w0, #0x14c
000000018821e414: movk      w0, #0x31ca, lsl #16
000000018821e418: mov       x3, x24
000000018821e41c: mov       x4, #0
000000018821e420: bl        #0x18db38f70 ; call _kdebug_trace
000000018821e424: adrp      x8, #0x1dcc1e000
000000018821e428: ldr       x0, [x8, #0x430] ; [0x1dcc1e430]=0x201e1b9a738
000000018821e42c: bl        #0x18db3924c ; call _objc_alloc
000000018821e430: mov       x2, x22
000000018821e434: mov       x3, x20
000000018821e438: bl        #0x188541780 ; call _objc_msgSend$initWithDrawablePrivate:layer:
000000018821e43c: bl        #0x18db39264 ; call _objc_autorelease
000000018821e440: mov       x20, x0
000000018821e444: b         #0x18821e468
000000018821e448: adrp      x0, #0x1d5812000
000000018821e44c: add       x0, x0, #0xc18
000000018821e450: bl        #0x18db38808 ; call _NSLog
000000018821e454: b         #0x18821e464
000000018821e458: adrp      x0, #0x1d5812000
000000018821e45c: add       x0, x0, #0xc38
000000018821e460: bl        #0x18db38808 ; call _NSLog
000000018821e464: mov       x20, #0
000000018821e468: mov       x0, x19
000000018821e46c: bl        #0x18db3954c ; call _os_unfair_lock_unlock
000000018821e470: mov       x0, x20
000000018821e474: ldp       x29, x30, [sp, #0xa0]
000000018821e478: ldp       x20, x19, [sp, #0x90]
000000018821e47c: ldp       x22, x21, [sp, #0x80]
000000018821e480: ldp       x24, x23, [sp, #0x70]
000000018821e484: ldp       x26, x25, [sp, #0x60]
000000018821e488: ldp       x28, x27, [sp, #0x50]
000000018821e48c: ldp       d9, d8, [sp, #0x40]
000000018821e490: ldp       d11, d10, [sp, #0x30]
000000018821e494: ldp       d13, d12, [sp, #0x20]
000000018821e498: add       sp, sp, #0xb0
000000018821e49c: ret
000000018821e4a0: adrp      x0, #0x1d5812000
000000018821e4a4: add       x0, x0, #0xc58
000000018821e4a8: bl        #0x18db38808 ; call _NSLog
000000018821e4ac: mov       x0, x19
000000018821e4b0: bl        #0x18db39534 ; call _os_unfair_lock_lock
000000018821e4b4: b         #0x18821e464
000000018821e4b8: adrp      x0, #0x1e1b9c000
000000018821e4bc: add       x0, x0, #0x1e0
000000018821e4c0: adrp      x1, #0x1d57fc000
000000018821e4c4: add       x1, x1, #0xfe8
000000018821e4c8: bl        #0x1884c950c ; x1 literal: ___block_literal_global.16
000000018821e4cc: b         #0x18821df4c
000000018821e4d0: adrp      x0, #0x1e1b9b000
000000018821e4d4: add       x0, x0, #0xbe0
000000018821e4d8: adrp      x1, #0x1d57fd000
000000018821e4dc: add       x1, x1, #0x68
000000018821e4e0: bl        #0x1884c950c ; x1 literal: ___block_literal_global.28
000000018821e4e4: b         #0x18821df68
000000018821e4e8: mov       x25, x0
000000018821e4ec: bl        #0x18db392ac ; call _objc_end_catch
000000018821e4f0: b         #0x18821e51c
000000018821e4f4: b         #0x18821e518
000000018821e4f8: b         #0x18821e528
000000018821e4fc: b         #0x18821e528
000000018821e500: b         #0x18821e528
000000018821e504: b         #0x18821e528
000000018821e508: b         #0x18821e518
000000018821e50c: b         #0x18821e528
000000018821e510: b         #0x18821e528
000000018821e514: b         #0x18821e528
000000018821e518: mov       x25, x0
000000018821e51c: mov       x0, x19
000000018821e520: bl        #0x18db39534 ; call _os_unfair_lock_lock
000000018821e524: b         #0x18821e52c
000000018821e528: mov       x25, x0
000000018821e52c: mov       x0, x19
000000018821e530: bl        #0x18db3954c ; call _os_unfair_lock_unlock
000000018821e534: mov       x0, x25
000000018821e538: bl        #0x18db388e0 ; call __Unwind_Resume
