/*
 * Experimental unsigned-pointer execution for a non-PAuth user address space.
 * This implements no signature generation, key storage or authentication.
 * It is not enabled for the iPad donor or for kernel instructions.
 *
 * Encoding reference: LLVM 14.0.6 AArch64InstrFormats.td, SignAuth/Auth*.
 */
#ifndef HAKIOS_PAUTH_COMPAT_H
#define HAKIOS_PAUTH_COMPAT_H

#include <stdint.h>

enum hakios_pauth_status {
	HAKIOS_PAUTH_UNHANDLED = 0,
	HAKIOS_PAUTH_STEPPED = 1,
	HAKIOS_PAUTH_BAD_TARGET = -1,
	HAKIOS_PAUTH_BAD_ADDRESS = -2,
	HAKIOS_PAUTH_READ_FAILED = -3,
};

struct hakios_pauth_frame {
	uint64_t x[31];
	uint64_t sp;
	uint64_t pc;
	uint64_t pstate;
};

struct hakios_pauth_policy {
	uint64_t user_limit; /* exclusive; power of two, at most 48 address bits */
	uint64_t data_tag_mask; /* either zero or 0xff00000000000000 */
	int (*read64)(uint64_t address, uint64_t *value, void *context);
	void *context;
};

static inline uint64_t
hakios_pauth_reg(const struct hakios_pauth_frame *frame, unsigned int reg)
{
	return reg == 31 ? 0 : frame->x[reg];
}

static inline uint64_t
hakios_pauth_strip(uint64_t value, const struct hakios_pauth_policy *policy, int data)
{
	return value & ((policy->user_limit - 1) | (data ? policy->data_tag_mask : 0));
}

static inline int
hakios_pauth_policy_valid(const struct hakios_pauth_policy *policy)
{
	return policy && policy->user_limit >= 0x1000 &&
	    policy->user_limit <= (1ULL << 48) &&
	    (policy->data_tag_mask == 0 || policy->data_tag_mask == 0xff00000000000000ULL) &&
	    !(policy->user_limit & (policy->user_limit - 1));
}

/*
 * The frame is changed only on success. Memory reads are delegated to the
 * caller: a kernel caller must use copyin, never a direct user-pointer load.
 * PSTATE's NZCV bits and every unrelated register are preserved.
 */
