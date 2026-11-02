#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "nabu_pauth_compat.h"

/*
 * Work order B host regression.
 *
 * Contract: with the fixed unsigned policy (48-bit user VA, tag byte in
 * 63:56), a data-pointer AUT/PAC/XPACD result keeps the unsigned canonical
 * negative encoding (bits 55:48 sign extension and bit 47).  Everything else
 * is masked with 0xff00ffffffffffff.  Code pointers and other policies keep
 * the legacy mask.  This file must fail against the pre-B core and pass
 * against the B core; test-data-pointer-differential.c compares both.
 */

static int read_calls;
static uint64_t read_value;
static uint64_t read_last_address;

static int
counting_read64(uint64_t address, uint64_t *value, void *context)
{
	(void)context;
	++read_calls;
	read_last_address = address;
	*value = read_value;
	return 1;
}

static struct hakios_pauth_frame
state(void)
{
	struct hakios_pauth_frame frame = {0};
	for (unsigned i = 0; i < 31; ++i)
		frame.x[i] = 0x10000 + i * 0x100;
	frame.pc = 0x1000;
	frame.sp = 0x80000;
	frame.pstate = 0xa0000000;
	return frame;
}

static const struct hakios_pauth_policy data_policy = {
	.user_limit = UINT64_C(1) << 48,
	.data_tag_mask = UINT64_C(0xff00000000000000),
	.read64 = counting_read64,
	.context = 0
};

/* Expected data result per the contract (also the differential oracle). */
static uint64_t
reference_strip_data(uint64_t pointer)
{
	if ((pointer & UINT64_C(0x00ff800000000000)) ==
	    UINT64_C(0x00ff800000000000))
		return pointer;
	return pointer & UINT64_C(0xff00ffffffffffff);
}

static uint64_t
apply(uint32_t opcode, uint64_t value, const struct hakios_pauth_policy *policy)
{
	struct hakios_pauth_frame frame = state(), expected;
	unsigned rd = opcode & 31;
	frame.x[rd] = value;
	expected = frame;
	assert(hakios_pauth_step(opcode, &frame, policy) == HAKIOS_PAUTH_STEPPED);
	assert(frame.pc == expected.pc + 4);
	expected.pc += 4;
	expected.x[rd] = frame.x[rd];
	assert(!memcmp(&frame, &expected, sizeof(frame)));
	return frame.x[rd];
}

/* rd == 31 must not write any register and must not touch frame.x[31]. */
static void
apply_x31(uint32_t opcode, const struct hakios_pauth_policy *policy)
{
	uint32_t rd31 = (opcode & ~31u) | 31u;
	struct hakios_pauth_frame frame = state(), before = frame;
	assert((rd31 & 31) == 31);
	assert(hakios_pauth_step(rd31, &frame, policy) == HAKIOS_PAUTH_STEPPED);
	assert(frame.pc == before.pc + 4);
	frame.pc = before.pc;
	assert(!memcmp(&frame, &before, sizeof(frame)));
}

static void
expect_unhandled(uint32_t opcode, const struct hakios_pauth_policy *policy)
{
	struct hakios_pauth_frame frame = state(), before = frame;
	assert(hakios_pauth_step(opcode, &frame, policy) == HAKIOS_PAUTH_UNHANDLED);
	assert(!memcmp(&frame, &before, sizeof(frame)));
}

