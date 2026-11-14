#define _DEFAULT_SOURCE 1
#include <assert.h>
#include <signal.h>
#include <stdio.h>
#include <sys/time.h>
#include <unistd.h>
#include "NabuChildStatus.h"

static volatile sig_atomic_t interrupted;
static void handle_alarm(int signal_number) { (void)signal_number; interrupted++; }

static pid_t exit_child(int code)
{
    pid_t child = fork();
    assert(child >= 0);
    if (!child) _exit(code);
    return child;
}

int main(void)
{
    int status = 0;
    assert(nabu_wait_child(exit_child(0), &status) == 0);
    assert(nabu_wait_child(exit_child(175), &status) == 175);
    pid_t child = fork();
    assert(child >= 0);
    if (!child) { raise(SIGKILL); _exit(1); }
    assert(nabu_wait_child(child, &status) == 128 + SIGKILL);
    assert(WIFSIGNALED(status));
    assert(nabu_wait_child(child, &status) == -ECHILD);

    struct sigaction action = {0};
    action.sa_handler = handle_alarm;
    sigemptyset(&action.sa_mask);
    assert(sigaction(SIGALRM, &action, NULL) == 0);
    child = fork();
    assert(child >= 0);
    if (!child) { usleep(80000); _exit(23); }
    struct itimerval timer = {{0, 0}, {0, 10000}};
    assert(setitimer(ITIMER_REAL, &timer, NULL) == 0);
    assert(nabu_wait_child(child, &status) == 23);
    assert(interrupted == 1);
    puts("PASS: success, installer error, signal termination, already-reaped child, interrupted wait");
    return 0;
}
