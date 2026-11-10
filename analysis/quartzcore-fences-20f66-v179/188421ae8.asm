0000000188421ae8: stp       x20, x19, [sp, #-0x20]!
0000000188421aec: stp       x29, x30, [sp, #0x10]
0000000188421af0: add       x29, sp, #0x10
0000000188421af4: cbz       x0, #0x188421b2c
0000000188421af8: mov       x19, x0
0000000188421afc: ldr       x8, [x0, #8]
0000000188421b00: cbz       x8, #0x188421b38
0000000188421b04: mov       x0, x19
0000000188421b08: bl        #0x188220bd4 ; call -[CAFenceHandle _copyUntrackedPort]
0000000188421b0c: mov       x20, x0
0000000188421b10: ldp       x1, x2, [x19, #8]
0000000188421b14: mov       w0, #0x230
0000000188421b18: movk      w0, #0x31ca, lsl #16
0000000188421b1c: mov       x3, #0
0000000188421b20: mov       x4, #0
0000000188421b24: bl        #0x18db38f70 ; call _kdebug_trace
0000000188421b28: mov       x0, x20
0000000188421b2c: ldp       x29, x30, [sp, #0x10]
0000000188421b30: ldp       x20, x19, [sp], #0x20
0000000188421b34: ret
0000000188421b38: adrp      x0, #0x18850a000
0000000188421b3c: add       x0, x0, #0x5b7
0000000188421b40: adrp      x1, #0x18850a000
0000000188421b44: add       x1, x1, #0x4b5
0000000188421b48: adrp      x3, #0x18850a000
0000000188421b4c: add       x3, x3, #0x5d2
0000000188421b50: mov       w2, #0x15a
0000000188421b54: bl        #0x18db389d0 ; call ___assert_rtn | x1 literal: CAFenceHandle.mm
