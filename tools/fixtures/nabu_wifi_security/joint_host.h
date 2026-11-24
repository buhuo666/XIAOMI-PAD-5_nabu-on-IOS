/* Allocation/copyin peers come from control_host.h. These are only the
 * radio/driver fields read by the original request_elements function. */
#include <strings.h>
#define ETH_ALEN 6
#define IEEE80211_HT_CAP_SUP_WIDTH_20_40 0x0002
#define IEEE80211_HT_CAP_SGI_40 0x0040
struct linuxkpi_ieee80211_channel { unsigned band, center_freq, max_power; };
struct ieee80211_supported_band {
    int n_bitrates;
    struct { int bitrate; } bitrates[12];
    struct { bool ht_supported; uint16_t cap; uint8_t ampdu_factor, ampdu_density, mcs[16]; } ht_cap;
    struct { bool vht_supported; uint32_t cap; uint8_t vht_mcs[8]; } vht_cap;
};
struct lx_radio {
    struct lx_target target;
    struct { struct { struct linuxkpi_ieee80211_channel *chan; } def; } *channel;
    struct { struct ieee80211_supported_band *bands[2]; } *wiphy;
    struct { struct { uint32_t basic_rates; } bss_conf; } *vif;
    uint8_t want[32], want_length, rsn[64], pmkid[16];
    unsigned width, rsn_length;
    bool sae, h2e;
    struct { unsigned rsn_length; } wpa;
};
