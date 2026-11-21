/* Runtime/ABI fixture only: no UIKit, real iOS layout or device display. */
#include <objc/runtime.h>
#include <objc/message.h>
#include <assert.h>
typedef struct {double width,height;} Size;
typedef struct {double x,y;} Point;
typedef struct {Point origin;Size size;} Rect;
static Rect bounds={{0,0},{1600,2560}};
static double factor=2;
static unsigned screenQueries,setterCalls;
static Size last;
__attribute__((objc_root_class)) @interface UIScreen
+(id)mainScreen;
-(Rect)nativeBounds;
-(double)scale;
@end
@implementation UIScreen
+(id)mainScreen {static id screen;screenQueries++;if(!screen)screen=class_createInstance(self,0);return screen;}
-(Rect)nativeBounds {return bounds;}
-(double)scale {return factor;}
@end
__attribute__((objc_root_class)) @interface UIKBDerivedKeyboard
-(void)setKeyboardSize:(Size)value;
@end
@implementation UIKBDerivedKeyboard
-(void)setKeyboardSize:(Size)value {last=value;setterCalls++;}
@end
void fixture_geometry(double scale,double width,double height) {factor=scale;bounds.size=(Size){width,height};}
unsigned fixture_screen_queries(void) {return screenQueries;}
unsigned fixture_calls(void) {return setterCalls;}
double fixture_height(void) {return last.height;}
