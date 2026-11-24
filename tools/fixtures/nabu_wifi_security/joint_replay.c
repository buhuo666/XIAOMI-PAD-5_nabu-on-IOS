/* Real set_join -> captured station boundary -> real protection -> real
 * request_elements. Request RSN and AP beacon RSN are distinct inputs. */
static struct apple80211_assoc association(bool mixed, uint8_t caps, bool sae)
{
    struct apple80211_assoc a = {0};
    const uint8_t head[] = {48, 0, 1, 0, 0, 15, 172, 4, 1, 0, 0, 15, 172, 4};
    a.version = a.key_version = 1;
    a.mode = 2; a.auth_lower = 1; a.auth_upper = sae ? 4096 : 8;
    a.ssid_length = 1; a.ssid[0] = 0xa1;
    a.key_cipher = CIPHER_PASSPHRASE; a.key_length = 8;
    memset(a.key, 0xc3, a.key_length);
    memcpy(a.rsn, head, sizeof(head));
    unsigned at = sizeof(head);
    a.rsn[at++] = mixed ? 2 : 1; a.rsn[at++] = 0;
    if (mixed || !sae) { memcpy(a.rsn + at, "\x00\x0f\xac\x02", 4); at += 4; }
    if (sae || mixed) { memcpy(a.rsn + at, "\x00\x0f\xac\x08", 4); at += 4; }
    a.rsn[at++] = caps; a.rsn[at++] = 0;
    a.rsn[1] = (uint8_t)(at - 2); a.rsn_length = (uint16_t)at;
    return a;
}

static void joint(struct apple80211_assoc *a, bool ap_mixed, uint8_t ap_caps,
                  bool h2e, bool control_ok, bool backend_ok, bool expect_sae)
{
    for (unsigned i=0; i<2; i++) assert(!allocations[i].address);
    memset(allocations,0,sizeof(allocations));
    memset(&captured, 0, sizeof(captured));
    alloc_calls = alloc_fail = free_calls = wipe_calls = copy_calls = native_calls = lock_calls = 0;
    copy_error = native_error = 0; copied_bytes = 0; locked = false; join_result = 21;
    struct apple80211req request = {.req_type=20, .req_len=sizeof(*a), .req_data=(user_addr_t)a};
    char said[256] = {0};
    int result = set_join(&request, said, sizeof(said));
    assert((result == 0) == control_ok);
    assert(native_calls == (unsigned)control_ok && !locked);
    assert(free_calls == 2 && wipe_calls == 2);
    for (unsigned i=0; i<2; i++) assert(!allocations[i].address);
    checks++;
    if (!control_ok) return;
    assert(captured.security == (expect_sae ? HAKIOS_STA_WPA3_SAE : HAKIOS_STA_WPA2_PSK));
    struct apple80211_assoc ap = association(ap_mixed, ap_caps, expect_sae);
    struct lx_radio radio = {0};
    radio.target.capability = 0x10;
    radio.target.elements_length = ap.rsn_length;
    memcpy(radio.target.elements, ap.rsn, ap.rsn_length);
    if (h2e) {
        memcpy(radio.target.elements + radio.target.elements_length, "\xf4\x01\x20", 3);
        radio.target.elements_length += 3;
    }
    unsigned cipher = 0;
    const char *error = protection(&radio.target, &cipher, &radio.sae, &radio.h2e,
                                  captured.security == HAKIOS_STA_WPA3_SAE);
    assert((error == NULL) == backend_ok);
    checks++;
    if (!backend_ok) { assert(!radio.sae && !radio.h2e); return; }
    assert(cipher == 4 && radio.sae == expect_sae && radio.h2e == (h2e && expect_sae));
    struct linuxkpi_ieee80211_channel channel = {.band=0, .center_freq=2412, .max_power=20};
    struct ieee80211_supported_band band = {.n_bitrates=1};
    band.bitrates[0].bitrate = 10;
    typeof(*radio.channel) channel_config = {.def.chan=&channel};
    typeof(*radio.wiphy) wiphy = {.bands={&band,NULL}};
    typeof(*radio.vif) vif = {.bss_conf.basic_rates=1};
    radio.channel=&channel_config; radio.wiphy=&wiphy; radio.vif=&vif;
    radio.width=20; radio.want_length=captured.ssid_length;
    memcpy(radio.want,captured.ssid,captured.ssid_length);
    memset(radio.pmkid,0xd4,sizeof(radio.pmkid));
    uint8_t frame[512] = {0};
    unsigned length = request_elements(&radio,frame,cipher);
    assert(length <= sizeof(frame));
    const uint8_t *rsn = element(frame,length,48);
    assert(rsn && rsn[19] == (expect_sae ? 8 : 2));
    assert(rsn[20] == (expect_sae ? 0xc0 : 0));
    assert(radio.wpa.rsn_length == radio.rsn_length);
    if (expect_sae) {
        assert(rsn[1] == 42 && rsn[22] == 1 && rsn[23] == 0);
        assert(!memcmp(rsn+40,"\x00\x0f\xac\x06",4));
    }
    checks++;
    memset(&captured,0,sizeof(captured));
}

int main(int argc, char **argv)
{
    assert(argc==2 && !strcmp(argv[1],"native-backend-pmf"));
    struct apple80211_assoc a;
    /* Exhaust AP/request capability combinations without equating the inputs. */
    for (unsigned request_caps=0; request_caps<256; request_caps++) {
        a=association(true,(uint8_t)request_caps,true);
        joint(&a,true,0x80,false,(request_caps&0x80)!=0,true,true);
    }
    a=association(false,0x80,true);
    joint(&a,true,0x80,false,true,true,true); /* Selected-only request, mixed beacon. */
    joint(&a,true,0x80,true,true,true,true);
    joint(&a,false,0xc0,true,true,true,true); /* Pure WPA3 remains PMF-required. */
    joint(&a,true,0,false,true,false,true); /* Backend cannot lose PMF. */
    a=association(true,0x80,false);
    joint(&a,true,0x80,true,true,true,false); /* AP H2E does not override selected PSK. */
    a=association(true,0xc0,false);
    joint(&a,true,0xc0,false,false,false,false);
    a=association(true,0x80,true); a.rsn[23]=2;
    joint(&a,true,0x80,false,false,false,true); /* Invalid/duplicate AKM is refused. */
    printf("PASS case=%s checks=%u\n",argv[1],checks);
    return 0;
}
