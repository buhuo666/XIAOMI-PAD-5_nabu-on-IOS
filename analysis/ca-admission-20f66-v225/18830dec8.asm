000000018830dec8: stp       x20, x19, [sp, #-0x20]!
000000018830decc: stp       x29, x30, [sp, #0x10]
000000018830ded0: add       x29, sp, #0x10
000000018830ded4: ldr       x19, [x0, #0x20]
000000018830ded8: bl        #0x18db38fac ; call _mach_absolute_time
000000018830dedc: bl        #0x188236490 ; call _CATimeWithHostTime
000000018830dee0: mov       x0, x19
000000018830dee4: mov       x1, #0
000000018830dee8: mov       x2, #0
000000018830deec: mov       x3, #0
000000018830def0: mov       w4, #0
000000018830def4: ldp       x29, x30, [sp, #0x10]
000000018830def8: ldp       x20, x19, [sp], #0x20
000000018830defc: b         #0x18846bf04
