static const uint8_t psk_rsn[] = {
    48, 18, 1, 0, 0, 15, 172, 4, 1, 0, 0, 15, 172, 4,
    1, 0, 0, 15, 172, 2
};

static void reset_peers(void)
{
    for (unsigned i = 0; i < 2; i++) assert(!allocations[i].address);
    memset(allocations, 0, sizeof(allocations));
    memset(&captured, 0, sizeof(captured));
    alloc_calls = alloc_fail = free_calls = wipe_calls = copy_calls = 0;
    native_calls = lock_calls = 0;
    copy_error = native_error = 0;
    copied_bytes = 0;
    locked = false;
    join_result = 21;
}

static struct apple80211_assoc valid(void)
{
    struct apple80211_assoc request = {0};
    request.version = request.key_version = 1;
    request.mode = 2;
    request.auth_lower = 1;
    request.auth_upper = 8;
    request.ssid_length = 32;
    request.key_cipher = CIPHER_PMK;
    request.key_length = 32;
    /* Byte patterns are synthetic and are never printed by the fixture. */
    memset(request.ssid, 0xa1, sizeof(request.ssid));
    memset(request.bssid, 0xb2, sizeof(request.bssid));
    memset(request.key, 0xc3, sizeof(request.key));
    memset(request.key_rest, 0xd4, sizeof(request.key_rest));
    memset(request.rest, 0xe5, sizeof(request.rest));
    request.rsn_length = sizeof(psk_rsn);
    memcpy(request.rsn, psk_rsn, sizeof(psk_rsn));
    return request;
}

static void length_set(struct apple80211_assoc *request, unsigned length)
{
    request->rsn_length = (uint16_t)length;
    request->rsn[1] = length >= 2 ? (uint8_t)(length - 2) : 0;
}

static void check_set(struct apple80211_assoc *asked, unsigned size, int expected, bool native)
{
    struct apple80211req request = {.req_type = 20, .req_len = size, .req_data = (user_addr_t)asked};
    char said[256] = {0};
    assert(set_join(&request, said, sizeof(said)) == expected);
    assert(native_calls == (unsigned)native);
    assert(!locked && lock_calls == (unsigned)native);
    assert(join_result == (native ? 0u : 21u));
    if (size < sizeof(*asked)) {
        assert(!alloc_calls && !copy_calls && !free_calls && !wipe_calls);
    } else {
        assert(alloc_calls == 2);
        assert(free_calls == (alloc_fail ? 1u : 2u) && wipe_calls == free_calls);
        assert(copy_calls == (alloc_fail ? 0u : 1u));
        if (copy_calls) assert(copied_bytes == sizeof(*asked));
    }
    for (unsigned i = 0; i < 2; i++) assert(!allocations[i].address);
    /* The actual log may report sizes/kinds, but never any of the synthetic values. */
    for (size_t i = 0; i < strlen(said); i++) assert((unsigned char)said[i] < 128);
    if (native) {
        assert(captured.security == (asked->auth_upper == 4096 ? HAKIOS_STA_WPA3_SAE : HAKIOS_STA_WPA2_PSK));
        assert(captured.ssid_length == asked->ssid_length);
        assert(!memcmp(captured.ssid, asked->ssid, asked->ssid_length));
        assert_zero(captured.ssid + asked->ssid_length, sizeof(captured.ssid) - asked->ssid_length);
        assert(!memcmp(captured.bssid, asked->bssid, sizeof(captured.bssid)));
        if (asked->key_cipher == CIPHER_PMK) {
            assert(!memcmp(captured.pmk, asked->key, sizeof(captured.pmk)));
            assert(!captured.passphrase_length);
            assert_zero(captured.passphrase, sizeof(captured.passphrase));
        } else {
            assert(captured.passphrase_length == asked->key_length);
            assert(!memcmp(captured.passphrase, asked->key, asked->key_length));
            assert_zero(captured.passphrase + asked->key_length, sizeof(captured.passphrase) - asked->key_length);
            assert_zero(captured.pmk, sizeof(captured.pmk));
        }
    }
    memset(&captured, 0, sizeof(captured));
    checks++;
}

static void check(struct apple80211_assoc *asked, int expected)
{
    int actual = join_security(asked);
    if (actual != expected)
        fprintf(stderr, "security mismatch length=%u auth=%u expected=%d actual=%d\n",
                asked->rsn_length, asked->auth_upper, expected, actual);
    assert(actual == expected);
    reset_peers();
    check_set(asked, sizeof(*asked), expected, expected == 0);
}

