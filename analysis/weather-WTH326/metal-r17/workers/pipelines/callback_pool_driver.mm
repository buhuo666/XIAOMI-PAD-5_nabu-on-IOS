#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <cstdio>
int main(int argc,char **argv) {
 if(argc!=3)return 64;
 @autoreleasepool {
  void *bundle=dlopen(argv[1],RTLD_LAZY|RTLD_GLOBAL);
  if(!bundle){fprintf(stderr,"dlopen: %s\n",dlerror());return 65;}
  auto run=(int(*)(const char *))dlsym(bundle,"nabu_test_callback_pool");
  if(!run)return 66;
  return run(argv[2]);
 }
}
