0000000181a3df8c: stp       x22, x21, [sp, #-0x30]!
0000000181a3df90: stp       x20, x19, [sp, #0x10]
0000000181a3df94: stp       x29, x30, [sp, #0x20]
0000000181a3df98: add       x29, sp, #0x20
0000000181a3df9c: mov       x19, x5
0000000181a3dfa0: mov       x20, x3
0000000181a3dfa4: mov       x21, x2
0000000181a3dfa8: mov       x22, x0
0000000181a3dfac: mov       x0, x4
0000000181a3dfb0: bl        #0x181bbd0a0 ; call _objc_msgSend$functionCache
0000000181a3dfb4: mov       x4, x0
0000000181a3dfb8: mov       x0, x22
0000000181a3dfbc: mov       x2, x21
0000000181a3dfc0: mov       x3, x20
0000000181a3dfc4: mov       x5, x19
0000000181a3dfc8: ldp       x29, x30, [sp, #0x20]
0000000181a3dfcc: ldp       x20, x19, [sp, #0x10]
0000000181a3dfd0: ldp       x22, x21, [sp], #0x30
0000000181a3dfd4: b         #0x181bc10a0
