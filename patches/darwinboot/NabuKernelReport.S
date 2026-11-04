// SPDX-License-Identifier: BSD-2-Clause-Patent
.section .text.entry, "ax"
.global kernel_report_start
.type kernel_report_start, %function
kernel_report_start:
  // The XNU callback arrives at a physical PC with the MMU off. Its stack
  // may still be a kernel VA; do not touch it before installing our own.
  msr daifset, #15
  dsb sy
  mrs x9, sctlr_el1
  bic x9, x9, #1
  bic x9, x9, #4
  bic x9, x9, #0x1000
  msr sctlr_el1, x9
  isb
  adrp x9, kernel_report_config
  add x9, x9, :lo12:kernel_report_config
  stp x0, x1, [x9]
  stp x2, x3, [x9, #16]
  stp x4, x5, [x9, #32]
  stp x6, x7, [x9, #48]
  adrp x9, kernel_report_stack_top
  add x9, x9, :lo12:kernel_report_stack_top
  mov sp, x9
  bl kernel_report_main
.global kernel_report_halt
kernel_report_halt:
  dsb sy
  wfe
  b kernel_report_halt
.size kernel_report_start, .-kernel_report_start