static void keys_auth(void)
{
    struct apple80211_assoc request = valid();
    check(&request, 0);
    const unsigned lengths[] = {0, 1, 7, 8, 31, 32, 33, 63, 64, 65, UINT32_MAX};
    for (unsigned cipher = 0; cipher < 2; cipher++) {
        for (unsigned i = 0; i < sizeof(lengths) / sizeof(lengths[0]); i++) {
            request = valid();
            request.key_cipher = cipher ? CIPHER_PASSPHRASE : CIPHER_PMK;
            request.key_length = lengths[i];
            bool okay = cipher ? lengths[i] >= 8 && lengths[i] <= 63 : lengths[i] == 32;
            check(&request, okay ? 0 : EINVAL);
        }
    }
    for (unsigned cipher = 0; cipher <= 12; cipher++) {
        if (cipher == CIPHER_PMK || cipher == CIPHER_PASSPHRASE) continue;
        request = valid(); request.key_cipher = cipher; check(&request, EOPNOTSUPP);
    }
    for (unsigned auth = 0; auth <= 128; auth++) {
        if (auth == 8) continue;
        request = valid(); request.auth_upper = (uint16_t)auth; check(&request, EOPNOTSUPP);
    }
    for (unsigned value = 0; value <= 4; value++) {
        request = valid(); request.mode = (uint16_t)value;
        check(&request, value == 2 ? 0 : EOPNOTSUPP);
        request = valid(); request.auth_lower = (uint16_t)value;
        check(&request, value == 1 ? 0 : EOPNOTSUPP);
    }
    for (unsigned value = 0; value <= 2; value++) {
        request = valid(); request.version = value; check(&request, value == 1 ? 0 : EINVAL);
        request = valid(); request.key_version = value; check(&request, value == 1 ? 0 : EINVAL);
    }
    for (unsigned bit = 0; bit < 16; bit++) {
        request = valid(); request.key_flags = (uint16_t)(1u << bit); check(&request, EOPNOTSUPP);
        request = valid(); request.key_index = (uint16_t)(1u << bit); check(&request, EOPNOTSUPP);
    }
}

static void selected_rsn(void)
{
    struct apple80211_assoc request;
    for (unsigned length = 0; length <= 260; length++) {
        request = valid(); length_set(&request, length);
        int expected = length == 0 ? EOPNOTSUPP :
            (length < 20 || length == 21 || length == 23 || length > 257) ? EINVAL :
            (length == 20 || length == 22 || length == 24) ? 0 : EOPNOTSUPP;
        check(&request, expected);
    }
    request = valid(); request.rsn_length = UINT16_MAX; check(&request, EINVAL);
    request = valid(); request.rsn[1]++; check(&request, EINVAL);
    request = valid(); request.rsn[0] = 221; check(&request, EOPNOTSUPP);
    request = valid(); request.rsn[2] = 2; check(&request, EINVAL);
    request = valid(); request.rsn[3] = 1; check(&request, EINVAL);
    const unsigned suites[] = {4, 10, 16};
    for (unsigned i = 0; i < sizeof(suites) / sizeof(suites[0]); i++) {
        for (unsigned byte = 0; byte < 4; byte++) {
            request = valid(); request.rsn[suites[i] + byte] ^= 1; check(&request, EOPNOTSUPP);
        }
    }
    const unsigned counts[] = {8, 14};
    for (unsigned i = 0; i < sizeof(counts) / sizeof(counts[0]); i++) {
        request = valid(); request.rsn[counts[i]] = 0; check(&request, EINVAL);
        request = valid(); request.rsn[counts[i]] = 255; request.rsn[counts[i] + 1] = 255; check(&request, EINVAL);
        request = valid(); length_set(&request, 24); request.rsn[counts[i]] = 2; check(&request, EOPNOTSUPP);
    }
    for (unsigned caps = 0; caps < 256; caps++) {
        request = valid(); length_set(&request, 22); request.rsn[20] = (uint8_t)caps;
        check(&request, caps & 0x40 ? EOPNOTSUPP : 0);
    }
    request = valid(); length_set(&request, 23); check(&request, EINVAL);
    request = valid(); length_set(&request, 24); request.rsn[22] = 1; check(&request, EINVAL);
    request = valid(); length_set(&request, 39); request.rsn[22] = 1; check(&request, EINVAL);
    request = valid(); length_set(&request, 40); request.rsn[22] = 1; check(&request, EOPNOTSUPP);
    request = valid(); length_set(&request, 24); request.rsn[23] = 1; check(&request, EINVAL);
    request = valid(); length_set(&request, 28); memcpy(request.rsn + 24, "\x00\x0f\xac\x06", 4);
    check(&request, EOPNOTSUPP);
}

