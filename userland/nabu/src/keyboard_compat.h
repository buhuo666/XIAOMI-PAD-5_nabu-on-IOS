#ifndef NABU_KEYBOARD_COMPAT_H
#define NABU_KEYBOARD_COMPAT_H

struct nabu_keyboard_compat_status {
    int installed;
    int covered_by_existing_experience;
    unsigned corrections;
};

/* Explicit callers use the main thread. Background calls merely schedule it. */
int nabu_keyboard_install_now(void);
void nabu_keyboard_compat_status(struct nabu_keyboard_compat_status *status);

#endif
