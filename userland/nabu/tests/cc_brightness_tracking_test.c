#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
typedef bool BOOL;
typedef const char *SEL;
struct controller {
    bool tracking, animated;
    float touch, system, displayed, notified;
    unsigned begins, ends, updates, reads, disappears, writes;
};
typedef struct controller *id;
static bool cc_tracking(id o) { return o->tracking; }
static void cc_set_tracking(id o, bool active) { o->tracking = active; }
static float cc_touch_value(id o) { return o->touch; }
#define NABU_CC_BRIGHTNESS_HOST_TEST 1
#include "../src/cc_brightness_tracking.h"
static void begin(id o, SEL s, id slider) { (void)s; (void)slider; ++o->begins; }
static void end(id o, SEL s, id slider) {
    (void)s; (void)slider; ++o->ends;
    assert(cc_level(o, "level") == o->touch);
}
static float level(id o, SEL s) { (void)s; ++o->reads; return o->system; }
static void update(id o, SEL s, BOOL animated) {
    (void)s; ++o->updates; o->animated = animated;
    o->displayed = cc_level(o, "level");
    o->notified = cc_level(o, "level");
}
static void disappear(id o, SEL s, BOOL animated) {
    (void)s; (void)animated; ++o->disappears;
}
int main(void) {
    cc_original_begin=begin; cc_original_end=end; cc_original_update=update;
    cc_original_level=level; cc_original_disappear=disappear;
    struct controller a={.system=.25f}, b={.system=.8f};
    cc_update(&a,"update",true);
    assert(a.displayed==.25f && a.animated);
    cc_begin(&a,"begin",NULL);
    const float drag[]={.3f,.4f,.5f,.6f,.7f,.65f,.55f,.45f};
    unsigned reads=a.reads;
    for(unsigned i=0;i<sizeof(drag)/sizeof(drag[0]);++i) {
        a.touch=drag[i]; ++a.writes; // native _setBacklightLevel still executes
        a.system=i%2 ? .2f : .8f; // asynchronous reply alternates stale values
        cc_update(&a,"update",true); // original _sliderValueDidChange:
        assert(a.displayed==drag[i] && a.notified==drag[i] && !a.animated);
        cc_update(&a,"update",true); // queued system brightness notification
        assert(a.displayed==drag[i] && a.reads==reads);
        cc_update(&b,"update",true);
        assert(b.displayed==.8f && b.animated && !b.tracking);
    }
    cc_end(&a,"end",NULL); assert(!a.tracking && a.ends==1 && a.writes==8);
    a.system=.45f;cc_update(&a,"update",true);
    assert(a.displayed==.45f && a.animated && a.reads>reads);
    cc_begin(&a,"begin",NULL);cc_disappear(&a,"hide",true);
    assert(!a.tracking && a.disappears==1);
    a.system=.1f;cc_update(&a,"update",false);assert(a.displayed==.1f && !a.animated);
    puts("PASS actual CC wrappers: stale replies, upward/downward drag, delegate values, release, cancellation, independent controllers");
}