static void copy_cleanup(void)
{
    struct apple80211_assoc request = valid();
    const unsigned lengths[] = {0, 0x88, 0xcc, 0xce, 591};
    for (unsigned i = 0; i < sizeof(lengths) / sizeof(lengths[0]); i++) {
        reset_peers(); check_set(&request, lengths[i], EINVAL, false);
    }
    for (unsigned failure = 1; failure <= 2; failure++) {
        reset_peers(); alloc_fail = failure; check_set(&request, sizeof(request), ENOMEM, false);
    }
    reset_peers(); copy_error = EFAULT; check_set(&request, sizeof(request), EFAULT, false);
    request.ssid_length = 0; reset_peers(); check_set(&request, sizeof(request), EINVAL, false);
    request.ssid_length = 33; reset_peers(); check_set(&request, sizeof(request), EINVAL, false);
    request.ssid_length = 1; reset_peers(); check_set(&request, sizeof(request), 0, true);
    request = valid(); reset_peers(); native_error = EBUSY;
    check_set(&request, sizeof(request), EBUSY, true);
    reset_peers(); native_error = ENXIO; check_set(&request, sizeof(request), ENXIO, true);
    reset_peers(); check_set(&request, sizeof(request) + 64, 0, true);
}

static void sae_selection(void)
{
    struct apple80211_assoc r = valid();
    r.auth_upper = 4096;
    r.rsn[19] = 8;
    length_set(&r, 22); r.rsn[20] = 0xc0;
    check(&r, EOPNOTSUPP); /* a derived PMK cannot authenticate SAE */
    r.key_cipher = CIPHER_PASSPHRASE;
    r.key_length = 1; check(&r, 0);
    r.key_length = 0; check(&r, EINVAL);
    r.key_length = 64; check(&r, EINVAL);
    r.key_length = 63; check(&r, 0);
    /* MFPR describes the AP requirement, while SAE always needs MFPC. */
    for (unsigned caps = 0; caps < 256; caps++) {
        r.rsn[20] = (uint8_t)caps;
        check(&r, caps & 0x80 ? 0 : EOPNOTSUPP);
    }
    r.rsn[20] = 0xc0; r.rsn[19] = 2; check(&r, EOPNOTSUPP);
    r.rsn[19] = 8; r.auth_upper = 8; check(&r, EOPNOTSUPP);
    r.auth_upper = 4096; length_set(&r, 28);
    memcpy(r.rsn + 24, "\x00\x0f\xac\x06", 4); check(&r, 0);
    r.rsn[27] = 11; check(&r, EOPNOTSUPP);
}

static struct apple80211_assoc transition_request(void)
{
    struct apple80211_assoc r = valid();
    static const uint8_t transition[] = {
        48, 30, 1, 0, 0, 15, 172, 4, 1, 0, 0, 15, 172, 4,
        2, 0, 0, 15, 172, 2, 0, 15, 172, 8, 0x80, 0,
        0, 0, 0, 15, 172, 6
    };
    r.key_cipher = CIPHER_PASSPHRASE;
    r.key_length = 8;
    r.auth_upper = 8;
    r.rsn_length = sizeof(transition);
    memcpy(r.rsn, transition, sizeof(transition));
    return r;
}

static void transition_selection(void)
{
    struct apple80211_assoc r = transition_request();
    check(&r, 0); /* WPA2 selection from a WPA2/WPA3 transition AP. */

    r = transition_request();
    r.rsn[24] = 0x40; check(&r, EOPNOTSUPP); /* PMF required is still unsupported. */

    r = transition_request();
    r.rsn[31] = 11; check(&r, EOPNOTSUPP); /* Unknown management cipher remains rejected. */

    r = transition_request();
    r.auth_upper = 4096;
    check(&r, 0); /* SAE on an MFPC=1/MFPR=0 transition AP still requires PMF. */
    r.rsn[24] = 0xc0;
    check(&r, 0); /* Explicit SAE selection also accepts the mixed AKM list. */

    r.rsn[24] = 0; check(&r, EOPNOTSUPP);
    r.rsn[24] = 0x40; check(&r, EOPNOTSUPP); /* MFPR cannot substitute for MFPC. */
    r.rsn[24] = 0x80;

    memcpy(r.rsn + 16, "\x00\x0f\xac\x08\x00\x0f\xac\x02", 8);
    check(&r, 0); /* AKM order cannot turn explicit SAE into PSK. */
    memcpy(r.rsn + 16, "\x00\x0f\xac\x02\x00\x0f\xac\x08", 8);

    r.rsn[23] = 2; check(&r, EOPNOTSUPP); /* SAE cannot fall back to the PSK suite. */

    r = transition_request();
    r.rsn[19] = 8; check(&r, EOPNOTSUPP); /* WPA2 cannot select an SAE-only list. */

    r = transition_request();
    r.rsn[23] = 2; check(&r, EOPNOTSUPP); /* Duplicate AKMs are not a transition list. */
}

