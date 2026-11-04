// SPDX-License-Identifier: BSD-2-Clause-Patent
// Freestanding screen report. Log reads are limited to the owned RAM window.
#include <stdint.h>

struct report_config {
  uint64_t incoming[8];
  uint64_t video[6];
  uint64_t font[95];
  uint64_t owned_base, owned_bytes;
};
_Static_assert(sizeof(struct report_config) == 111 * 8, "report config ABI");
__attribute__((section(".data.config"), used))
volatile struct report_config kernel_report_config = {0};

static void draw(const char *s, uint64_t y, unsigned column, unsigned scale, uint32_t color)
{
  uint64_t stride = kernel_report_config.video[2] / 4;
  volatile uint32_t *fb = (volatile uint32_t *)kernel_report_config.video[0];
  if (y + 12 * scale > kernel_report_config.video[4]) return;
  for (; *s && column + 6 * scale <= kernel_report_config.video[3]; ++s, column += 6 * scale) {
    unsigned c = (unsigned char)*s;
    if (c < 32 || c > 126) c = '?';
    uint64_t glyph = kernel_report_config.font[c - 32];
    for (unsigned gy = 0; gy < 12; ++gy) {
      uint64_t bits = gy < 6 ? (glyph >> 32) >> (gy * 5)
                                  : (glyph & 0xffffffffULL) >> ((gy - 6) * 5);
      for (unsigned gx = 0; gx < 5; ++gx) {
        if ((bits >> gx) & 1) {
          for (unsigned dy = 0; dy < scale; ++dy)
            for (unsigned dx = 0; dx < scale; ++dx)
              fb[(y + gy * scale + dy) * stride + column + gx * scale + dx] = color;
        }
      }
    }
  }
}

static void text(const char *s, unsigned row, unsigned column, uint32_t color)
{
  draw(s, kernel_report_config.video[4] / 4 + row * 56, column, 4, color);
}

// Search only the validated log, including markers displaced by an appended
// message buffer. A missing marker is not proof that an event did not happen.
static uint64_t find_marker(const volatile unsigned char *log, uint64_t length,
                            const char *marker)
{
  for (uint64_t i = 0; i < length; ++i) {
    uint64_t j = 0;
    while (marker[j] && j < length - i && log[i + j] == (unsigned char)marker[j]) ++j;
    if (!marker[j]) return i;
  }
  return length;
}

struct selected_lines { uint64_t at[3]; unsigned count; };

static void select_line(struct selected_lines *lines, uint64_t at)
{
  if (lines->count < 3) lines->at[lines->count] = at;
  else { lines->at[1] = lines->at[2]; lines->at[2] = at; }
  ++lines->count;
}

static unsigned draw_log_line(const volatile unsigned char *log, uint64_t length,
    uint64_t at, uint64_t y, unsigned rows, unsigned columns)
{
  unsigned used = 0;
  while (used < rows && used < 2 && at < length) {
    char line[129]; unsigned n = 0, ended = 0;
    while (at < length && n < columns) {
      unsigned c = log[at++];
      if (c == '\n') { ended = 1; break; }
      if (c != '\r') line[n++] = c >= 32 && c <= 126 ? c : '?';
    }
    if (!ended && at < length && log[at] != '\n' &&
        (used + 1 == 2 || used + 1 == rows) && n) line[n - 1] = '>';
    line[n] = 0;
    draw(line, y + used * 28, 12, 2, 0xffffffff);
    ++used;
    if (ended) break;
  }
  return used;
}

/* The log tail can be dominated by unrelated repeated messages. Retain each
 * selected service's first and last two lines across the entire validated log.
 * These are log matches, not a process inventory or a readiness claim. */
static void desktop_log(const volatile unsigned char *log, uint64_t length,
    uint64_t y, unsigned rows, unsigned columns)
{
  struct selected_lines groups[5];
  for (unsigned g = 0; g < 5; ++g) groups[g].count = 0;
  struct selected_lines stacks;
  stacks.count = 0;
  const char *labels[5] = {"SPRINGBOARD: FIRST / LAST LOG LINES",
    "BACKBOARDD: FIRST / LAST LOG LINES", "RUNNINGBOARDD: FIRST / LAST LOG LINES",
    "DISPLAY / SURFACES: FIRST / LAST LOG LINES", "DYLD / EXIT: FIRST / LAST LOG LINES"};
  uint64_t status = length, reads = length;
  for (uint64_t start = 0; start < length;) {
    uint64_t end = start;
    while (end < length && log[end] != '\n') ++end;
    uint64_t n = end - start;
#define HAS(s) (find_marker(log + start, n, (s)) < n)
    if (HAS("NABU USERLAND:")) status = start;
    if (HAS("IO reads=")) reads = start;
    if (HAS("nabu_diag ")) { /* Boot arguments can contain service names. */ }
    else if (HAS("ustacks:")) select_line(&stacks, start);
    else {
      if (HAS("SpringBoard")) select_line(&groups[0], start);
      if (HAS("backboardd")) select_line(&groups[1], start);
      if (HAS("runningboardd")) select_line(&groups[2], start);
      if (HAS("MiniIOMobileFramebuffer") || HAS("MiniIOSurface")) select_line(&groups[3], start);
      if (HAS("Library not loaded") || HAS("exit reason") || HAS("dyld:")) select_line(&groups[4], start);
    }
#undef HAS
    start = end < length ? end + 1 : length;
  }
  unsigned used = 0;
  if (status < length) used += draw_log_line(log, length, status, y, rows, columns);
  if (reads < length && used < rows)
    used += draw_log_line(log, length, reads, y + used * 28, rows - used, columns);
  for (unsigned g = 0; g < 5 && used < rows; ++g) {
    const struct selected_lines *selected = &groups[g];
    const char *label = labels[g];
    if (g == 2 && stacks.count) {
      selected = &stacks;
      label = "THREAD STACK SAMPLES: FIRST / LAST LOG LINES";
    }
    draw(label, y + used++ * 28, 12, 2, 0xffffff00);
    unsigned count = selected->count < 3 ? selected->count : 3;
    if (!count && used < rows)
      draw("NO MATCH IN CAPTURED LOG", y + used++ * 28, 12, 2, 0xffffffff);
    for (unsigned i = 0; i < count && used < rows; ++i)
      used += draw_log_line(log, length, selected->at[i], y + used * 28, rows - used, columns);
  }
}

