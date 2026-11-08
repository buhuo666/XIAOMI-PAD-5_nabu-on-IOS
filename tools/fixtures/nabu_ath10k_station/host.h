#ifndef NABU_ATH10K_STATION_HOST_H
#define NABU_ATH10K_STATION_HOST_H
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ETH_ALEN 6
#define GFP_KERNEL 0
#define NL80211_IFTYPE_STATION 2
#define SUPPORTS_TX_ENCAP_OFFLOAD 1u
#define SUPPORTS_RX_DECAP_OFFLOAD 2u
#define IEEE80211_OFFLOAD_ENCAP_ENABLED 1u
#define IEEE80211_OFFLOAD_DECAP_ENABLED 2u
#define roundup2(value, alignment) (((value) + (alignment) - 1) & ~((uintptr_t)(alignment) - 1))
#define ieee80211_hw_check(hw, flag) (((hw)->flags & (flag)) != 0)
#define lx_tell(...) printf(__VA_ARGS__)

struct mutex { bool locked; };
struct wiphy { uint8_t perm_addr[ETH_ALEN]; struct mutex mtx; };
struct ieee80211_hw { struct wiphy *wiphy; unsigned vif_data_size, flags; };
struct ieee80211_vif;
struct ieee80211_bss_conf {
    uint8_t addr[ETH_ALEN];
    struct ieee80211_vif *vif;
    const uint8_t *bssid;
};
struct ieee80211_vif {
    int type;
    uint8_t addr[ETH_ALEN];
    struct ieee80211_bss_conf bss_conf;
    struct ieee80211_bss_conf *link_conf[1];
    unsigned offload_flags;
};
struct ieee80211_sta { unsigned marker; };
struct ieee80211_ops {
    int (*start)(struct ieee80211_hw *);
    int (*add_interface)(struct ieee80211_hw *, struct ieee80211_vif *);
    void (*remove_interface)(struct ieee80211_hw *, struct ieee80211_vif *);
    void (*stop)(struct ieee80211_hw *, bool);
};
/* Only fields touched by the extracted functions are needed by the host peers. */
struct lx_radio {
    struct ieee80211_hw hw;
    const struct ieee80211_ops *ops;
    struct ieee80211_vif *vif;
    void *vif_memory;
    bool started;
    struct ieee80211_sta *sta;
};
static struct lx_radio *the_radio;
static const uint8_t no_network[ETH_ALEN];
static void *kzalloc(size_t size, int flags);
static void kfree(void *memory);
static void station_leave(struct lx_radio *radio);
static void lx_station_say(void);
static void station_down(struct lx_radio *radio);

static void mutex_lock(struct mutex *mutex)
{
    assert(!mutex->locked);
    mutex->locked = true;
}
static void mutex_unlock(struct mutex *mutex)
{
    assert(mutex->locked);
    mutex->locked = false;
}
static bool is_zero_ether_addr(const uint8_t *address)
{
    return memcmp(address, no_network, ETH_ALEN) == 0;
}
#endif
