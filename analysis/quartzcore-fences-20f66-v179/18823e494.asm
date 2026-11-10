000000018823e494: stp       x20, x19, [sp, #-0x20]!
000000018823e498: stp       x29, x30, [sp, #0x10]
000000018823e49c: add       x29, sp, #0x10
000000018823e4a0: mov       x19, x0
000000018823e4a4: add       x0, x0, #0xa50
000000018823e4a8: bl        #0x18827d044 ; call __ZNSt3__112__hash_tableINS_17__hash_value_typeImyEENS_22__unordered_map_hasherImS2_NS_4hashImEENS_8equal_toImEELb1EEENS_21__unordered_map_equalImS2_S7_S5_Lb1EEENS_9allocatorIS2_EEE4findImEENS_15__hash_iteratorIPNS_11__hash_nodeIS2_PvEEEERKT_
000000018823e4ac: cbz       x0, #0x18823e4c4
000000018823e4b0: add       x8, x19, #0xeb8
000000018823e4b4: ldar      x8, [x8]
000000018823e4b8: ldr       x9, [x0, #0x18]
000000018823e4bc: cmp       x8, x9
000000018823e4c0: cset      w0, hs
000000018823e4c4: ldp       x29, x30, [sp, #0x10]
000000018823e4c8: ldp       x20, x19, [sp], #0x20
000000018823e4cc: ret
