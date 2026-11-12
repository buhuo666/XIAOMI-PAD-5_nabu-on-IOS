/* Opt-in production scheduler for the original arm64 20F66 QuartzCore. */
#ifndef NABU_CA_CONTEXT_TIMER_H
#define NABU_CA_CONTEXT_TIMER_H

#ifdef __cplusplus
extern "C" {
#endif

/* Call during backboardd startup. The core also requires the exact environment
 * NABU_CA_CONTEXT_TIMER=1 and QuartzCore UUID. Returns 1 when installed, 0 when
 * disabled/unsupported, or a negative installation error. -5 means selected hooks
 * are live but restoring a data-page protection failed; never unload the dylib.
 * Optional NABU_CA_SINGLE_FREE_PAGE=1 adds four restricted can_update hooks.
 * The bundled observer, when enabled, must install first. No runtime toggle
 * or process-lifetime teardown. */
int nabu_ca_context_timer_install(void);
int nabu_ca_context_timer_active(void);
int nabu_ca_single_free_page_active(void);
unsigned nabu_ca_context_timer_slots(void);

#ifdef __cplusplus
}
#endif
#endif