static void log_tail(void)
{
  uint64_t address = kernel_report_config.incoming[0];
  uint64_t length = kernel_report_config.incoming[1];
  uint64_t owned = kernel_report_config.owned_base;
  uint64_t bytes = kernel_report_config.owned_bytes;
  uint64_t summary_y = kernel_report_config.video[4] / 4 + 12 * 56;
  uint64_t y = summary_y + 28;
  unsigned rows = (kernel_report_config.video[4] - y) / 28;
  unsigned columns = (kernel_report_config.video[3] - 24) / 12;
  if (rows > 40) rows = 40;
  if (columns > 128) columns = 128;
  if (length == 0) { text("NO KERNEL LOG BYTES", 11, 24, 0xffffffff); return; }
  if (!owned || !bytes || owned > UINT64_MAX - bytes || address < owned ||
      address - owned >= bytes || length > bytes - (address - owned) ||
      length > 1536 * 1024) {
    text("KERNEL LOG RANGE REJECTED", 11, 24, 0xffff8000); return;
  }
  if (!rows || !columns) return;
  const volatile unsigned char *log = (const volatile unsigned char *)address;
  uint64_t timer = find_marker(log, length, "--- loader_return_after expired ---");
  uint64_t panic = find_marker(log, length, "--- panic buffer ---");
  text(timer < length ? "TIMER MARKER: YES" : "TIMER MARKER: NOT SEEN", 10, 24, 0xffffffff);
  text(panic < length ? "PANIC BUFFER: YES" : "PANIC BUFFER: NOT SEEN", 10, 800, 0xffffffff);
  uint64_t requested = find_marker(log, length, "return_panic: the panic that was asked for, on cpu ");
  if (kernel_report_config.incoming[2] == 0 && panic == length && requested == length &&
      find_marker(log, length, "NABU USERLAND: phase=7") < length) {
    text("DESKTOP LOG SUMMARY - HALTED", 11, 24, 0xffffffff);
    draw("SELECTED LOG EVIDENCE; NO MATCH DOES NOT MEAN NOT RUNNING", summary_y, 12, 2, 0xffffffff);
    desktop_log(log, length, y, rows, columns);
    return;
  }
  text("KERNEL LOG TAIL - HALTED", 11, 24, 0xffffffff);
  if (requested < length) {
    char line[129];
    unsigned n = 0;
    while (requested < length && n < columns && log[requested] != '\n' && log[requested] != '\r') {
      unsigned c = log[requested++];
      line[n++] = c >= 32 && c <= 126 ? c : '?';
    }
    line[n] = 0;
    draw(line, summary_y, 12, 2, 0xffffff00);
  } else {
    draw("REQUESTED PANIC LINE NOT SEEN", summary_y, 12, 2, 0xffffffff);
  }
  uint64_t start = length > 65536 ? length - 65536 : 0;
  uint64_t starts[40], count = 1;
  unsigned col = 0;
  starts[0] = start;
  for (uint64_t i = start; i < length; ++i) {
    unsigned c = log[i];
    if (c == '\r') continue;
    if (c == '\n' || ++col == columns) {
      starts[count++ % 40] = i + 1;
      col = 0;
    }
  }
  unsigned shown = count < rows ? (unsigned)count : rows;
  for (unsigned row = 0; row < shown; ++row) {
    uint64_t at = starts[(count - shown + row) % 40];
    char line[129];
    unsigned n = 0;
    while (at < length && n < columns) {
      unsigned c = log[at++];
      if (c == '\n') break;
      if (c == '\r') continue;
      line[n++] = c >= 32 && c <= 126 ? c : '?';
    }
    line[n] = 0;
    draw(line, y + row * 28, 12, 2, 0xffffffff);
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
  for (uint64_t y = height / 4; y < height; ++y)
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
  log_tail();
  __asm__ volatile ("dsb sy" ::: "memory");
}
