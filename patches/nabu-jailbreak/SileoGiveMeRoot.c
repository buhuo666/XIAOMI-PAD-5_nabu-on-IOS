/*
 * Copyright (c) 2021, the Sileo Project. All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
 *
 * 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
 * 3. All advertising materials mentioning features or use of this software must display the following acknowledgement:
 * This product includes software developed by the Sileo Team.
 * 4. Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission.
 * THIS SOFTWARE IS PROVIDED BY THE SILEO TEAM "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE SILEO TEAM BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 *
 * Source: Sileo/Sileo c9f70158a037dc76b91c450e72af2de0514dd3ee, giveMeRoot/giveMeRoot.c.
 * Nabu change: release app path uses the persistent rootless prefix.
 * Parent process validation and command execution are unchanged.
 */
#import <stdint.h>
#import <stdlib.h>
#import <stdio.h>
#import <unistd.h>
#import <string.h>
#import <sys/syslimits.h>
#import <sys/stat.h>
#import <sysexits.h>
#include <dlfcn.h>

extern int proc_pidpath(int pid, void *buffer, uint32_t buffersize);
#define PROC_PIDPATHINFO_MAXSIZE  (1024)
/* Set platform binary flag */
#define FLAG_PLATFORMIZE (1 << 1)


const char *getBuildtimeAppPath(void) {
    const char *path = NULL;
#ifndef MAC
    
#ifdef PREBOOT
    
#ifdef NIGHTLY
    path = "/var/jb/Applications/Sileo-Nightly.app/Sileo-Preboot";
#elif BETA
    path = "/var/jb/Applications/Sileo-Beta.app/Sileo-Preboot";
#else
    path = "/var/jb/Applications/Sileo.app/Sileo-Preboot";
#endif
    
#else
    
#ifdef NIGHTLY
    path = "/Applications/Sileo-Nightly.app/Sileo";
#elif BETA
    path = "/Applications/Sileo-Beta.app/Sileo";
#else
    path = "/var/jb/Applications/Sileo.app/Sileo";
#endif
    
#endif
    
#endif
    
    return path;
}

void patch_setuid() {
    void* handle = dlopen("/usr/lib/libjailbreak.dylib", RTLD_LAZY);
    if (!handle) return;
    
    // Reset errors
    dlerror();
    
    typedef void (*fix_setuid_prt_t)(pid_t pid);
    fix_setuid_prt_t ptr = (fix_setuid_prt_t)dlsym(handle, "jb_oneshot_fix_setuid_now");
    
    ptr(getpid());
    
    setuid(0);
}

char *copyRuntimeAppPath(void) {
    const char *buildtimePath = getBuildtimeAppPath();
    if (buildtimePath == NULL) {
        return NULL;
    }
    return realpath(buildtimePath, NULL);
}

int main(int argc, const char *argv[]) {
    int retval = EX_SOFTWARE;
    
    int err = 0;
    
    char *sileoAppPath = NULL;
    char *parentPath = NULL;
    
#ifndef MAC
    
    sileoAppPath = copyRuntimeAppPath();
    if (sileoAppPath == NULL) {
        fprintf(stderr, "Error: failed to retrieve Sileo app path");
        retval = EX_OSFILE;
        goto end;
    }
    
    struct stat sileoAppStat = {};
    err = lstat(sileoAppPath, &sileoAppStat);
    if (err == -1) {
        fprintf(stderr, "Error: failed to stat Sileo app path");
        retval = EX_OSFILE;
        goto end;
    }
    
    pid_t parentPID = getppid();
    
    size_t parentPathSize = PATH_MAX;
    parentPath = calloc(parentPathSize, sizeof(char));
    if (parentPath == NULL) {
        fprintf(stderr, "Error: failed to malloc");
        retval = EX_OSERR;
        goto end;
    }
    
    int parentPathLength = proc_pidpath(parentPID, parentPath, parentPathSize);
    if (parentPathLength <= 0) {
        fprintf(stderr, "Error: failed to retrieve parent process path");
        retval = EX_OSERR;
        goto end;
    }
    
    if (strcmp(parentPath, sileoAppPath) != 0) {
        fprintf(stderr, "Error: permission denied, parent process is not Sileo");
        retval = EX_NOPERM;
        goto end;
    }
    
#endif
    
    patch_setuid();
    
    setuid(0);
    setgid(0);
    
    if (getuid() != 0) {
        fprintf(stderr, "Error: failed to obtain root");
        retval = EX_OSERR;
        goto end;
    }
    
    retval = 0;
    
end:
    if (sileoAppPath != NULL) {
        free(sileoAppPath);
    }
    if (parentPath != NULL) {
        free(parentPath);
    }
    
    if (retval == 0) {
        if (argc < 2) {
            return 0;
        }
        
        if (strcmp(argv[1], "whoami") == 0) {
            printf("root\n");
            return 0;
        }
        
        const char **remainingArgs = (const char **)((uintptr_t)argv + (1 * sizeof(char *)));
        execv(remainingArgs[0], (char **)remainingArgs);
        
        fprintf(stderr, "Error: failed to execv specified task");
        return EX_OSERR;
    }
    else {
        return retval;
    }
}
