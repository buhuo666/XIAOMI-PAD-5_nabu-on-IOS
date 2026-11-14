#ifndef NABU_JAILBREAK_TWEAK_TEST_H
#define NABU_JAILBREAK_TWEAK_TEST_H

struct nabu_tweak_test_state {
    int version;
    int constructor_ran;
    int uid;
    int euid;
    int engine_loaded;
    int hook_called;
    int before;
    int original;
    int after;
    char stage[32];
    char error[256];
};

typedef int (*nabu_tweak_value_fn)(int);
typedef const struct nabu_tweak_test_state *(*nabu_tweak_state_fn)(void);

#endif
