00000001882e58e8: stp       x22, x21, [sp, #-0x30]!
00000001882e58ec: stp       x20, x19, [sp, #0x10]
00000001882e58f0: stp       x29, x30, [sp, #0x20]
00000001882e58f4: add       x29, sp, #0x20
00000001882e58f8: mov       x19, x0
00000001882e58fc: adrp      x20, #0x1dcc23000
00000001882e5900: ldr       x0, [x20, #0xbd8] ; [0x1dcc23bd8]=0x0
00000001882e5904: mov       x1, x19
00000001882e5908: bl        #0x18db39750 ; call _pthread_setspecific
00000001882e590c: ldr       x0, [x19, #0x10]
00000001882e5910: mov       w1, #1
00000001882e5914: mov       w2, #0
00000001882e5918: bl        #0x18826ee4c ; call _CAImageQueueCollect_
00000001882e591c: ldr       x0, [x20, #0xbd8] ; [0x1dcc23bd8]=0x0
00000001882e5920: mov       x1, #0
00000001882e5924: bl        #0x18db39750 ; call _pthread_setspecific
00000001882e5928: ldr       x20, [x19, #0x30]
00000001882e592c: cbz       x20, #0x1882e5960
00000001882e5930: str       xzr, [x19, #0x30]
00000001882e5934: mov       x21, x20
00000001882e5938: ldr       x1, [x21]
00000001882e593c: mov       x0, x19
00000001882e5940: bl        #0x18843375c ; call __ZL16release_drawableP20_CAMetalLayerPrivateP23_CAMetalDrawablePrivate
00000001882e5944: ldr       x21, [x21, #8]
00000001882e5948: cbnz      x21, #0x1882e5938
00000001882e594c: ldr       x21, [x20, #8]
00000001882e5950: mov       x0, x20
00000001882e5954: bl        #0x1884c96e0
00000001882e5958: mov       x20, x21
00000001882e595c: cbnz      x21, #0x1882e594c
00000001882e5960: add       x20, x19, #8
00000001882e5964: mov       x0, x20
00000001882e5968: bl        #0x18db3954c ; call _os_unfair_lock_unlock
00000001882e596c: mov       x0, x19
00000001882e5970: bl        #0x188214650 ; call __ZL31layer_private_cleanup_callbacksP20_CAMetalLayerPrivate
00000001882e5974: mov       x0, x20
00000001882e5978: ldp       x29, x30, [sp, #0x20]
00000001882e597c: ldp       x20, x19, [sp, #0x10]
00000001882e5980: ldp       x22, x21, [sp], #0x30
00000001882e5984: b         #0x18db39534
00000001882e5988: mov       x19, x0
00000001882e598c: mov       x0, x20
00000001882e5990: bl        #0x18db39534 ; call _os_unfair_lock_lock
00000001882e5994: mov       x0, x19
00000001882e5998: bl        #0x18db388e0 ; call __Unwind_Resume