static inline enum hakios_pauth_status
hakios_pauth_step(uint32_t instruction, struct hakios_pauth_frame *frame,
    const struct hakios_pauth_policy *policy)
{
	uint32_t base, family;
	unsigned int rd = instruction & 31, rn = (instruction >> 5) & 31;
	uint64_t target, next_pc, value, address;
	int link = 0;

	if (!frame || !hakios_pauth_policy_valid(policy) ||
	    frame->pc >= policy->user_limit || (frame->pc & 3) ||
	    frame->pc > policy->user_limit - 4)
		return HAKIOS_PAUTH_UNHANDLED;
	next_pc = frame->pc + 4;

	/* PAC/AUT hint aliases operate on LR or X17; XPACLRI uses LR. */
	switch (instruction) {
	case 0xd503211f: case 0xd503215f: /* PACIA1716, PACIB1716 */
	case 0xd503219f: case 0xd50321df: /* AUTIA1716, AUTIB1716 */
		frame->x[17] = hakios_pauth_strip(frame->x[17], policy, 0);
		frame->pc = next_pc;
		return HAKIOS_PAUTH_STEPPED;
	case 0xd50320ff: /* XPACLRI */
	case 0xd503231f: case 0xd503235f: /* PACIAZ, PACIBZ */
	case 0xd503239f: case 0xd50323df: /* AUTIAZ, AUTIBZ */
	case 0xd503233f: case 0xd503237f: /* PACIASP, PACIBSP */
	case 0xd50323bf: case 0xd50323ff: /* AUTIASP, AUTIBSP */
		frame->x[30] = hakios_pauth_strip(frame->x[30], policy, 0);
		frame->pc = next_pc;
		return HAKIOS_PAUTH_STEPPED;
	}

	/* Register PAC/AUT and their zero-modifier variants; XPACI/XPACD. */
	base = instruction & 0xfffffc00u;
	family = base & ~0x1c00u;
	if (family == 0xdac10000u) {
		if (rd != 31)
			frame->x[rd] = hakios_pauth_strip(frame->x[rd], policy, !!(instruction & 0x800u));
		frame->pc = next_pc;
		return HAKIOS_PAUTH_STEPPED;
	}
	base = instruction & 0xffffffe0u;
	if ((base >= 0xdac123e0u && base <= 0xdac13fe0u &&
	    ((base - 0xdac123e0u) & 0x3ffu) == 0) ||
	    base == 0xdac143e0u || base == 0xdac147e0u) {
		if (rd != 31)
			frame->x[rd] = hakios_pauth_strip(frame->x[rd], policy,
			    base == 0xdac147e0u || (base < 0xdac14000u && !!(instruction & 0x800u)));
		frame->pc = next_pc;
		return HAKIOS_PAUTH_STEPPED;
	}

	base = instruction & 0xfffffc00u;
	if (base == 0xd71f0800u || base == 0xd71f0c00u ||
	    base == 0xd73f0800u || base == 0xd73f0c00u) {
		target = hakios_pauth_reg(frame, rn);
		link = !!(instruction & 0x00200000u);
		goto branch;
	}
	base = instruction & 0xfffffc1fu;
	if (base == 0xd61f081fu || base == 0xd61f0c1fu ||
	    base == 0xd63f081fu || base == 0xd63f0c1fu) {
		target = hakios_pauth_reg(frame, rn);
		link = !!(instruction & 0x00200000u);
		goto branch;
	}
	if (instruction == 0xd65f0bffu || instruction == 0xd65f0fffu) {
		target = frame->x[30];
		goto branch;
	}

	/* LDRAA/LDRAB: signed 10-bit offset scaled by 8; optional preindex. */
	base = instruction & 0xffa00400u;
	if (base == 0xf8200400u || base == 0xf8a00400u) {
		int writeback = !!(instruction & 0x800u);
		int offset = (int)(((instruction >> 12) & 0x1ffu) |
		    ((instruction >> 13) & 0x200u));
		uint64_t source = rn == 31 ? frame->sp : frame->x[rn];
		int displacement;

		if (offset & 0x200)
			offset -= 0x400;
		displacement = offset * 8;
		if (writeback && rn != 31 && rn == rd)
			return HAKIOS_PAUTH_UNHANDLED; /* constrained unpredictable */
		if (rn == 31 && (source & 15))
			return HAKIOS_PAUTH_BAD_ADDRESS;
		/* Tagged-base arithmetic still needs a separately tested TBI contract. */
		if (source & 0xff00000000000000ULL)
			return HAKIOS_PAUTH_UNHANDLED;
		source = hakios_pauth_strip(source, policy, 0);
		if (displacement < 0 && source < (uint64_t)(-displacement))
			return HAKIOS_PAUTH_BAD_ADDRESS;
		if (displacement >= 0 && source > policy->user_limit - 1 - (uint64_t)displacement)
			return HAKIOS_PAUTH_BAD_ADDRESS;
		address = displacement < 0 ? source - (uint64_t)(-displacement) :
		    source + (uint64_t)displacement;
		if (address > policy->user_limit - 8)
			return HAKIOS_PAUTH_BAD_ADDRESS;
		if (!policy->read64)
			return HAKIOS_PAUTH_UNHANDLED;
		if (!policy->read64(address, &value, policy->context))
			return HAKIOS_PAUTH_READ_FAILED;
		if (rd != 31)
			frame->x[rd] = value; /* the loaded value is not authenticated */
		if (writeback) {
			if (rn == 31)
				frame->sp = address;
			else
				frame->x[rn] = address;
		}
		frame->pc = next_pc;
		return HAKIOS_PAUTH_STEPPED;
	}

	/* PACGA, privileged ERETAA/ERETAB and unknown encodings stay unhandled. */
	return HAKIOS_PAUTH_UNHANDLED;

branch:
	target = hakios_pauth_strip(target, policy, 0);
	if (target & 3)
		return HAKIOS_PAUTH_BAD_TARGET;
	/* Read the target before changing LR, including BLRAA X30, Xm. */
	if (link)
		frame->x[30] = next_pc;
	frame->pc = target;
	return HAKIOS_PAUTH_STEPPED;
}

#endif
