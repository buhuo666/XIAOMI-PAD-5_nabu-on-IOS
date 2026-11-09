0000000181a36f3c: sub       sp, sp, #0x90
0000000181a36f40: stp       x28, x27, [sp, #0x30]
0000000181a36f44: stp       x26, x25, [sp, #0x40]
0000000181a36f48: stp       x24, x23, [sp, #0x50]
0000000181a36f4c: stp       x22, x21, [sp, #0x60]
0000000181a36f50: stp       x20, x19, [sp, #0x70]
0000000181a36f54: stp       x29, x30, [sp, #0x80]
0000000181a36f58: add       x29, sp, #0x80
0000000181a36f5c: mov       x19, x5
0000000181a36f60: mov       x20, x4
0000000181a36f64: mov       x21, x3
0000000181a36f68: mov       x22, x2
0000000181a36f6c: mov       x23, x0
0000000181a36f70: add       x25, x4, x5
0000000181a36f74: cmp       x25, #0x10, lsl #12
0000000181a36f78: b.hi      #0x181a37050
0000000181a36f7c: mov       x0, x21
0000000181a36f80: bl        #0x181a37d58 ; call _MTLDataTypeGetComponentCount
0000000181a36f84: cmp       w0, #3
0000000181a36f88: b.ne      #0x181a36fa0
0000000181a36f8c: mov       x0, x21
0000000181a36f90: bl        #0x181a32394 ; call _MTLDataTypeGetComponentType
0000000181a36f94: bl        #0x181a33650 ; call __MTLConstantDataSize
0000000181a36f98: lsl       x24, x0, #2
0000000181a36f9c: b         #0x181a36fac
0000000181a36fa0: mov       x0, x21
0000000181a36fa4: bl        #0x181a33650 ; call __MTLConstantDataSize
0000000181a36fa8: mov       x24, x0
0000000181a36fac: cmp       x20, x25
0000000181a36fb0: b.hs      #0x181a37030
0000000181a36fb4: adrp      x8, #0x1dcbee000
0000000181a36fb8: ldrsw     x28, [x8, #0x244]
0000000181a36fbc: ldr       x25, [x23, x28]
0000000181a36fc0: mov       x0, x21
0000000181a36fc4: bl        #0x181a33650 ; call __MTLConstantDataSize
0000000181a36fc8: mov       x27, x0
0000000181a36fcc: bl        #0x181b281e4 ; call __Znam
0000000181a36fd0: mov       x26, x0
0000000181a36fd4: mov       x1, x22
0000000181a36fd8: mov       x2, x27
0000000181a36fdc: bl        #0x181b28724 ; call __platform_memmove
0000000181a36fe0: strh      w20, [sp, #0x1e]
0000000181a36fe4: add       x0, x25, #0x18
0000000181a36fe8: add       x8, sp, #0x1e
0000000181a36fec: str       x8, [sp, #0x28]
0000000181a36ff0: add       x1, sp, #0x1e
0000000181a36ff4: add       x3, sp, #0x28
0000000181a36ff8: add       x4, sp, #0x20
0000000181a36ffc: adrp      x2, #0x181b48000
0000000181a37000: add       x2, x2, #0x9a0
0000000181a37004: bl        #0x181a33c78 ; call __ZNSt3__16__treeINS_12__value_typeItN18MTLConstantStorage12ConstantDataEEENS_19__map_value_compareItS4_NS_4lessItEELb1EEENS_9allocatorIS4_EEE25__emplace_unique_key_argsItJRKNS_21piecewise_construct_tENS_5tupleIJOtEEENSG_IJEEEEEENS_4pairINS_15__tree_iteratorIS4_PNS_11__tree_nodeIS4_PvEElEEbEERKT_DpOT0_
0000000181a37008: mov       x27, x0
0000000181a3700c: ldr       x0, [x0, #0x30]
0000000181a37010: cbz       x0, #0x181a37018
0000000181a37014: bl        #0x181b281cc ; call __ZdaPv
0000000181a37018: str       x26, [x27, #0x30]
0000000181a3701c: strb      w21, [x27, #0x28]
0000000181a37020: add       x22, x22, x24
0000000181a37024: add       x20, x20, #1
0000000181a37028: subs      x19, x19, #1
0000000181a3702c: b.ne      #0x181a36fbc
0000000181a37030: ldp       x29, x30, [sp, #0x80]
0000000181a37034: ldp       x20, x19, [sp, #0x70]
0000000181a37038: ldp       x22, x21, [sp, #0x60]
0000000181a3703c: ldp       x24, x23, [sp, #0x50]
0000000181a37040: ldp       x26, x25, [sp, #0x40]
0000000181a37044: ldp       x28, x27, [sp, #0x30]
0000000181a37048: add       sp, sp, #0x90
0000000181a3704c: ret
0000000181a37050: sub       x8, x25, #1
0000000181a37054: mov       w9, #0x10000
0000000181a37058: stp       x8, x9, [sp]
0000000181a3705c: adrp      x1, #0x181b5d000
0000000181a37060: add       x1, x1, #0x4a
0000000181a37064: adrp      x3, #0x1d5687000
0000000181a37068: add       x3, x3, #0x50
0000000181a3706c: mov       x0, #0
0000000181a37070: mov       w2, #0x2e9
0000000181a37074: bl        #0x181b07a40 ; call _MTLReportFailure | x1 literal: -[MTLFunctionConstantValuesInternal setConstantValues:type:withRange:]
0000000181a37078: b         #0x181a36f7c
0000000181a3707c: mov       x19, x0
0000000181a37080: mov       x0, x26
0000000181a37084: bl        #0x181b281cc ; call __ZdaPv
0000000181a37088: mov       x0, x19
0000000181a3708c: bl        #0x186cfe048 ; call __Unwind_Resume
