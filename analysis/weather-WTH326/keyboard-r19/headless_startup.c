/* No Foundation/CoreFoundation/UIKit and no application main-queue loop. */
#include <dlfcn.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "keyboard_compat.h"
int main(int argc,char **argv) {
    assert(argc==2);
    unsigned (*count)(void)=dlsym(RTLD_DEFAULT,"nabu_test_keyboard_enqueues");
    void (*status)(struct nabu_keyboard_compat_status *)=dlsym(RTLD_DEFAULT,"nabu_keyboard_compat_status");
    assert(count&&status);unsigned observed=count();
    struct nabu_keyboard_compat_status state={0};status(&state);
    assert(!state.installed&&!state.covered_by_existing_experience&&!state.corrections);
    if(!strcmp(argv[1],"baseline"))assert(observed>0);
    else {assert(!strcmp(argv[1],"candidate"));assert(observed==0);}
    printf("{\"variant\":\"%s\",\"keyboard_enqueues_before_main\":%u,\"passed\":true}\n",argv[1],observed);
    return 0;
}
