0000000188433470: stp       x26, x25, [sp, #-0x50]!
0000000188433474: stp       x24, x23, [sp, #0x10]
0000000188433478: stp       x22, x21, [sp, #0x20]
000000018843347c: stp       x20, x19, [sp, #0x30]
0000000188433480: stp       x29, x30, [sp, #0x40]
0000000188433484: add       x29, sp, #0x40
0000000188433488: mov       x23, x7
000000018843348c: mov       x24, x6
0000000188433490: mov       x21, x5
0000000188433494: mov       x9, x4
0000000188433498: mov       x19, x1
000000018843349c: mov       x20, x0
00000001884334a0: adrp      x8, #0x1dcc1e000
00000001884334a4: ldr       x0, [x8, #0x3a8] ; [0x1dcc1e3a8]=0x201e1b2fa20
00000001884334a8: mov       w8, w2
00000001884334ac: mov       w4, w3
00000001884334b0: mov       x2, x9
00000001884334b4: mov       x3, x8
00000001884334b8: mov       w5, #0
00000001884334bc: bl        #0x1885474a0 ; call _objc_msgSend$texture2DDescriptorWithPixelFormat:width:height:mipmapped:
00000001884334c0: mov       x22, x0
00000001884334c4: mov       x0, x19
00000001884334c8: bl        #0x18db38640 ; call _IOSurfaceGetPixelFormat
00000001884334cc: mov       x25, x0
00000001884334d0: mov       w1, #0
00000001884334d4: mov       w2, #0
00000001884334d8: bl        #0x188251684 ; call __ZN2CA6Render25fourcc_compressed_of_typeEj24IOSurfaceCompressionType29IOSurfaceCompressionFootprint
00000001884334dc: mov       x26, x0
00000001884334e0: adrp      x8, #0x1e1b9b000
00000001884334e4: ldr       x8, [x8, #0xbe0] ; [0x1e1b9bbe0]=0x0
00000001884334e8: cmn       x8, #1
00000001884334ec: b.ne      #0x1884335c0
00000001884334f0: cmp       w26, w25
00000001884334f4: b.eq      #0x188433520
00000001884334f8: adrp      x8, #0x1e1b9b000
00000001884334fc: ldrb      w9, [x8, #0x7a8]
0000000188433500: cbz       w9, #0x188433520
0000000188433504: ldrb      w8, [x8, #0x7a8]
0000000188433508: cmp       w8, #0
000000018843350c: and       w8, w24, #0xfffffffd
0000000188433510: ccmp      w8, #1, #0, ne
0000000188433514: mov       w8, #4
0000000188433518: csel      x2, x8, xzr, eq
000000018843351c: b         #0x18843352c
0000000188433520: cmp       w24, #4
0000000188433524: b.hs      #0x1884335d8
0000000188433528: mov       w2, w24
000000018843352c: ldr       x24, [x29, #0x10]
0000000188433530: mov       x0, x22
0000000188433534: bl        #0x188545fc0 ; call _objc_msgSend$setRotation:
0000000188433538: mov       x0, x22
000000018843353c: mov       w2, #1
0000000188433540: bl        #0x1885455e0 ; call _objc_msgSend$setIsDrawable:
0000000188433544: cbz       w23, #0x18843355c
0000000188433548: mov       x0, x22
000000018843354c: mov       w2, #1
0000000188433550: bl        #0x188545240 ; call _objc_msgSend$setFramebufferOnly:
0000000188433554: mov       w2, #4
0000000188433558: b         #0x188433560
000000018843355c: ldr       x2, [x29, #0x18]
0000000188433560: mov       x0, x22
0000000188433564: bl        #0x1885466a0 ; call _objc_msgSend$setUsage:
0000000188433568: cbz       x21, #0x188433584
000000018843356c: mov       x0, x22
0000000188433570: mov       w2, #1
0000000188433574: bl        #0x188545180 ; call _objc_msgSend$setForceResourceIndex:
0000000188433578: mov       x0, x22
000000018843357c: mov       x2, x21
0000000188433580: bl        #0x188545f80 ; call _objc_msgSend$setResourceIndex:
0000000188433584: mov       x0, x20
0000000188433588: mov       x2, x22
000000018843358c: mov       x3, x19
0000000188433590: mov       x4, #0
0000000188433594: bl        #0x188543060 ; call _objc_msgSend$newTextureWithDescriptor:iosurface:plane:
0000000188433598: mov       x19, x0
000000018843359c: mov       x2, x24
00000001884335a0: bl        #0x188545660 ; call _objc_msgSend$setLabel:
00000001884335a4: mov       x0, x19
00000001884335a8: ldp       x29, x30, [sp, #0x40]
00000001884335ac: ldp       x20, x19, [sp, #0x30]
00000001884335b0: ldp       x22, x21, [sp, #0x20]
00000001884335b4: ldp       x24, x23, [sp, #0x10]
00000001884335b8: ldp       x26, x25, [sp], #0x50
00000001884335bc: ret       
00000001884335c0: adrp      x0, #0x1e1b9b000
00000001884335c4: add       x0, x0, #0xbe0
00000001884335c8: adrp      x1, #0x1d57fd000
00000001884335cc: add       x1, x1, #0x68
00000001884335d0: bl        #0x1884c950c ; x1 literal: ___block_literal_global.28
00000001884335d4: b         #0x1884334f0
00000001884335d8: bl        #0x18db38ab4 ; call _abort
