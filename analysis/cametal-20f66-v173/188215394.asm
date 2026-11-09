0000000188215394: stp       x22, x21, [sp, #-0x30]!
0000000188215398: stp       x20, x19, [sp, #0x10]
000000018821539c: stp       x29, x30, [sp, #0x20]
00000001882153a0: add       x29, sp, #0x20
00000001882153a4: str       xzr, [x0, #8]
00000001882153a8: cbz       x2, #0x188215420
00000001882153ac: mov       x19, x2
00000001882153b0: mov       x21, x0
00000001882153b4: add       x20, x2, #0xc8
00000001882153b8: mov       x0, x20
00000001882153bc: bl        #0x18db39534 ; call _os_unfair_lock_lock
00000001882153c0: mov       x0, x21
00000001882153c4: bl        #0x188546e40 ; call _objc_msgSend$status
00000001882153c8: cbnz      x0, #0x1882153f0
00000001882153cc: ldr       x0, [x21, #0x58]
00000001882153d0: bl        #0x18853fa00 ; call _objc_msgSend$count
00000001882153d4: cbz       x0, #0x1882153f0
00000001882153d8: mov       x0, x21
00000001882153dc: mov       w2, #3
00000001882153e0: bl        #0x188546300 ; call _objc_msgSend$setStatus:
00000001882153e4: fmov      d0, xzr
00000001882153e8: mov       x0, x21
00000001882153ec: bl        #0x1885400a0 ; call _objc_msgSend$didPresentAtTime:
00000001882153f0: mov       x0, x20
00000001882153f4: bl        #0x18db3954c ; call _os_unfair_lock_unlock
00000001882153f8: add       x8, x19, #0x80
00000001882153fc: ldaxr     w9, [x8]
0000000188215400: sub       w9, w9, #1
0000000188215404: stlxr     w10, w9, [x8]
0000000188215408: cbnz      w10, #0x1882153fc
000000018821540c: mov       x0, x19
0000000188215410: ldp       x29, x30, [sp, #0x20]
0000000188215414: ldp       x20, x19, [sp, #0x10]
0000000188215418: ldp       x22, x21, [sp], #0x30
000000018821541c: b         #0x1882b1fb4
0000000188215420: adrp      x0, #0x18850d000
0000000188215424: add       x0, x0, #0xdf6
0000000188215428: adrp      x1, #0x18850d000
000000018821542c: add       x1, x1, #0xe23
0000000188215430: adrp      x3, #0x18850d000
0000000188215434: add       x3, x3, #0xe33
0000000188215438: mov       w2, #0x87e
000000018821543c: bl        #0x18db389d0 ; call ___assert_rtn | x1 literal: CAMetalLayer.mm
0000000188215440: mov       x19, x0
0000000188215444: mov       x0, x20
0000000188215448: bl        #0x18db3954c ; call _os_unfair_lock_unlock
000000018821544c: mov       x0, x19
0000000188215450: bl        #0x18db388e0 ; call __Unwind_Resume
