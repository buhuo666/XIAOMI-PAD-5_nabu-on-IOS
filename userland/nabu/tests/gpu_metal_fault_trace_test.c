// Exercise the real handler on the macOS builder before packaging the iOS object.
#include <assert.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>

int nabu_metal_fault_trace_install(const char *);

int main(void) {
    assert(nabu_metal_fault_trace_install("MetalPresent") == 0);
    struct sigaction action;
    assert(sigaction(SIGSEGV, NULL, &action) == 0 && action.sa_handler == SIG_DFL);
    int output[2];
    assert(pipe(output) == 0);
    pid_t child = fork();
    assert(child >= 0);
    if (child == 0) {
        close(output[0]);
        assert(dup2(output[1], STDERR_FILENO) == STDERR_FILENO);
        close(output[1]);
        struct rlimit limit = {0, 0};
        assert(setrlimit(RLIMIT_CORE, &limit) == 0);
        assert(nabu_metal_fault_trace_install("backboardd") == 1);
        // A real bad memory access must be recorded, then still die of SIGSEGV.
        volatile unsigned *invalid = (volatile unsigned *)(uintptr_t)1;
        *invalid = 178;
        _exit(90);
    }
    close(output[1]);
    char record[4096] = {0};
    size_t used = 0;
    ssize_t count;
    while ((count = read(output[0], record + used, sizeof(record) - used - 1)) > 0) used += (size_t)count;
    close(output[0]);
    int status;
    assert(waitpid(child, &status, 0) == child);
    assert(WIFSIGNALED(status) && WTERMSIG(status) == SIGSEGV);
    assert(strstr(record, "NABU_METAL_FAULT process=backboardd"));
    assert(strstr(record, " address=0x0000000000000001"));
    assert(strstr(record, " pc=0x") && strstr(record, " sp=0x"));
    puts("PASS: scoped fault trace recorded the original memory fault and preserved SIGSEGV termination");
    return 0;
}
