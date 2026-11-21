#ifndef NABU_KEYBOARD_GEOMETRY_H
#define NABU_KEYBOARD_GEOMETRY_H

/* The 20F66 derived-keyboard caller uses -1 to keep its UIKBTree height.
 * Keep this rule identical to the existing, device-tested experience adapter.
 */
static inline double nabu_keyboard_layout_height(double width,double height,
    double scale,double native_width,double native_height) {
    int nabu=scale==2.0 &&
        ((native_width==1600.0 && native_height==2560.0) ||
         (native_width==2560.0 && native_height==1600.0));
    return nabu && width>0.0 && height==0.0 ? -1.0 : height;
}

#endif
