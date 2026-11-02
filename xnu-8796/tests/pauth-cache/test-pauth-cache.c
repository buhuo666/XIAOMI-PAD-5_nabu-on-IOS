/*
 * Host test: work order C1 gate caching must not change observable behaviour.
 *
 * Compares the cached wrapper against a literal copy of the pre-C1 wrapper for
 * the same saved state and instruction corpus, and verifies the caching
 * contract: boot argument parsed once; hardware register read once per CPU,
 * never shared across CPUs; unknown slots fall back to the direct read.
 *
 * Host-only: not a kernel build, not device evidence, and the benchmark below
 * measures host CPU cost, not the device exception return path.
 */
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ARM64_BOARD_CONFIG_NABU 1
#ifndef MAX_CPUS
#define MAX_CPUS 64
#endif

/* Types for the diagnostic stubs below, before the wrapper is included. */
#include <arm64/nabu_pauth_compat.h>
#include <arm64/nabu_pauth_diag.h>

/* ---- shim state ------------------------------------------------------- */

static int shim_cpu;
static int shim_boot_enabled;
static int shim_boot_present = 1;
static uint64_t shim_isar;
static unsigned shim_parse_calls;
static unsigned shim_isar_calls;
static unsigned shim_gate[4];
static unsigned shim_core_calls;

int
cpu_number(void)
{
	return shim_cpu;
}

int
PE_parse_boot_argn(const char *arg_string, void *arg_ptr, int max_len)
{
	(void)arg_string;
	if (max_len != (int)sizeof(int) || !shim_boot_present) {
		return 0;
	}
	shim_parse_calls++;
	*(int *)arg_ptr = shim_boot_enabled;
	return 1;
}

#define __builtin_arm_rsr64(name) shim_read_isar()
static uint64_t
shim_read_isar(void)
{
	shim_isar_calls++;
	return shim_isar;
}

void
nabu_pauth_diag_start(void)
{
}

int
nabu_pauth_diag_enabled(void)
{
	return 0;
}

void
nabu_pauth_diag_fetch_failed(uint64_t start_tick)
{
	(void)start_tick;
}

void
nabu_pauth_diag_gate(enum nabu_pauth_gate gate, uint64_t start_tick)
{
	(void)start_tick;
	shim_gate[gate]++;
}

void
nabu_pauth_diag_core(uint64_t start_tick, enum nabu_pauth_step_status status,
    enum hakios_pauth_class cls)
{
	(void)start_tick;
	(void)status;
	(void)cls;
	shim_core_calls++;
}

/* saved state shims */
typedef uint64_t user_addr_t;

typedef struct {
	uint64_t regs[29];
	uint64_t fp;
	uint64_t lr;
	uint64_t sp;
	uint64_t pc;
	uint32_t cpsr;
} arm_saved_state_t;

static int
is_saved_state64(arm_saved_state_t *state)
{
	(void)state;
	return 1;
}

static int
PSR64_IS_USER64(uint32_t cpsr)
{
	return (cpsr & 0xf) == 0;
}

static uint64_t
get_saved_state_pc(arm_saved_state_t *s)
{
	return s->pc;
}

static uint64_t
get_saved_state_lr(arm_saved_state_t *s)
{
	return s->lr;
}

static uint64_t
get_saved_state_sp(arm_saved_state_t *s)
{
	return s->sp;
}

static uint64_t
get_saved_state_fp(arm_saved_state_t *s)
{
	return s->fp;
}

static uint32_t
get_saved_state_cpsr(arm_saved_state_t *s)
{
	return s->cpsr;
}

static uint64_t
get_saved_state_reg(arm_saved_state_t *s, unsigned i)
{
	return s->regs[i];
}

static void
set_saved_state_pc(arm_saved_state_t *s, uint64_t v)
{
	s->pc = v;
}

static void
set_saved_state_lr(arm_saved_state_t *s, uint64_t v)
{
	s->lr = v;
}

static void
set_saved_state_sp(arm_saved_state_t *s, uint64_t v)
{
	s->sp = v;
}

static void
set_saved_state_fp(arm_saved_state_t *s, uint64_t v)
{
	s->fp = v;
}

