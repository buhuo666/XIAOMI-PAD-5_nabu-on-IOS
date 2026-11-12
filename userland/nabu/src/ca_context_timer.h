/* Opt-in production scheduler for the original arm64 20F66 QuartzCore. */
#ifndef NABU_CA_CONTEXT_TIMER_H
#define NABU_CA_CONTEXT_TIMER_H

#ifdef __cplusplus
extern "C" {
#endif

/* Call during backboardd startup. The core also requires the exact environment
 * NABU_CA_CONTEXT_TIMER=1 and QuartzCore UUID. Returns 1 when installed, 0 when
 * disabled/unsupported, or a negative installation error. -5 means both hooks
 * are live but restoring a data-page protection failed; never unload the dylib.
 * There is no runtime toggle, observer dependency or process-lifetime teardown. */
int nabu_ca_context_timer_install(void);
int nabu_ca_context_timer_active(void);

#ifdef __cplusplus
}
#endif
#endif