static void diagnostic_values(struct apple80211_assoc *r, bool akm_valid,
                              unsigned akms, bool caps_valid, unsigned caps)
{
    unsigned observed_akms = UINT_MAX, observed_caps = UINT_MAX;
    bool observed_akm_valid = true, observed_caps_valid = true;
    join_rsn_diagnostic(r, &observed_akms, &observed_akm_valid, &observed_caps, &observed_caps_valid);
    assert(observed_akm_valid == akm_valid && observed_caps_valid == caps_valid);
    assert(observed_akms == akms && observed_caps == caps);
    checks++;
}

static void diagnostic_said(struct apple80211_assoc *r)
{
    struct apple80211req request = {.req_type=20, .req_len=sizeof(*r), .req_data=(user_addr_t)r};
    char full[200] = {0};
    int expected = join_security(r);
    reset_peers();
    assert(set_join(&request, full, sizeof(full)) == expected);
    assert(full[sizeof(full)-1] == 0);
    assert(strlen(full) < sizeof(full)-1 && full[strlen(full)-1] == ')');
    const char *secrets[] = {"SSID_PRIVATE", "KEY_PRIVATE", "REST_PRIVATE", "PMKID_PRIVATE"};
    for (unsigned i=0; i<sizeof(secrets)/sizeof(secrets[0]); i++) assert(!strstr(full,secrets[i]));
    for (size_t i=0; i<strlen(full); i++) assert((unsigned char)full[i]<128);
    for (unsigned room=0; room<=200; room++) {
        struct { unsigned char before[16]; char said[200]; unsigned char after[16]; } guarded;
        memset(&guarded,0xa5,sizeof(guarded));
        reset_peers();
        assert(set_join(&request, guarded.said, room) == expected);
        for (unsigned i=0; i<16; i++) assert(guarded.before[i]==0xa5 && guarded.after[i]==0xa5);
        if (room) {
            size_t used=strlen(full)<room-1 ? strlen(full) : room-1;
            assert(!memcmp(guarded.said,full,used) && guarded.said[used]==0);
        }
        for (unsigned i=room; i<200; i++) assert((unsigned char)guarded.said[i]==0xa5);
        assert(native_calls==(unsigned)(expected==0) && !locked && free_calls==2 && wipe_calls==2);
        for (unsigned i=0; i<2; i++) assert(!allocations[i].address);
        checks++;
    }
    reset_peers(); native_error=EBUSY;
    int returned=set_join(&request,full,sizeof(full));
    assert(returned==(expected ? expected : EBUSY));
    assert(native_calls==(unsigned)(expected==0) && !locked);
    memset(&captured,0,sizeof(captured));
    checks++;
}

