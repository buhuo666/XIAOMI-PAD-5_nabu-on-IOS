/*
 * A deliberately gated undefined-instruction experiment for plain arm64 tests.
 * It does not change grade_binary, advertise arm64e, or start the iPad donor.
 */
#ifndef HAKIOS_PAUTH_XNU_H
#define HAKIOS_PAUTH_XNU_H

#if defined(GENERIC_GIC_V3_IRQ) && !defined(HAS_APPLE_PAC)
#include <arm64/hakios_pauth_compat.h>
#include <pexpert/pexpert.h>

static int
hakios_pauth_copyin64(uint64_t address, uint64_t *value, void *context)
{
	(void)context;
	return copyin((user_addr_t)address, value, sizeof(*value)) == 0;
}

static int
hakios_pauth_xnu_step(arm_saved_state_t *state, uint32_t instruction)
{
	struct hakios_pauth_frame frame;
	struct hakios_pauth_policy policy = {
		.user_limit = 1ULL << 48,
		.data_tag_mask = 0xff00000000000000ULL,
		.read64 = hakios_pauth_copyin64,
	};
	int enabled = 0;
	uint64_t isar1;

	if (!PSR64_IS_USER64(get_saved_state_cpsr(state)) ||
	    !PE_parse_boot_argn("pauth_unsigned_test", &enabled, sizeof(enabled)) || enabled != 1)
		return 0;
	isar1 = __builtin_arm_rsr64("ID_AA64ISAR1_EL1");
	/* Do not mix this unsigned experiment with real address/generic PAuth. */
	if (isar1 & ((0xffULL << 4) | (0xffULL << 24)))
		return 0;
	for (unsigned int i = 0; i < 29; i++)
		frame.x[i] = get_saved_state_reg(state, i);
	frame.x[29] = get_saved_state_fp(state);
	frame.x[30] = get_saved_state_lr(state);
	frame.sp = get_saved_state_sp(state);
	frame.pc = get_saved_state_pc(state);
	frame.pstate = get_saved_state_cpsr(state);
	if (hakios_pauth_step(instruction, &frame, &policy) != HAKIOS_PAUTH_STEPPED)
		return 0;
	for (unsigned int i = 0; i < 29; i++)
		set_saved_state_reg(state, i, frame.x[i]);
	set_saved_state_fp(state, frame.x[29]);
	set_saved_state_lr(state, frame.x[30]);
	set_saved_state_sp(state, frame.sp);
	set_saved_state_pc(state, frame.pc);
	return 1;
}
#else
static int
hakios_pauth_xnu_step(arm_saved_state_t *state, uint32_t instruction)
{
	(void)state;
	(void)instruction;
	return 0;
}
#endif
#endif
