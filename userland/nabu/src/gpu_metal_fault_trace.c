// SPDX-License-Identifier: MIT
// Run179: retain the faulting backboardd registers before its default SIGSEGV exit.
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ucontext.h>
#include <unistd.h>
#include <mach-o/dyld.h>

static int tracing;

static char *text(char *out, const char *value) {
    while (*value) *out++ = *value++;
    return out;
}

static char *hex(char *out, uint64_t value) {
    static const char digits[] = "0123456789abcdef";
    *out++ = '0'; *out++ = 'x';
    for (int shift = 60; shift >= 0; shift -= 4) *out++ = digits[(value >> shift) & 15];
    return out;
}

static char *field(char *out, const char *name, uint64_t value) {
    return hex(text(out, name), value);
}

static void fault(int number, siginfo_t *info, void *raw_context) {
    const ucontext_t *context = (const ucontext_t *)raw_context;
    const mcontext_t machine = context->uc_mcontext;
    // Fixed labels plus at most 29 register fields fit within 2048 bytes.
    // Only direct stores and async-signal-safe write/kill/getpid run here.
    char record[2048], *out = text(record, "NABU_METAL_FAULT process=backboardd");
    out = field(out, " pid=", (uint64_t)getpid());
    out = field(out, " signal=", (uint64_t)number);
    out = field(out, " code=", (uint64_t)info->si_code);
    out = field(out, " address=", (uint64_t)(uintptr_t)info->si_addr);
#if defined(__arm64__)
    out = field(out, " pc=", machine->__ss.__pc);
    out = field(out, " lr=", machine->__ss.__lr);
    out = field(out, " sp=", machine->__ss.__sp);
    out = field(out, " fp=", machine->__ss.__fp);
    out = field(out, " far=", machine->__es.__far);
    out = field(out, " esr=", machine->__es.__esr);
    out = field(out, " cpsr=", machine->__ss.__cpsr);
    for (unsigned i = 0; i < 29; ++i) {
        out = text(out, " x");
        *out++ = (char)('0' + i / 10); *out++ = (char)('0' + i % 10); *out++ = '=';
        out = hex(out, machine->__ss.__x[i]);
    }
#elif defined(__x86_64__)
    // The same handler's macOS host test verifies logging and default termination.
    out = field(out, " pc=", machine->__ss.__rip);
    out = field(out, " sp=", machine->__ss.__rsp);
    out = field(out, " fp=", machine->__ss.__rbp);
#else
#error Unsupported fault context
#endif
    *out++ = '\n';
    (void)write(STDERR_FILENO, record, (size_t)(out - record));
    // SA_RESETHAND already restored SIG_DFL. Re-raise after saving the original
    // context so both a hardware fault and a sent SIGSEGV retain signal death.
    (void)kill(getpid(), number);
}

int nabu_metal_fault_trace_install(const char *process) {
    if (tracing || !process || strcmp(process, "backboardd")) return tracing;
    struct sigaction previous, action = {0};
    if (sigaction(SIGSEGV, NULL, &previous)) return 0;
    // Do not replace an original consumer's own exception handler.
    if (previous.sa_handler != SIG_DFL) {
        fprintf(stderr, "NABU_METAL_FAULT skipped=existing-handler process=backboardd pid=%d\n", getpid());
        return 0;
    }
    action.sa_sigaction = fault;
    action.sa_flags = SA_SIGINFO | SA_RESETHAND;
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGSEGV, &action, NULL)) return 0;
    tracing = 1;
    fprintf(stderr, "NABU_METAL_FAULT armed=SIGSEGV process=backboardd pid=%d\n", getpid());
    return 1;
}

void nabu_metal_fault_trace_images(void) {
    if (!tracing) return;
    for (uint32_t i = 0; i < _dyld_image_count(); ++i) {
        fprintf(stderr, "NABU_METAL_IMAGE pid=%d base=0x%llx slide=0x%llx name=%s\n", getpid(),
                (unsigned long long)(uintptr_t)_dyld_get_image_header(i),
                (unsigned long long)_dyld_get_image_vmaddr_slide(i), _dyld_get_image_name(i));
    }
}