static void request_diagnostic(void)
{
    struct apple80211_assoc r;
    for (unsigned length=0; length<=260; length++) {
        r=valid(); length_set(&r,length);
        bool parsed=length>=16 && length<=257;
        diagnostic_values(&r,parsed,parsed ? 1 : 0,parsed && length>=22,0);
    }
    r=valid(); r.rsn_length=UINT16_MAX;
    diagnostic_values(&r,false,0,false,0);
    r=valid(); length_set(&r,22); r.rsn[0]=221;
    diagnostic_values(&r,false,0,false,0);
    r=valid(); length_set(&r,22); r.rsn[1]++;
    diagnostic_values(&r,false,0,false,0);
    r=valid(); length_set(&r,22); r.rsn[2]=2;
    diagnostic_values(&r,false,0,false,0);
    r=valid(); length_set(&r,22); r.rsn[3]=1;
    diagnostic_values(&r,false,0,false,0);
    for (unsigned index=0; index<2; index++) {
        r=valid(); length_set(&r,22); r.rsn[8]=index ? 255 : 0; r.rsn[9]=index ? 255 : 0;
        diagnostic_values(&r,false,0,false,0);
        r=valid(); length_set(&r,22); r.rsn[14]=index ? 255 : 0; r.rsn[15]=index ? 255 : 0;
        diagnostic_values(&r,true,index ? 65535 : 0,false,0);
    }
    r=transition_request(); diagnostic_values(&r,true,2,true,0x80);
    r.rsn[24]=255; r.rsn[25]=255; diagnostic_values(&r,true,2,true,65535);
    r=transition_request();
    memmove(r.rsn+18,r.rsn+14,r.rsn_length-14);
    memcpy(r.rsn+14,"\x00\x0f\xac\x04",4); r.rsn[8]=2;
    length_set(&r,r.rsn_length+4); diagnostic_values(&r,true,2,true,0x80);
    r=transition_request(); r.auth_upper=4096;
    memcpy(r.ssid,"SSID_PRIVATE",12); memcpy(r.key,"KEY_PRIVATE",11);
    memcpy(r.key_rest,"REST_PRIVATE",12);
    r.rsn[26]=1; memcpy(r.rsn+28,"PMKID_PRIVATE",13);
    memcpy(r.rsn+44,"\x00\x0f\xac\x06",4); length_set(&r,48);
    diagnostic_values(&r,true,2,true,0x80);
    diagnostic_said(&r); /* Rejected PMKID metadata never prints PMKID bytes. */
    r=transition_request(); r.auth_upper=4096; diagnostic_said(&r);
    r=valid(); r.version=r.key_version=r.key_length=r.key_cipher=UINT32_MAX;
    r.mode=r.auth_lower=r.auth_upper=r.key_flags=r.key_index=r.rsn_length=UINT16_MAX;
    diagnostic_said(&r); /* Maximum scalar values also fit the actual 200-byte buffer. */
    r=valid(); length_set(&r,20);
    struct apple80211req request={.req_type=20,.req_len=sizeof(r),.req_data=(user_addr_t)&r};
    char said[200]={0}; reset_peers(); assert(set_join(&request,said,sizeof(said))==0);
    assert(strstr(said,"akms=1 akm_valid=1 caps=0 caps_valid=0 mfpc=0 mfpr=0"));
    r=transition_request(); r.auth_upper=4096; reset_peers();
    assert(set_join(&request,said,sizeof(said))==0);
    assert(strstr(said,"mode=2 auth=0x1/0x1000 kv=1 key=10/8 kf=0 ki=0"));
    assert(strstr(said,"rsn_len=32 akms=2 akm_valid=1 caps=0x80 caps_valid=1 mfpc=1 mfpr=0"));
    printf("SAFE_DIAGNOSTIC%s\n",said);
    memset(&captured,0,sizeof(captured));
    checks+=2;
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    if (!strcmp(argv[1], "abi-layout")) {
        _Static_assert(sizeof(struct apple80211req) == 40, "64-bit Apple80211 ioctl request ABI");
        printf("{\"ioctl_request_bytes\":%zu,\"req_type\":%zu,\"req_value\":%zu,"
               "\"req_length\":%zu,\"req_data\":%zu,\"assoc_bytes\":%zu,"
               "\"version\":%zu,\"mode\":%zu,\"auth_lower\":%zu,\"auth_upper\":%zu,"
               "\"ssid_length\":%zu,\"key_version\":%zu,\"key_length\":%zu,"
               "\"key_cipher\":%zu,\"key_flags\":%zu,\"key_index\":%zu,"
               "\"rsn_length\":%zu,\"rsn\":%zu,\"rsn_capacity\":%zu}\n",
               sizeof(struct apple80211req), offsetof(struct apple80211req,req_type),
               offsetof(struct apple80211req,req_val), offsetof(struct apple80211req,req_len),
               offsetof(struct apple80211req,req_data), sizeof(struct apple80211_assoc),
               offsetof(struct apple80211_assoc,version), offsetof(struct apple80211_assoc,mode),
               offsetof(struct apple80211_assoc,auth_lower), offsetof(struct apple80211_assoc,auth_upper),
               offsetof(struct apple80211_assoc,ssid_length), offsetof(struct apple80211_assoc,key_version),
               offsetof(struct apple80211_assoc,key_length), offsetof(struct apple80211_assoc,key_cipher),
               offsetof(struct apple80211_assoc,key_flags), offsetof(struct apple80211_assoc,key_index),
               offsetof(struct apple80211_assoc,rsn_length), offsetof(struct apple80211_assoc,rsn),
               sizeof(((struct apple80211_assoc *)0)->rsn));
        return 0;
    }
    if (!strcmp(argv[1], "keys-auth")) keys_auth();
    else if (!strcmp(argv[1], "selected-rsn")) selected_rsn();
    else if (!strcmp(argv[1], "copy-cleanup")) copy_cleanup();
    else if (!strcmp(argv[1], "sae-selection")) sae_selection();
    else if (!strcmp(argv[1], "transition-selection")) transition_selection();
    else if (!strcmp(argv[1], "request-diagnostic")) request_diagnostic();
    else return 2;
    printf("PASS case=%s checks=%u\n", argv[1], checks);
    return 0;
}
