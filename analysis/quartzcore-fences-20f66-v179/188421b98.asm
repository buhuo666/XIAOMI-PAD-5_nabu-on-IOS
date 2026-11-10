0000000188421b98: sub       sp, sp, #0x60
0000000188421b9c: stp       x22, x21, [sp, #0x30]
0000000188421ba0: stp       x20, x19, [sp, #0x40]
0000000188421ba4: stp       x29, x30, [sp, #0x50]
0000000188421ba8: add       x29, sp, #0x50
0000000188421bac: mov       x19, x1
0000000188421bb0: adrp      x8, #0x1daabe000
0000000188421bb4: ldr       x8, [x8, #0x7f0] ; [0x1daabe7f0]=0x201e1adb490
0000000188421bb8: ldr       x8, [x8]
0000000188421bbc: str       x8, [sp, #0x28]
0000000188421bc0: bl        #0x18db3936c ; call _objc_opt_self
0000000188421bc4: add       w8, w19, #1
0000000188421bc8: cmp       w8, #1
0000000188421bcc: b.ls      #0x188421cfc
0000000188421bd0: str       wzr, [sp, #0x1c]
0000000188421bd4: str       xzr, [sp, #0x10]
0000000188421bd8: add       x1, sp, #0x1c
0000000188421bdc: add       x2, sp, #0x10
0000000188421be0: mov       x0, x19
0000000188421be4: bl        #0x188285cc8 ; call __CASCreateFencePort
0000000188421be8: mov       w8, #0x4001
0000000188421bec: movk      w8, #0xfb29, lsl #16
0000000188421bf0: cmp       w0, w8
0000000188421bf4: b.eq      #0x188421d1c
0000000188421bf8: mov       x20, x0
0000000188421bfc: ldr       w19, [sp, #0x1c]
0000000188421c00: cbnz      w0, #0x188421c10
0000000188421c04: add       w8, w19, #1
0000000188421c08: cmp       w8, #2
0000000188421c0c: b.hs      #0x188421cc0
0000000188421c10: bl        #0x1882e8870 ; call _x_log_hook_p
0000000188421c14: cbz       w0, #0x188421c30
0000000188421c18: str       x20, [sp]
0000000188421c1c: adrp      x1, #0x18850a000
0000000188421c20: add       x1, x1, #0x4dd
0000000188421c24: mov       w0, #2
0000000188421c28: bl        #0x188346ddc ; call _x_log_ | x1 literal: Server failed to create port for fence (%u)
0000000188421c2c: b         #0x188421c78
0000000188421c30: adrp      x8, #0x1e1b9c000
0000000188421c34: ldr       x21, [x8, #0x668] ; [0x1e1b9c668]=0x0
0000000188421c38: mov       x0, x21
0000000188421c3c: mov       w1, #0x10
0000000188421c40: bl        #0x18db39510 ; call _os_log_type_enabled
0000000188421c44: cbz       w0, #0x188421c78
0000000188421c48: mov       w8, #0x100
0000000188421c4c: movk      w8, #0x400, lsl #16
0000000188421c50: stp       w8, w20, [sp, #0x20]
0000000188421c54: adrp      x0, #0x1881fb000
0000000188421c58: add       x0, x0, #0
0000000188421c5c: adrp      x3, #0x18851f000
0000000188421c60: add       x3, x3, #0xd4b
0000000188421c64: add       x4, sp, #0x20
0000000188421c68: mov       x1, x21
0000000188421c6c: mov       w2, #0x10
0000000188421c70: mov       w5, #8
0000000188421c74: bl        #0x18db38a84 ; call __os_log_impl
0000000188421c78: cbz       w19, #0x188421c90
0000000188421c7c: adrp      x8, #0x1daac1000
0000000188421c80: ldr       x8, [x8, #0x330] ; [0x1daac1330]=0x201e1ad9870
0000000188421c84: ldr       w0, [x8]
0000000188421c88: mov       x1, x19
0000000188421c8c: bl        #0x18db3900c ; call _mach_port_deallocate
0000000188421c90: ldr       x8, [sp, #0x28]
0000000188421c94: adrp      x9, #0x1daabe000
0000000188421c98: ldr       x9, [x9, #0x7f0] ; [0x1daabe7f0]=0x201e1adb490
0000000188421c9c: ldr       x9, [x9]
0000000188421ca0: cmp       x9, x8
0000000188421ca4: b.ne      #0x188421d2c
0000000188421ca8: mov       x0, #0
0000000188421cac: ldp       x29, x30, [sp, #0x50]
0000000188421cb0: ldp       x20, x19, [sp, #0x40]
0000000188421cb4: ldp       x22, x21, [sp, #0x30]
0000000188421cb8: add       sp, sp, #0x60
0000000188421cbc: ret
0000000188421cc0: adrp      x8, #0x1dcc1e000
0000000188421cc4: ldr       x0, [x8, #0x3e8] ; [0x1dcc1e3e8]=0x201e1b9aa80
0000000188421cc8: ldr       x2, [sp, #0x10]
0000000188421ccc: ldr       x8, [sp, #0x28]
0000000188421cd0: adrp      x9, #0x1daabe000
0000000188421cd4: ldr       x9, [x9, #0x7f0] ; [0x1daabe7f0]=0x201e1adb490
0000000188421cd8: ldr       x9, [x9]
0000000188421cdc: cmp       x9, x8
0000000188421ce0: b.ne      #0x188421d2c
0000000188421ce4: mov       x1, x19
0000000188421ce8: ldp       x29, x30, [sp, #0x50]
0000000188421cec: ldp       x20, x19, [sp, #0x40]
0000000188421cf0: ldp       x22, x21, [sp, #0x30]
0000000188421cf4: add       sp, sp, #0x60
0000000188421cf8: b         #0x188220d04
0000000188421cfc: adrp      x0, #0x18850a000
0000000188421d00: add       x0, x0, #0x48f
0000000188421d04: adrp      x1, #0x18850a000
0000000188421d08: add       x1, x1, #0x4b5
0000000188421d0c: adrp      x3, #0x18850a000
0000000188421d10: add       x3, x3, #0x4c6
0000000188421d14: mov       w2, #0x30
0000000188421d18: bl        #0x18db389d0 ; call ___assert_rtn | x1 literal: CAFenceHandle.mm
0000000188421d1c: adrp      x0, #0x1884fb000
0000000188421d20: add       x0, x0, #0x15a
0000000188421d24: bl        #0x188346e30 ; call _x_log_crash
0000000188421d28: bl        #0x18db38ab4 ; call _abort
0000000188421d2c: bl        #0x18db38a60 ; call ___stack_chk_fail
