#define _DARWIN_C_SOURCE 1
#include <assert.h>
#include <dlfcn.h>
#include <dirent.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>

int nabu_metal_fault_trace_install(const char *);
int nabu_metal_fault_trace_open(const char *);
void nabu_metal_fault_trace_images(void);
static void consumer(int signal) { _exit(signal == SIGSEGV ? 42 : 43); }

static void child_case(int which, const char *library, const char *directory) {
    struct rlimit limit = {0, 0};
    assert(setrlimit(RLIMIT_CORE, &limit) == 0);
    assert(nabu_metal_fault_trace_open(directory));
    struct sigaction action = {0}, observed;
    sigemptyset(&action.sa_mask);
    if (which == 2 || which == 3) {
        action.sa_handler = which == 2 ? consumer : SIG_IGN;
        assert(sigaction(SIGSEGV, &action, NULL) == 0);
        assert(sigaction(SIGBUS, &action, NULL) == 0);
        assert(nabu_metal_fault_trace_install("ExistingConsumer") == 0);
        assert(sigaction(SIGSEGV, NULL, &observed) == 0 && observed.sa_handler == action.sa_handler);
        assert(sigaction(SIGBUS, NULL, &observed) == 0 && observed.sa_handler == action.sa_handler);
        raise(SIGSEGV);
        _exit(which == 3 ? 0 : 99);
    }
    assert(nabu_metal_fault_trace_install("ArbitraryMetalClient") == 1);
    assert(nabu_metal_fault_trace_install("ArbitraryMetalClient") == 1);
    if (which == 5 || which == 6) {
        int blocked[2]; assert(pipe(blocked) == 0);
        if (which == 5) close(blocked[0]);
        else {
            int flags = fcntl(blocked[1], F_GETFL); assert(flags >= 0);
            assert(fcntl(blocked[1], F_SETFL, flags | O_NONBLOCK) == 0);
            char bytes[4096] = {0};
            while (write(blocked[1], bytes, sizeof(bytes)) > 0) {}
            assert(fcntl(blocked[1], F_SETFL, flags) == 0);
        }
        assert(dup2(blocked[1], STDERR_FILENO) == STDERR_FILENO);
        close(blocked[1]);
        alarm(5);
    }
    if (which == 4) {
        nabu_metal_fault_trace_images();
        nabu_metal_fault_trace_images();
        void *handle = dlopen(library, RTLD_NOW | RTLD_LOCAL);
        assert(handle);
        int (*value)(void) = (int (*)(void))dlsym(handle, "nabu_fault_test_value");
        assert(value && value() == 15);
        _exit(0);
    }
    if (which == 1) {
        char name[] = "/tmp/nabu-fault-r15-XXXXXX";
        int fd = mkstemp(name);
        assert(fd >= 0);
        unlink(name);
        size_t size = (size_t)getpagesize();
        assert(ftruncate(fd, (off_t)size) == 0);
        volatile char *mapped = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
        assert(mapped != MAP_FAILED);
        assert(ftruncate(fd, 0) == 0);
        *mapped = 1;
    } else {
        volatile unsigned *invalid = (volatile unsigned *)(uintptr_t)1;
        *invalid = 15;
    }
    _exit(99);
}

int main(int argc, char **argv) {
    assert(argc == 2);
    for (int which = 0; which < 7; ++which) {
        char directory[] = "/tmp/nabu-fault-sink-r15-XXXXXX";
        assert(mkdtemp(directory));
        int output[2]; assert(pipe(output) == 0);
        pid_t child = fork(); assert(child >= 0);
        if (!child) {
            close(output[0]); assert(dup2(output[1], STDERR_FILENO) == STDERR_FILENO);
            close(output[1]); child_case(which, argv[1], directory);
        }
        close(output[1]);
        char *record = calloc(1, 2 * 1024 * 1024); assert(record);
        size_t used = 0; ssize_t got;
        while ((got = read(output[0], record + used, 2 * 1024 * 1024 - used - 1)) > 0) used += (size_t)got;
        close(output[0]);
        int status; assert(waitpid(child, &status, 0) == child);
        DIR *dir = opendir(directory); assert(dir);
        struct dirent *entry;
        char *persisted = calloc(1, 2 * 1024 * 1024); assert(persisted);
        int files = 0;
        while ((entry = readdir(dir))) {
            if (strncmp(entry->d_name, "metal-fault-", 12)) continue;
            ++files;
            char path[1024]; snprintf(path, sizeof(path), "%s/%s", directory, entry->d_name);
            FILE *file = fopen(path, "rb"); assert(file);
            size_t bytes = fread(persisted, 1, 2 * 1024 * 1024 - 1, file);
            assert(bytes > 0); fclose(file); unlink(path);
        }
        closedir(dir); rmdir(directory); assert(files == 1);
        assert(strstr(persisted, "NABU_METAL_FAULT_SINK"));
        if (which < 2 || which >= 5) {
            assert(WIFSIGNALED(status) && WTERMSIG(status) == (which == 1 ? SIGBUS : SIGSEGV));
            assert(strstr(persisted, "NABU_METAL_FAULT process=ArbitraryMetalClient"));
            assert(strstr(persisted, " pc=0x") && strstr(persisted, " sp=0x"));
            if (which != 1) assert(strstr(persisted, "address=0x0000000000000001"));
        } else {
            assert(WIFEXITED(status) && WEXITSTATUS(status) == (which == 2 ? 42 : 0));
            assert(!strstr(record, "NABU_METAL_FAULT process="));
            if (which == 4) {
                assert(strstr(persisted, argv[1]) && strstr(persisted, "uuid="));
            } else assert(strstr(persisted, "skipped=existing-handler"));
        }
        printf("PASS fault case %d: original termination/disposition and diagnostic checks\n", which);
        free(record);
        free(persisted);
    }
    return 0;
}