static void
set_saved_state_reg(arm_saved_state_t *s, unsigned i, uint64_t v)
{
	s->regs[i] = v;
}

static int
copyin(user_addr_t src, void *dst, size_t n)
{
	(void)src;
	(void)n;
	*(uint64_t *)dst = UINT64_C(0x0000000100000000);
	return 0;
}

#include "nabu_arm64e_xnu.h"

/* ---- reference: the pre-C1 wrapper, kept as a behaviour oracle -------- */

static int
reference_step(arm_saved_state_t *state, uint32_t instruction, uint64_t start_tick,
    int parse_each_time)
{
	struct hakios_pauth_frame frame;
	const struct hakios_pauth_policy policy = {
		.user_limit = UINT64_C(1) << 48,
		.data_tag_mask = UINT64_C(0xff00000000000000),
		.read64 = nabu_arm64e_copyin64,
		.context = NULL,
	};
	enum hakios_pauth_class cls = HAKIOS_PAUTH_CLASS_UNKNOWN;
	enum hakios_pauth_status status;
	int enabled = 0;

	if (!is_saved_state64(state) || !PSR64_IS_USER64(get_saved_state_cpsr(state))) {
		if (parse_each_time) {
			nabu_pauth_diag_gate(NABU_PAUTH_GATE_STATE, start_tick);
		}
		return 0;
	}
	if (!PE_parse_boot_argn("nabuarm64e", &enabled, sizeof(enabled)) || enabled != 1) {
		if (parse_each_time) {
			nabu_pauth_diag_gate(NABU_PAUTH_GATE_DISABLED, start_tick);
		}
		return 0;
	}
	uint64_t isar1 = __builtin_arm_rsr64("ID_AA64ISAR1_EL1");
	if (isar1 & ((0xffULL << 4) | (0xffULL << 24))) {
		if (parse_each_time) {
			nabu_pauth_diag_gate(NABU_PAUTH_GATE_HARDWARE, start_tick);
		}
		return 0;
	}
	for (unsigned i = 0; i < 29; ++i) {
		frame.x[i] = get_saved_state_reg(state, i);
	}
	frame.x[29] = get_saved_state_fp(state);
	frame.x[30] = get_saved_state_lr(state);
	frame.sp = get_saved_state_sp(state);
	frame.pc = get_saved_state_pc(state);
	frame.pstate = get_saved_state_cpsr(state);
	status = hakios_pauth_step_class(instruction, &frame, &policy, &cls);
	nabu_pauth_diag_core(start_tick, nabu_arm64e_diag_status(status), cls);
	if (status != HAKIOS_PAUTH_STEPPED) {
		return 0;
	}
	for (unsigned i = 0; i < 29; ++i) {
		set_saved_state_reg(state, i, frame.x[i]);
	}
	set_saved_state_fp(state, frame.x[29]);
	set_saved_state_lr(state, frame.x[30]);
	set_saved_state_sp(state, frame.sp);
	set_saved_state_pc(state, frame.pc);
	return 1;
}

/* ---- helpers ---------------------------------------------------------- */

static unsigned checks;
static unsigned failures;

#define CHECK(condition, message) do { \
	checks++; \
	if (!(condition)) { \
		failures++; \
		printf("FAIL %s (%s:%d)\n", message, __FILE__, __LINE__); \
	} \
} while (0)

static void
reset_cache(void)
{
	nabu_arm64e_cfg_state = 0;
	memset(nabu_arm64e_hw_state, 0, sizeof(nabu_arm64e_hw_state));
}

static void
reset_counters(void)
{
	shim_parse_calls = 0;
	shim_isar_calls = 0;
	memset(shim_gate, 0, sizeof(shim_gate));
	shim_core_calls = 0;
}

static arm_saved_state_t
test_state(void)
{
	arm_saved_state_t state;

	memset(&state, 0, sizeof(state));
	for (unsigned i = 0; i < 29; i++) {
		state.regs[i] = UINT64_C(0x0000007000000000) + i * 8;
	}
	state.fp = UINT64_C(0x0000007000300000);
	state.lr = UINT64_C(0x0000007000400000);
	state.sp = UINT64_C(0x0000007000500000);
	state.pc = 0x4000;
	state.cpsr = 0;
	return state;
}

