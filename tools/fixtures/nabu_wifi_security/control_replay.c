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
        assert(captured.security == HAKIOS_STA_WPA2_PSK);
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
    assert(join_security(asked) == expected);
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
        check(&request, caps & 0xc0 ? EOPNOTSUPP : 0);
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

int main(int argc, char **argv)
{
    assert(argc == 2);
    if (!strcmp(argv[1], "keys-auth")) keys_auth();
    else if (!strcmp(argv[1], "selected-rsn")) selected_rsn();
    else if (!strcmp(argv[1], "copy-cleanup")) copy_cleanup();
    else return 2;
    printf("PASS case=%s checks=%u\n", argv[1], checks);
    return 0;
}
