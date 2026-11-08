// No allocation, new lock, device write, stack walk or crash-pointer probing.
// Replay the saved panic text through the existing logger after storage reporting.
using u32 = unsigned int;
using u64 = unsigned long long;

struct NabuReturnTrace {
    u32 state;
    u32 reserved;
    u64 lr, fp, sp, mpidr, esr, far, elr;
};
static_assert(sizeof(NabuReturnTrace) == 64, "assembly record layout");

extern "C" {
NabuReturnTrace nabu_return_trace_record = {};
void loader_log_line(const char *);
void nabu_panic_early_report(void);
}

static char trace_line[192];

static char *text(char *at, const char *value)
{
    while (*value) *at++ = *value++;
    return at;
}

static char *hex(char *at, u64 value)
{
    at = text(at, "0x");
    for (int shift = 60; shift >= 0; shift -= 4) {
        unsigned digit = (value >> shift) & 15;
        *at++ = digit < 10 ? '0' + digit : 'a' + digit - 10;
    }
    return at;
}

static void emit(char *end)
{
    *end++ = '\n';
    *end = 0;
    loader_log_line(trace_line);
}

extern "C" void nabu_return_trace_report(void)
{
    const NabuReturnTrace &r = nabu_return_trace_record;
    u32 state = __atomic_load_n(&r.state, __ATOMIC_ACQUIRE);
    if (state != 2) {
        char *p = text(trace_line, "NABU RETURN FIRST: incomplete state=");
        emit(hex(p, state));
        nabu_panic_early_report();
        return;
    }
    char *p = text(trace_line, "NABU RETURN FIRST: LR=");
    p = hex(p, r.lr); p = text(p, " SP="); p = hex(p, r.sp);
    p = text(p, " FP="); p = hex(p, r.fp); emit(p);
    p = text(trace_line, "NABU RETURN FIRST: MPIDR=");
    p = hex(p, r.mpidr); p = text(p, " LR may reflect a tail caller"); emit(p);
    p = text(trace_line, "NABU RETURN SYSREG (may be stale): ESR=");
    p = hex(p, r.esr); p = text(p, " FAR="); p = hex(p, r.far);
    p = text(p, " ELR="); p = hex(p, r.elr); emit(p);
    nabu_panic_early_report();
}
