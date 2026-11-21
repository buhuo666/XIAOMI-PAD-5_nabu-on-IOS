/* The method belongs to the actual dylib basename being tested. */
#include <objc/runtime.h>
typedef struct {double width,height;} Size;
static void (*previous)(id,SEL,Size);
static void retained(id obj,SEL sel,Size value) {
    if(value.width>0 && value.height==0)value.height=-1;
    previous(obj,sel,value);
}
__attribute__((constructor)) static void install(void) {
    Method m=class_getInstanceMethod(objc_lookUpClass("UIKBDerivedKeyboard"),sel_registerName("setKeyboardSize:"));
    previous=(void (*)(id,SEL,Size))method_setImplementation(m,(IMP)retained);
}