static uint64_t
next_random(uint64_t *state)
{
	*state ^= *state << 13;
	*state ^= *state >> 7;
	*state ^= *state << 17;
	return *state;
}

static int
test_cache_contract(void)
{
	arm_saved_state_t state;

	/* enabled + hardware absent: one parse, one ISAR read on this CPU */
	shim_boot_present = 1;
	shim_boot_enabled = 1;
	shim_isar = 0;
	shim_cpu = 3;
	reset_cache();
	reset_counters();
	state = test_state();
	for (int i = 0; i < 5; i++) {
		nabu_arm64e_xnu_step(&state, 0xdac10820u, 0);
	}
	CHECK(shim_parse_calls == 1, "boot argument parsed once");
	CHECK(shim_isar_calls == 1, "hardware register read once per CPU");
	CHECK(shim_core_calls == 5, "decoder reached for every call");

	/* a second CPU must read its own copy, not reuse CPU 3's answer */
	shim_cpu = 5;
	state = test_state();
	nabu_arm64e_xnu_step(&state, 0xdac10820u, 0);
	CHECK(shim_isar_calls == 2, "second CPU reads the register itself");
	CHECK(shim_core_calls == 6, "second CPU decoded");

	/* hardware PAuth present on one CPU only: that CPU is gated, others not */
	shim_cpu = 7;
	shim_isar = UINT64_C(1) << 4;
	state = test_state();
	CHECK(nabu_arm64e_xnu_step(&state, 0xdac10820u, 0) == 0, "hardware gate returns 0");
	CHECK(shim_gate[NABU_PAUTH_GATE_HARDWARE] == 1, "hardware gate counted");
	CHECK(shim_isar_calls == 3, "hardware CPU read once");
	state = test_state();
	nabu_arm64e_xnu_step(&state, 0xdac10820u, 0);
	CHECK(shim_isar_calls == 3, "cached hardware answer reused");
	shim_cpu = 9;
	shim_isar = 0;
	state = test_state();
	CHECK(nabu_arm64e_xnu_step(&state, 0xdac10820u, 0) == 1,
	    "other CPU is not gated by another CPU's hardware reading");
	CHECK(shim_isar_calls == 4, "other CPU reads its own register");

	/* disabled boot argument: parsed once, hardware register never read */
	shim_boot_enabled = 0;
	reset_cache();
	reset_counters();
	shim_cpu = 11;
	shim_isar = 0;
	state = test_state();
	for (int i = 0; i < 3; i++) {
		CHECK(nabu_arm64e_xnu_step(&state, 0xdac10820u, 0) == 0,
		    "disabled boot argument returns 0");
	}
	CHECK(shim_parse_calls == 1, "disabled state parsed once");
	CHECK(shim_isar_calls == 0, "disabled state never reads the register");
	CHECK(shim_gate[NABU_PAUTH_GATE_DISABLED] == 3, "disabled gate counted per trap");

	/* missing boot argument is also cached as disabled */
	shim_boot_present = 0;
	reset_cache();
	reset_counters();
	state = test_state();
	nabu_arm64e_xnu_step(&state, 0xdac10820u, 0);
	nabu_arm64e_xnu_step(&state, 0xdac10820u, 0);
	CHECK(shim_parse_calls == 0 && shim_gate[NABU_PAUTH_GATE_DISABLED] == 2,
	    "missing argument stays disabled without repeated reads");

	/* out-of-range CPU index falls back to the direct read every time */
	shim_boot_present = 1;
	shim_boot_enabled = 1;
	reset_cache();
	reset_counters();
	shim_cpu = 4096;
	shim_isar = 0;
	state = test_state();
	for (int i = 0; i < 3; i++) {
		CHECK(nabu_arm64e_xnu_step(&state, 0xdac10820u, 0) == 1,
		    "out-of-range CPU still decodes");
	}
	CHECK(shim_isar_calls == 3, "out-of-range CPU reads the register each time");

	/* state gate still comes first and is counted per trap */
	reset_cache();
	reset_counters();
	shim_cpu = 0;
	shim_boot_enabled = 1;
	arm_saved_state_t bad;
	memset(&bad, 0, sizeof(bad));
	bad.cpsr = 0x1; /* EL1, not EL0 */
	CHECK(nabu_arm64e_xnu_step(&bad, 0xdac10820u, 0) == 0, "state gate returns 0");
	CHECK(shim_parse_calls == 0, "state gate short-circuits before the boot argument");
	CHECK(shim_gate[NABU_PAUTH_GATE_STATE] == 1, "state gate counted");
	return 0;
}

