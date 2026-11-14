/* Run outside an .app, as mobile, after the device's display is ready. The
 * UIKit-linked system-service-probe already demonstrated native Nabu geometry
 * in this main/@autoreleasepool context without UIApplicationMain.
 */
#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include "keyboard_layout_audit.h"

int main(int argc,char **argv) {
    if ((argc!=3 && argc!=5) || strcmp(argv[1],"--output") ||
        (argc==5 && strcmp(argv[3],"--keyboard-library"))) {
        fprintf(stderr,"usage: nabu-keyboard-layout-probe --output <json> [--keyboard-library <path>]\n");
        return 64;
    }
    @autoreleasepool {
        if (argc==5) {
            /* The plain audit follows this same screen-before-TextInputUI order.
             * No app bundle, fabricated traits or screen-method replacement.
             */
            (void)UIScreen.mainScreen;
            void *textInput=dlopen("/System/Library/PrivateFrameworks/TextInputUI.framework/TextInputUI",RTLD_NOW);
            if (!textInput) { fprintf(stderr,"TextInputUI load: %s\n",dlerror()); return 69; }
            void *library=dlopen(argv[4],RTLD_NOW|RTLD_GLOBAL);
            if (!library) { fprintf(stderr,"keyboard library load: %s\n",dlerror()); return 69; }
            int (*install)(void)=(int (*)(void))dlsym(library,"nabu_keyboard_install_now");
            if (!install) { fprintf(stderr,"keyboard install symbol: %s\n",dlerror()); return 69; }
            /* A CLI has no application main-queue loop. Invoke the exported
             * main-thread installation explicitly after UIKit classes exist.
             * Keep the library loaded while its method implementation is live.
             */
            int installed=install();
            fprintf(stderr,"NABU KEYBOARD PROBE: explicit library install returned %d\n",installed);
            if (!installed) return 69;
        }
        BOOL written=nabuKeyboardLayoutAudit(@(argv[2]));
        fprintf(stderr,"NABU KEYBOARD PROBE: audit JSON %s: %s\n",written?"written":"failed",argv[2]);
        return written?0:74;
    }
}
