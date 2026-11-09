0000000188317e40: stp       x22, x21, [sp, #-0x30]!
0000000188317e44: stp       x20, x19, [sp, #0x10]
0000000188317e48: stp       x29, x30, [sp, #0x20]
0000000188317e4c: add       x29, sp, #0x20
0000000188317e50: mov       x20, x2
0000000188317e54: adrp      x8, #0x1dcc1e000
0000000188317e58: ldrsw     x8, [x8, #0xbe4]
0000000188317e5c: ldr       x21, [x0, x8]
0000000188317e60: add       x19, x21, #8
0000000188317e64: mov       x0, x19
0000000188317e68: bl        #0x18db39534 ; call _os_unfair_lock_lock
0000000188317e6c: ldr       x8, [x21, #0x40]
0000000188317e70: cmp       x8, x20
0000000188317e74: b.eq      #0x188317e90
0000000188317e78: bl        #0x18db39420 ; call _objc_retain_x20
0000000188317e7c: ldr       x8, [x21, #0x40]
0000000188317e80: bl        #0x18db393fc ; call _objc_release_x8
0000000188317e84: str       x20, [x21, #0x40]
0000000188317e88: mov       x0, x21
0000000188317e8c: bl        #0x1882e58e8 ; call __ZL25layer_private_flush_asyncP20_CAMetalLayerPrivate
0000000188317e90: mov       x0, x19
0000000188317e94: ldp       x29, x30, [sp, #0x20]
0000000188317e98: ldp       x20, x19, [sp, #0x10]
0000000188317e9c: ldp       x22, x21, [sp], #0x30
0000000188317ea0: b         #0x18db3954c
0000000188317ea4: mov       x20, x0
0000000188317ea8: mov       x0, x19
0000000188317eac: bl        #0x18db3954c ; call _os_unfair_lock_unlock
0000000188317eb0: mov       x0, x20
0000000188317eb4: bl        #0x18db388e0 ; call __Unwind_Resume
