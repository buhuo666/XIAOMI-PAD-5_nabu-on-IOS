/* Identity checks for the original CoreBrightness -> real Nabu ALS boundary.
 * No IOKit objects or manufactured registry entries are defined here. */
#ifndef NABU_SENSOR_BRIGHTNESS_IDENTITY_H
#define NABU_SENSOR_BRIGHTNESS_IDENTITY_H
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

enum { NabuALSAssociationABI = 1, NabuALSPhysicalKind = 3 };

struct nabu_als_claim {
    uint64_t virtual_id, source_id, suid[2];
    uint32_t generation, association_abi;
    bool built_in, als_usage;
};

struct nabu_als_source_identity {
    uint64_t registry_id, suid[2];
    uint32_t generation, source_abi, kind;
    bool class_matches, active, built_in, lux_units;
};

static inline bool nabu_als_identity_matches(const struct nabu_als_claim *claim,
    const struct nabu_als_source_identity *source)
{
    return claim && source && claim->virtual_id && claim->source_id &&
        claim->association_abi == NabuALSAssociationABI && claim->generation &&
        (claim->suid[0] | claim->suid[1]) && claim->built_in && claim->als_usage &&
        source->class_matches && source->source_abi == 1 &&
        source->kind == NabuALSPhysicalKind && source->active && source->built_in &&
        source->lux_units && source->registry_id == claim->source_id &&
        source->generation == claim->generation &&
        !memcmp(source->suid, claim->suid, sizeof(claim->suid));
}

/* The expected caller is the verified 20F66 IDMatching call site inside the
 * synchronous original addHIDServiceClient: invocation. Other lookups pass. */
static inline uint64_t nabu_als_matching_target(const struct nabu_als_claim *claim,
    const struct nabu_als_source_identity *source, uintptr_t expected_caller,
    uint64_t requested_id, uintptr_t caller)
{
    return expected_caller && caller == expected_caller && claim &&
        requested_id == claim->virtual_id && nabu_als_identity_matches(claim, source)
        ? claim->source_id : requested_id;
}
#endif
