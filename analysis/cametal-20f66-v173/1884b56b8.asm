00000001884b56b8: sub       sp, sp, #0x40
00000001884b56bc: stp       x22, x21, [sp, #0x10]
00000001884b56c0: stp       x20, x19, [sp, #0x20]
00000001884b56c4: stp       x29, x30, [sp, #0x30]
00000001884b56c8: add       x29, sp, #0x30
00000001884b56cc: adrp      x8, #0x1daabe000
00000001884b56d0: ldr       x8, [x8, #0x7f0] ; [0x1daabe7f0]=0x201e1adb490
00000001884b56d4: ldr       x8, [x8]
00000001884b56d8: str       x8, [sp, #8]
00000001884b56dc: str       xzr, [sp]
00000001884b56e0: adrp      x8, #0x1daabf000
00000001884b56e4: ldr       x8, [x8, #0x328] ; [0x1daabf328]=0x201e1ad9874
00000001884b56e8: ldr       w0, [x8]
00000001884b56ec: add       x1, sp, #4
00000001884b56f0: bl        #0x18db381b4 ; call _IOMainPort
00000001884b56f4: cbz       w0, #0x1884b5724
00000001884b56f8: ldr       x8, [sp, #8]
00000001884b56fc: adrp      x9, #0x1daabe000
00000001884b5700: ldr       x9, [x9, #0x7f0] ; [0x1daabe7f0]=0x201e1adb490
00000001884b5704: ldr       x9, [x9]
00000001884b5708: cmp       x9, x8
00000001884b570c: b.ne      #0x1884b5798
00000001884b5710: ldp       x29, x30, [sp, #0x30]
00000001884b5714: ldp       x20, x19, [sp, #0x20]
00000001884b5718: ldp       x22, x21, [sp, #0x10]
00000001884b571c: add       sp, sp, #0x40
00000001884b5720: ret
00000001884b5724: mov       w21, #0
00000001884b5728: adrp      x19, #0x188519000
00000001884b572c: add       x19, x19, #0x535
00000001884b5730: ldr       w20, [sp, #4]
00000001884b5734: mov       x0, x19
00000001884b5738: bl        #0x18db384f0 ; call _IOServiceMatching
00000001884b573c: mov       x1, x0
00000001884b5740: mov       x2, sp
00000001884b5744: mov       x0, x20
00000001884b5748: bl        #0x18db384e4 ; call _IOServiceGetMatchingServices
00000001884b574c: cbnz      w0, #0x1884b56f8
00000001884b5750: mov       w20, #0
00000001884b5754: ldr       w0, [sp]
00000001884b5758: bl        #0x18db38160 ; call _IOIteratorNext
00000001884b575c: cbz       w0, #0x1884b576c
00000001884b5760: bl        #0x18db3849c ; call _IOObjectRelease
00000001884b5764: mov       w20, #1
00000001884b5768: b         #0x1884b5754
00000001884b576c: ldr       w0, [sp]
00000001884b5770: bl        #0x18db3849c ; call _IOObjectRelease
00000001884b5774: cmp       w21, #0x12b
00000001884b5778: cset      w8, hi
00000001884b577c: orr       w8, w20, w8
00000001884b5780: tbnz      w8, #0, #0x1884b56f8
00000001884b5784: add       w21, w21, #1
00000001884b5788: mov       w0, #0x86a0
00000001884b578c: movk      w0, #1, lsl #16
00000001884b5790: bl        #0x18db39900 ; call _usleep
00000001884b5794: b         #0x1884b5730
00000001884b5798: bl        #0x18db38a60 ; call ___stack_chk_fail
