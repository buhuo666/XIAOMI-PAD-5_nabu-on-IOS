// SPDX-License-Identifier: BSD-2-Clause-Patent
// Freestanding, position-independent screen report. No UEFI calls or log reads.
#include <stdint.h>

struct report_config {
  uint64_t incoming[8];
  uint64_t video[6];
  uint64_t font[95];
};
_Static_assert(sizeof(struct report_config) == 109 * 8, "report config ABI");
__attribute__((section(".data.config"), used))
volatile struct report_config kernel_report_config = {0};

static void text(const char *s, unsigned row, unsigned column, uint32_t color)
{
  uint64_t stride = kernel_report_config.video[2] / 4;
  uint64_t y = kernel_report_config.video[4] / 4 + row * 56;
  volatile uint32_t *fb = (volatile uint32_t *)kernel_report_config.video[0];
  for (; *s && column + 24 <= kernel_report_config.video[3]; ++s, column += 24) {
    unsigned c = (unsigned char)*s;
    if (c < 32 || c > 126) c = '?';
    uint64_t glyph = kernel_report_config.font[c - 32];
    for (unsigned gy = 0; gy < 12; ++gy) {
      uint64_t bits = gy < 6 ? (glyph >> 32) >> (gy * 5)
                                  : (glyph & 0xffffffffULL) >> ((gy - 6) * 5);
      for (unsigned gx = 0; gx < 5; ++gx) {
        if ((bits >> gx) & 1) {
          for (unsigned dy = 0; dy < 4; ++dy)
            for (unsigned dx = 0; dx < 4; ++dx)
              fb[(y + gy * 4 + dy) * stride + column + gx * 4 + dx] = color;
        }
      }
    }
  }
}

static void number(const char *label, uint64_t value, unsigned row)
{
  char hex[17];
  for (unsigned i = 0; i < 16; ++i) {
    unsigned d = (value >> (60 - i * 4)) & 15;
    hex[i] = d < 10 ? '0' + d : 'A' + d - 10;
  }
  hex[16] = 0;
  text(label, row, 24, 0xffffffff);
  text(hex, row, 12 * 24, 0xffffffff);
}

void kernel_report_main(void)
{
  uint64_t base = kernel_report_config.video[0];
  uint64_t rowbytes = kernel_report_config.video[2];
  uint64_t width = kernel_report_config.video[3];
  uint64_t height = kernel_report_config.video[4];
  if (!base || (base & 3) || width < 800 || width > 4096 || height < 1024 ||
      height > 4096 || rowbytes < width * 4 || rowbytes > 32768 ||
      (rowbytes & 3) || kernel_report_config.video[5] != 32 ||
      base > UINT64_MAX - rowbytes * height) return;
  volatile uint32_t *fb = (volatile uint32_t *)base;
  uint64_t stride = rowbytes / 4;
  // A fourth, magenta band means the kernel invoked this report stub.
  for (uint64_t y = height * 3 / 16; y < height / 4; ++y)
    for (uint64_t x = 0; x < width; ++x) fb[y * stride + x] = 0xffff00ff;
  for (uint64_t y = height / 4; y < height / 4 + 12 * 56; ++y)
    for (uint64_t x = 0; x < width; ++x) fb[y * stride + x] = 0xff000000;
  text("XNU CALLBACK REACHED", 0, 24, 0xff00ff00);
  if (kernel_report_config.incoming[2] == 2)
    text("KERNEL CHECKPOINT - INTENTIONAL STOP", 1, 24, 0xff00ff00);
  else if (kernel_report_config.incoming[2] == 1)
    text("KERNEL EARLY EXCEPTION", 1, 24, 0xffff8000);
  else
    text("KERNEL RETURN", 1, 24, 0xffff8000);
  number("REASON", kernel_report_config.incoming[2], 2);
  number("CODE / ESR", kernel_report_config.incoming[3], 3);
  // Checkpoint calls only define x0-x3; exception calls also define x4-x7.
  int exception = kernel_report_config.incoming[2] == 1;
  number(exception ? "ELR" : "X4", kernel_report_config.incoming[4], 4);
  number(exception ? "FAR" : "X5", kernel_report_config.incoming[5], 5);
  number(exception ? "LR" : "X6", kernel_report_config.incoming[6], 6);
  number(exception ? "SP" : "X7", kernel_report_config.incoming[7], 7);
  number("LOG PA", kernel_report_config.incoming[0], 8);
  number("LOG BYTES", kernel_report_config.incoming[1], 9);
  text("HALTED FOR DIAGNOSIS", 11, 24, 0xffffffff);
  __asm__ volatile ("dsb sy" ::: "memory");
}