int main(void)
{
	const uint32_t data_ops[] = {
		0xdac10830u, 0xdac10c30u, 0xdac11830u, 0xdac11c30u,
		0xdac12bf0u, 0xdac12ff0u, 0xdac13bf0u, 0xdac13ff0u, 0xdac147f0u
	};
	const uint64_t sentinels[] = {
		UINT64_MAX, UINT64_MAX - 1, UINT64_MAX - 4095,
		UINT64_C(0xffff800000000000), UINT64_C(0x00ff800000000000)
	};

	/* 1. Sentinels and canonical negatives survive every data form. */
	for (unsigned i = 0; i < sizeof(data_ops) / sizeof(data_ops[0]); ++i) {
		for (unsigned j = 0; j < sizeof(sentinels) / sizeof(sentinels[0]); ++j)
			assert(apply(data_ops[i], sentinels[j], &data_policy) == sentinels[j]);
		for (unsigned tag = 0; tag < 256; ++tag) {
			uint64_t tagged = ((uint64_t)tag << 56) |
			    UINT64_C(0x0000000123456780);
			assert(apply(data_ops[i], tagged, &data_policy) == tagged);
			uint64_t tagged_negative = ((uint64_t)tag << 56) |
			    UINT64_C(0x00fffffffffffe);
			assert(apply(data_ops[i], tagged_negative, &data_policy) ==
			    tagged_negative);
		}
		for (unsigned low = 0; low < 65536; ++low) {
			uint64_t near_negative = UINT64_C(0xffffffffffff0000) | low;
			assert(apply(data_ops[i], near_negative, &data_policy) ==
			    near_negative);
		}
	}

	/* 2. Non-canonical values keep the plain mask. */
	const struct { uint64_t input, expected; } masked[] = {
		{UINT64_C(0xffff7fffffffffff), UINT64_C(0xff007fffffffffff)},
		{UINT64_C(0xabcd000123456780), UINT64_C(0xab00000123456780)},
		{UINT64_C(0x00ff000123456780), UINT64_C(0x0000000123456780)},
		{UINT64_C(0xff80fffffffffff0), UINT64_C(0xff00fffffffffff0)},
		{UINT64_C(0x1234fffffffffff0), UINT64_C(0x1200fffffffffff0)}
	};
	for (unsigned i = 0; i < sizeof(masked) / sizeof(masked[0]); ++i) {
		assert(apply(0xdac11830u, masked[i].input, &data_policy) ==
		    masked[i].expected);
		assert(reference_strip_data(masked[i].input) == masked[i].expected);
	}

	/* 3. Deterministic sweep against the oracle, not only hand-picked values. */
	{
		uint64_t seed = UINT64_C(0x9e3779b97f4a7c15);
		for (unsigned i = 0; i < 4096; ++i) {
			seed = seed * UINT64_C(6364136223846793005) + 1;
			assert(apply(0xdac11830u, seed, &data_policy) ==
			    reference_strip_data(seed));
			assert(apply(0xdac147f0u, seed, &data_policy) ==
			    reference_strip_data(seed));
		}
	}

	/* 4. Code pointers, and data under other policies, keep the legacy mask. */
	assert(apply(0xdac11030u, UINT64_MAX - 1, &data_policy) ==
	    UINT64_C(0x0000fffffffffffe));
	struct hakios_pauth_policy variant = data_policy;
	variant.data_tag_mask = 0;
	assert(apply(0xdac11830u, UINT64_MAX - 1, &variant) ==
	    UINT64_C(0x0000fffffffffffe));
	variant = data_policy;
	variant.user_limit = UINT64_C(1) << 47;
	assert(apply(0xdac11830u, UINT64_MAX - 1, &variant) ==
	    UINT64_C(0xff007ffffffffffe));
	variant = data_policy;
	variant.user_limit = UINT64_C(1) << 40;
	assert(apply(0xdac11830u, UINT64_MAX - 1, &variant) ==
	    UINT64_C(0xff0000fffffffffe));

	/* 5. rd == 31 writes nothing for every data form. */
	for (unsigned i = 0; i < sizeof(data_ops) / sizeof(data_ops[0]); ++i)
		apply_x31(data_ops[i], &data_policy);

	/* 6. Register forms never call read64; LDRAA calls it once, raw value. */
	read_calls = 0;
	for (unsigned i = 0; i < sizeof(data_ops) / sizeof(data_ops[0]); ++i)
		(void)apply(data_ops[i], UINT64_MAX - 1, &data_policy);
	assert(read_calls == 0);
	{
		/* LDRAA x16, [x17]; decoder displacement is derived from bits. */
		uint32_t opcode = 0xf8600400u | (17u << 5) | 16u;
		struct hakios_pauth_frame frame = state(), before = frame;
		int offset = (int)(((opcode >> 12) & 0x1ffu) |
		    ((opcode >> 13) & 0x200u));
		if (offset & 0x200)
			offset -= 0x400;
		uint64_t expected_address = frame.x[17] + (uint64_t)(int64_t)(offset * 8);
		read_calls = 0;
		read_value = UINT64_MAX - 1; /* loaded values are not authenticated */
		assert(hakios_pauth_step(opcode, &frame, &data_policy) ==
		    HAKIOS_PAUTH_STEPPED);
		assert(read_calls == 1);
		assert(read_last_address == expected_address);
		assert(frame.x[16] == UINT64_MAX - 1);
		assert(frame.pc == before.pc + 4);
		assert(frame.sp == before.sp && frame.pstate == before.pstate);
		for (unsigned i = 0; i < 31; ++i)
			if (i != 16)
				assert(frame.x[i] == before.x[i]);
	}
	{
		/* LDRAA below the user window is BAD_ADDRESS: no read, no writes. */
		uint32_t opcode = 0xf8600400u | (17u << 5) | 16u;
		struct hakios_pauth_frame frame = state(), before = frame;
		frame.x[17] = 0x800;
		before = frame;
		read_calls = 0;
		enum hakios_pauth_status status =
		    hakios_pauth_step(opcode, &frame, &data_policy);
		assert(status == HAKIOS_PAUTH_BAD_ADDRESS);
		assert(read_calls == 0);
		assert(!memcmp(&frame, &before, sizeof(frame)));
	}

	/* 7. Replay the actual reply-unregister self-check and -2 free guard. */
	{
		struct hakios_pauth_frame reply = state();
		reply.x[16] = UINT64_MAX - 1;
		reply.x[21] = 0x12340000;
		reply.x[17] = 0x6ae1000012340000;
		assert(hakios_pauth_step(0xdac11a30u, &reply, &data_policy) ==
		    HAKIOS_PAUTH_STEPPED);
		reply.x[17] = reply.x[16]; /* MOV X17,X16 */
		assert(hakios_pauth_step(0xdac147f1u, &reply, &data_policy) ==
		    HAKIOS_PAUTH_STEPPED);
		assert(reply.x[16] == reply.x[17]); /* CMP X16,X17 */
		reply.x[22] = reply.x[16]; /* MOV X22,X16 */
		assert(reply.x[22] + 2 == 0); /* CMN X22,#2; B.EQ skips free(X21) */
		assert(reply.x[21] == 0x12340000);
	}

	/* 8. Unknown encodings stay unhandled with an untouched frame. */
	const uint32_t rejected[] = {0, 0xd53ef128u, 0xd51ef120u, 0xd69f0bffu,
	    0xd4200020u};
	for (unsigned i = 0; i < sizeof(rejected) / sizeof(rejected[0]); ++i)
		expect_unhandled(rejected[i], &data_policy);

	puts("Data pointer regression: nine data forms, canonical negative and tagged "
	    "values, 65536 near-negative and 4096 swept values, rd=31, read64 "
	    "call-count, BAD_ADDRESS, legacy masks, reply -2 branch, unknown "
	    "encodings passed.");
	return 0;
}
