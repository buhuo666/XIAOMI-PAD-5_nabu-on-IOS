// Capture the first loader_return caller before PSCI can hand it to CPU0.
// The offline patch uses x16 (AAPCS64 IP0) as its only incoming clobber.
// No pointer is probed; the 32-byte temporary frame preserves scratch state.
.section __TEXT,__text,regular,pure_instructions
.p2align 2
.globl _nabu_return_trace_entry
_nabu_return_trace_entry:
    stp x9, x10, [sp, #-32]!
    stp x11, x17, [sp, #16]
    mrs x11, NZCV
    adrp x16, _nabu_return_trace_record@PAGE
    add x16, x16, _nabu_return_trace_record@PAGEOFF
1:
    ldaxr w9, [x16]
    cbnz w9, 3f
    mov w9, #1
    stxr w10, w9, [x16]
    cbnz w10, 1b
    stp x30, x29, [x16, #8]
    add x9, sp, #32
    str x9, [x16, #24]
    mrs x9, MPIDR_EL1
    str x9, [x16, #32]
    mrs x9, ESR_EL1
    str x9, [x16, #40]
    mrs x9, FAR_EL1
    str x9, [x16, #48]
    mrs x9, ELR_EL1
    str x9, [x16, #56]
    mov w9, #2
    stlr w9, [x16]
    b 4f
3:
    clrex
4:
    msr NZCV, x11
    ldp x11, x17, [sp, #16]
    ldp x9, x10, [sp], #32
    // Exact original v104 prologue, also checked against the input image.
    sub sp, sp, #0x160
    stp x26, x25, [sp, #0x110]
    stp x24, x23, [sp, #0x120]
    adrp x16, _loader_return@PAGE
    add x16, x16, _loader_return@PAGEOFF
    add x16, x16, #12
    br x16
.globl _nabu_return_trace_entry_end
_nabu_return_trace_entry_end:

.p2align 2
.globl _nabu_return_trace_terminal
_nabu_return_trace_terminal:
    // Preserve the original storage report, then leave this trace at the tail.
    bl _nabu_storage_append_report
    bl _nabu_return_trace_report
    mov x0, #0
    mov x1, #0
    adrp x16, _loader_return@PAGE
    add x16, x16, _loader_return@PAGEOFF
    // The patch tool verifies the symbol-derived terminal continuation offset.
    add x16, x16, #0x3c0
    br x16
.globl _nabu_return_trace_terminal_end
_nabu_return_trace_terminal_end:
