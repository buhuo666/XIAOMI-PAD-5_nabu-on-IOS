// Preserve raw fatal memory fault context for every process using this factory.
#define _DARWIN_C_SOURCE 1
#include <dlfcn.h>
#include <fcntl.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ucontext.h>
#include <sys/time.h>
#include <unistd.h>

static pthread_mutex_t install_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_once_t images_once = PTHREAD_ONCE_INIT;
static unsigned traced_signals;
static char process_name[128];
static int fault_fd = -1;

int nabu_metal_fault_trace_open(const char *directory) {
    pthread_mutex_lock(&install_lock);
    if (fault_fd < 0) {
        struct timeval now;
        gettimeofday(&now, NULL);
        char path[PATH_MAX];
        int length = snprintf(path, sizeof(path), "%s/metal-fault-%d-%lld-%06d.log", directory,
            getpid(), (long long)now.tv_sec, (int)now.tv_usec);
        if (length > 0 && length < (int)sizeof(path)) {
            fault_fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_APPEND | O_CLOEXEC | O_SYNC, 0600);
            if (fault_fd >= 0) dprintf(fault_fd, "NABU_METAL_FAULT_SINK pid=%d path=%s\n", getpid(), path);
        }
    }
    int opened = fault_fd >= 0;
    pthread_mutex_unlock(&install_lock);
    return opened;
}

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
    const ucontext_t *context = raw_context;
    const mcontext_t machine = context->uc_mcontext;
    // Maximum process label plus 40 fixed-width fields fits in this buffer.
    // No Objective-C, unwinder, allocation, image lookup or backend calls here.
    char record[2048], *out = text(record, "NABU_METAL_FAULT process=");
    out = text(out, process_name);
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
    out = field(out, " pc=", machine->__ss.__rip);
    out = field(out, " sp=", machine->__ss.__rsp);
    out = field(out, " fp=", machine->__ss.__rbp);
#else
#error Unsupported fault context
#endif
    *out++ = '\n';
    if (fault_fd >= 0) (void)write(fault_fd, record, (size_t)(out - record));
    (void)write(STDERR_FILENO, record, (size_t)(out - record));
    // SA_RESETHAND restores SIG_DFL; the same signal still terminates normally.
    (void)kill(getpid(), number);
}

int nabu_metal_fault_trace_install(const char *process) {
    static const int signals[] = {SIGSEGV, SIGBUS};
    static const char *names[] = {"SIGSEGV", "SIGBUS"};
    pthread_mutex_lock(&install_lock);
    if (!process_name[0]) snprintf(process_name, sizeof(process_name), "%s", process ? process : "unknown");
    for (unsigned i = 0; i < 2; ++i) {
        if (traced_signals & (1u << i)) continue;
        struct sigaction previous, action = {0};
        if (sigaction(signals[i], NULL, &previous)) continue;
        if (previous.sa_handler != SIG_DFL) {
            fprintf(stderr, "NABU_METAL_FAULT skipped=existing-handler signal=%s process=%s pid=%d\n",
                    names[i], process_name, getpid());
            if (fault_fd >= 0) dprintf(fault_fd, "NABU_METAL_FAULT skipped=existing-handler signal=%s process=%s pid=%d\n",
                    names[i], process_name, getpid());
            continue;
        }
        action.sa_sigaction = fault;
        action.sa_flags = SA_SIGINFO | SA_RESETHAND;
        sigemptyset(&action.sa_mask);
        if (sigaction(signals[i], &action, NULL)) continue;
        traced_signals |= 1u << i;
        fprintf(stderr, "NABU_METAL_FAULT armed=%s process=%s pid=%d\n", names[i], process_name, getpid());
        if (fault_fd >= 0) dprintf(fault_fd, "NABU_METAL_FAULT armed=%s process=%s pid=%d\n", names[i], process_name, getpid());
    }
    int installed = traced_signals != 0;
    pthread_mutex_unlock(&install_lock);
    return installed;
}

static void image_added(const struct mach_header *header, intptr_t slide) {
    const struct mach_header_64 *image = (const struct mach_header_64 *)header;
    const unsigned char *uuid = NULL;
    const char *cursor = (const char *)(image + 1);
    for (uint32_t i = 0; i < image->ncmds; ++i) {
        const struct load_command *command = (const struct load_command *)cursor;
        if (command->cmd == LC_UUID) uuid = ((const struct uuid_command *)command)->uuid;
        cursor += command->cmdsize;
    }
    char uuid_text[33] = {0};
    if (uuid) for (unsigned i = 0; i < 16; ++i) snprintf(uuid_text + i * 2, 3, "%02x", uuid[i]);
    Dl_info info = {0};
    dladdr(header, &info);
    fprintf(stderr, "NABU_METAL_IMAGE pid=%d base=0x%llx slide=0x%llx uuid=%s name=%s\n", getpid(),
        (unsigned long long)(uintptr_t)header, (unsigned long long)slide,
        uuid ? uuid_text : "absent", info.dli_fname ? info.dli_fname : "unknown");
    if (fault_fd >= 0) dprintf(fault_fd, "NABU_METAL_IMAGE pid=%d base=0x%llx slide=0x%llx uuid=%s name=%s\n", getpid(),
        (unsigned long long)(uintptr_t)header, (unsigned long long)slide,
        uuid ? uuid_text : "absent", info.dli_fname ? info.dli_fname : "unknown");
}
static void register_images(void) {
    // dyld calls this for existing images and subsequent loads, outside fault handling.
    _dyld_register_func_for_add_image(image_added);
}
void nabu_metal_fault_trace_images(void) {
    pthread_mutex_lock(&install_lock);
    int enabled = traced_signals != 0;
    pthread_mutex_unlock(&install_lock);
    if (enabled) pthread_once(&images_once, register_images);
}
