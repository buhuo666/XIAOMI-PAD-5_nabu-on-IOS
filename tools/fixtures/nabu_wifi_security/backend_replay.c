static struct lx_target network(bool psk, bool sae, uint8_t capabilities)
{
    struct lx_target target = {.found = true, .capability = 0x10};
    const uint8_t first[] = {48, 0, 1, 0, 0, 15, 172, 4, 1, 0, 0, 15, 172, 4};
    memcpy(target.elements, first, sizeof(first));
    unsigned length = sizeof(first);
    target.elements[length++] = (uint8_t)(psk + sae);
    target.elements[length++] = 0;
    if (psk) { memcpy(target.elements + length, "\x00\x0f\xac\x02", 4); length += 4; }
    if (sae) { memcpy(target.elements + length, "\x00\x0f\xac\x08", 4); length += 4; }
    target.elements[length++] = capabilities;
    target.elements[length++] = 0;
    target.elements[1] = (uint8_t)(length - 2);
    target.elements_length = length;
    return target;
}

static void check(struct lx_target *target, bool want_sae, bool accepted, bool selected_sae, bool selected_h2e)
{
    unsigned group = 0;
    bool sae = true, h2e = true;
    const char *error = protection(target, &group, &sae, &h2e, want_sae);
    assert((error == NULL) == accepted);
    assert(sae == selected_sae && h2e == selected_h2e);
    if (accepted) assert(group == 4);
    checks++;
}

static void mixed_selection(void)
{
    struct lx_target target = network(true, true, 0x80);
    check(&target, false, true, false, false);
#ifdef LX_HAVE_SAE
    check(&target, true, true, true, false);
    /* H2E announced by the AP must not turn a requested PSK association into SAE. */
    memcpy(target.elements + target.elements_length, "\xf4\x01\x20", 3);
    target.elements_length += 3;
    check(&target, false, true, false, false);
    check(&target, true, true, true, true);
#else
    check(&target, true, true, false, false);
#endif
    target = network(true, true, 0);
    check(&target, false, true, false, false);
#ifdef LX_HAVE_SAE
    check(&target, true, false, false, false);
#endif
    target = network(true, false, 0);
    check(&target, false, true, false, false);
    target = network(false, true, 0x80);
    check(&target, false, false, false, false);
#ifdef LX_HAVE_SAE
    check(&target, true, true, true, false);
#else
    check(&target, true, false, false, false);
#endif
    target = network(true, true, 0xc0);
    check(&target, false, false, false, false);
    target = network(true, false, 0x80);
    check(&target, false, true, false, false);
    target = network(true, false, 0x40);
    check(&target, false, false, false, false);
}

static void rsn_boundaries(void)
{
    struct lx_target target = network(true, false, 0);
    for (unsigned length = 0; length < 20; length++) {
        target = network(true, false, 0);
        target.elements_length = length;
        if (length >= 2) target.elements[1] = (uint8_t)(length - 2);
        check(&target, false, false, false, false);
    }
    target = network(true, false, 0); target.elements_length = 20; target.elements[1] = 18;
    check(&target, false, true, false, false);
    target = network(true, false, 0); target.elements[1]++;
    check(&target, false, false, false, false);
    target = network(true, false, 0); target.elements[2] = 2;
    check(&target, false, false, false, false);
    target = network(true, false, 0); target.elements[7] = 2;
    check(&target, false, false, false, false);
    target = network(true, false, 0); target.elements[13] = 2;
    check(&target, false, false, false, false);
    target = network(true, false, 0); target.elements[19] = 1;
    check(&target, false, false, false, false);
    const unsigned counts[] = {8, 14};
    for (unsigned i = 0; i < sizeof(counts) / sizeof(counts[0]); i++) {
        target = network(true, false, 0); target.elements[counts[i]] = 0;
        check(&target, false, false, false, false);
        target = network(true, false, 0); target.elements[counts[i]] = 255;
        target.elements[counts[i] + 1] = 255;
        check(&target, false, false, false, false);
    }
    target = network(true, false, 0); target.elements_length = 0; target.capability = 0;
    check(&target, false, false, false, false);
#ifdef LX_HAVE_SAE
    target = network(false, true, 0x80); target.elements[target.elements_length++] = 0;
    target.elements[1]++;
    check(&target, true, false, false, false);
    target = network(false, true, 0x80); target.elements[target.elements_length++] = 1;
    target.elements[target.elements_length++] = 0; target.elements[1] += 2;
    check(&target, true, false, false, false);
    target = network(false, true, 0x80);
    memcpy(target.elements + target.elements_length, "\x00\x00\x00\x0f\xac\x06", 6);
    target.elements_length += 6; target.elements[1] += 6;
    check(&target, true, true, true, false);
    target.elements[target.elements_length - 1] = 7;
    check(&target, true, false, false, false);
#endif
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    if (!strcmp(argv[1], "mixed-selection")) mixed_selection();
    else if (!strcmp(argv[1], "rsn-boundaries")) rsn_boundaries();
    else return 2;
    printf("PASS case=%s checks=%u\n", argv[1], checks);
    return 0;
}
