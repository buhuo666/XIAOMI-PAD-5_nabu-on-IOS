00000001882dc0e0: stp       x22, x21, [sp, #-0x30]!
00000001882dc0e4: stp       x20, x19, [sp, #0x10]
00000001882dc0e8: stp       x29, x30, [sp, #0x20]
00000001882dc0ec: add       x29, sp, #0x20
00000001882dc0f0: mov       x19, x0
00000001882dc0f4: add       x20, x0, #0x20
00000001882dc0f8: mov       x0, x20
00000001882dc0fc: bl        #0x1884c9ec0 ; call _pthread_mutex_lock
00000001882dc100: add       x21, x19, #0x60
00000001882dc104: mov       x0, x21
00000001882dc108: bl        #0x18db39534 ; call _os_unfair_lock_lock
00000001882dc10c: ldrb      w8, [x19, #0x64]
00000001882dc110: cbz       w8, #0x1882dc130
00000001882dc114: mov       x0, x21
00000001882dc118: bl        #0x18db3954c ; call _os_unfair_lock_unlock
00000001882dc11c: mov       x0, x20
00000001882dc120: ldp       x29, x30, [sp, #0x20]
00000001882dc124: ldp       x20, x19, [sp, #0x10]
00000001882dc128: ldp       x22, x21, [sp], #0x30
00000001882dc12c: b         #0x1884c9ed8
00000001882dc130: mov       w8, #1
00000001882dc134: strb      w8, [x19, #0x64]
00000001882dc138: mov       x0, x21
00000001882dc13c: bl        #0x18db3954c ; call _os_unfair_lock_unlock
00000001882dc140: mov       x0, x20
00000001882dc144: bl        #0x1884c9ed8 ; call _pthread_mutex_unlock
00000001882dc148: ldr       w1, [x19, #0x18]
00000001882dc14c: cbz       w1, #0x1882dc160
00000001882dc150: adrp      x8, #0x1daac1000
00000001882dc154: ldr       x8, [x8, #0x330] ; [0x1daac1330]=0x201e1ad9870
00000001882dc158: ldr       w0, [x8]
00000001882dc15c: bl        #0x18db3900c ; call _mach_port_deallocate
00000001882dc160: ldr       x1, [x19, #8]
00000001882dc164: cbz       x1, #0x1882dc18c
00000001882dc168: ldr       x2, [x19, #0x10]
00000001882dc16c: mov       w0, #0x222
00000001882dc170: movk      w0, #0x31ca, lsl #16
00000001882dc174: mov       x3, #0
00000001882dc178: mov       x4, #0
00000001882dc17c: ldp       x29, x30, [sp, #0x20]
00000001882dc180: ldp       x20, x19, [sp, #0x10]
00000001882dc184: ldp       x22, x21, [sp], #0x30
00000001882dc188: b         #0x18db38f70
00000001882dc18c: ldp       x29, x30, [sp, #0x20]
00000001882dc190: ldp       x20, x19, [sp, #0x10]
00000001882dc194: ldp       x22, x21, [sp], #0x30
00000001882dc198: ret