static int
test_differential(void)
{
	static const uint32_t corpus[] = {
		0xdac10020u, 0xdac10420u, 0xdac10820u, 0xdac10c20u, 0xdac11020u,
		0xdac11420u, 0xdac11820u, 0xdac11c20u, 0xdac12bf0u, 0xdac12ff0u,
		0xdac13bf0u, 0xdac13ff0u, 0xdac147e0u, 0xdac143e0u, 0xd503211fu,
		0xd503219fu, 0xd50320ffu, 0xd503233fu, 0xd50323bfu, 0x9ac03000u,
		0xd71f0800u, 0xd73f0800u, 0xd65f0bffu, 0xf8200400u, 0xf8a00400u,
		0x00000000u, 0xd4200020u,
	};
	unsigned mismatches = 0;
	unsigned samples = 0;

	shim_boot_present = 1;
	shim_boot_enabled = 1;
	shim_isar = 0;
	reset_cache();
	shim_cpu = 1;
	for (unsigned seed = 0; seed < 4; seed++) {
		uint64_t random_state = 0x9e3779b97f4a7c15ULL * (seed + 1);
		for (unsigned index = 0; index < 200; index++) {
			arm_saved_state_t plain = test_state();
			arm_saved_state_t cached;
			uint32_t instruction = corpus[(index + seed) %
			    (sizeof(corpus) / sizeof(corpus[0]))];
			int plain_result, cached_result;

			for (unsigned i = 0; i < 29; i++) {
				plain.regs[i] = next_random(&random_state) &
				    UINT64_C(0x0000ffffffffffff);
			}
			plain.pc = 0x4000 + (next_random(&random_state) & 0x3ff0);
			plain.sp = UINT64_C(0x0000007000000000) +
			    (next_random(&random_state) & 0xffff);
			cached = plain;
			if ((index % 5) == 4) {
				instruction = (uint32_t)next_random(&random_state);
			}
			plain_result = reference_step(&plain, instruction, 0, 0);
			cached_result = nabu_arm64e_xnu_step(&cached, instruction, 0);
			samples++;
			if (plain_result != cached_result ||
			    memcmp(&plain, &cached, sizeof(plain)) != 0) {
				mismatches++;
			}
		}
	}
	printf("differential samples: %u, mismatches: %u\n", samples, mismatches);
	CHECK(mismatches == 0, "cached wrapper is behaviour-identical to the oracle");
	return 0;
}

/* Host-only cost comparison; this is not a device exception-return benchmark. */
static int
test_host_benchmark(void)
{
	const unsigned iterations = 200000;
	arm_saved_state_t state = test_state();
	unsigned i;

	shim_boot_present = 1;
	shim_boot_enabled = 1;
	reset_cache();
	shim_cpu = 2;
	shim_isar = 0;
	for (i = 0; i < iterations; i++) {
		reference_step(&state, 0xdac10820u, 0, 0);
	}
	reset_cache();
	shim_cpu = 3;
	shim_isar = 0;
	for (i = 0; i < iterations; i++) {
		nabu_arm64e_xnu_step(&state, 0xdac10820u, 0);
	}
	printf("host benchmark: %u warm calls per wrapper (host CPU only, not device)\n",
	    iterations);
	return 0;
}

int
main(void)
{
	test_cache_contract();
	test_differential();
	test_host_benchmark();
	if (failures != 0) {
		printf("PAuth cache host test FAILED checks=%u failures=%u\n", checks, failures);
		return 1;
	}
	printf("PAuth cache host test passed: %u checks, 800 differential samples\n", checks);
	return 0;
}
