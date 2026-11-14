#ifndef NABU_CHILD_STATUS_H
#define NABU_CHILD_STATUS_H

#include <errno.h>
#include <sys/wait.h>

/* A helper killed by a signal must never be reported as a successful install. */
static int nabu_wait_child(pid_t child, int *raw_status)
{
    pid_t result;
    do {
        result = waitpid(child, raw_status, 0);
    } while (result == -1 && errno == EINTR);
    if (result == -1) return -errno;
    if (WIFSIGNALED(*raw_status)) return 128 + WTERMSIG(*raw_status);
    return WEXITSTATUS(*raw_status);
}

#endif
