0000000181a20108: sub       sp, sp, #0x70
0000000181a2010c: stp       x24, x23, [sp, #0x30]
0000000181a20110: stp       x22, x21, [sp, #0x40]
0000000181a20114: stp       x20, x19, [sp, #0x50]
0000000181a20118: stp       x29, x30, [sp, #0x60]
0000000181a2011c: add       x29, sp, #0x60
0000000181a20120: mov       x21, x4
0000000181a20124: mov       x19, x3
0000000181a20128: mov       x22, x2
0000000181a2012c: mov       x20, x0
0000000181a20130: cmp       x4, #0x10, lsl #12
0000000181a20134: b.hs      #0x181a201bc
0000000181a20138: adrp      x8, #0x1dcbee000
0000000181a2013c: ldrsw     x8, [x8, #0x244]
0000000181a20140: ldr       x24, [x20, x8]
0000000181a20144: mov       x0, x19
0000000181a20148: bl        #0x181a33650 ; call __MTLConstantDataSize
0000000181a2014c: mov       x23, x0
0000000181a20150: bl        #0x181b281e4 ; call __Znam
0000000181a20154: mov       x20, x0
0000000181a20158: mov       x1, x22
0000000181a2015c: mov       x2, x23
0000000181a20160: bl        #0x181b28724 ; call __platform_memmove
0000000181a20164: strh      w21, [sp, #0x1e]
0000000181a20168: add       x0, x24, #0x18
0000000181a2016c: add       x8, sp, #0x1e
0000000181a20170: str       x8, [sp, #0x28]
0000000181a20174: adrp      x2, #0x181b48000
0000000181a20178: add       x2, x2, #0x9a0
0000000181a2017c: add       x1, sp, #0x1e
0000000181a20180: add       x3, sp, #0x28
0000000181a20184: add       x4, sp, #0x20
0000000181a20188: bl        #0x181a33c78 ; call __ZNSt3__16__treeINS_12__value_typeItN18MTLConstantStorage12ConstantDataEEENS_19__map_value_compareItS4_NS_4lessItEELb1EEENS_9allocatorIS4_EEE25__emplace_unique_key_argsItJRKNS_21piecewise_construct_tENS_5tupleIJOtEEENSG_IJEEEEEENS_4pairINS_15__tree_iteratorIS4_PNS_11__tree_nodeIS4_PvEElEEbEERKT_DpOT0_
0000000181a2018c: mov       x21, x0
0000000181a20190: ldr       x0, [x0, #0x30]
0000000181a20194: cbz       x0, #0x181a2019c
0000000181a20198: bl        #0x181b281cc ; call __ZdaPv
0000000181a2019c: str       x20, [x21, #0x30]
0000000181a201a0: strb      w19, [x21, #0x28]
0000000181a201a4: ldp       x29, x30, [sp, #0x60]
0000000181a201a8: ldp       x20, x19, [sp, #0x50]
0000000181a201ac: ldp       x22, x21, [sp, #0x40]
0000000181a201b0: ldp       x24, x23, [sp, #0x30]
0000000181a201b4: add       sp, sp, #0x70
0000000181a201b8: ret
0000000181a201bc: mov       w8, #0x10000
0000000181a201c0: stp       x21, x8, [sp]
0000000181a201c4: adrp      x1, #0x181b5c000
0000000181a201c8: add       x1, x1, #0xfd9
0000000181a201cc: adrp      x3, #0x1d5687000
0000000181a201d0: add       x3, x3, #0x30
0000000181a201d4: mov       x0, #0
0000000181a201d8: mov       w2, #0x2e0
0000000181a201dc: bl        #0x181b07a40 ; call _MTLReportFailure | x1 literal: -[MTLFunctionConstantValuesInternal setConstantValue:type:atIndex:]
0000000181a201e0: b         #0x181a20138
0000000181a201e4: mov       x19, x0
0000000181a201e8: mov       x0, x20
0000000181a201ec: bl        #0x181b281cc ; call __ZdaPv
0000000181a201f0: mov       x0, x19
0000000181a201f4: bl        #0x186cfe048 ; call __Unwind_Resume
