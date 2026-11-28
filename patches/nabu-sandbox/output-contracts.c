/*
 * SET378: output-bearing Sandbox requests for the existing non-enforcing
 * policy. ARM64 layouts were checked against both halves of iPad7,3 20F66.
 * These are compatibility answers, not sandbox enforcement or Apple tokens.
 */
#define MINISANDBOX_QUERY_FILTER_DATA (1ULL << 26)
#define MINISANDBOX_BULK_MAX (1024ULL * 1024ULL)

static int
minisandbox_check_output(user_addr_t arg)
{
	/* 13 64-bit words; result pointer at 0, flags at 0x28. */
	struct {
		user_addr_t result;
		uint64_t pid, operation, filter_type, filter_value, flags;
		uint64_t identity, auxiliary, report, report_size, extra_result;
		user_addr_t filter_data, filter_size;
	} args;
	uint64_t allowed = 0;
	int error = copyin(arg, &args, sizeof(args));
	if (error) {
		return error;
	}
	/* No filter bytecode exists in this policy. The wrapper frees its
	 * malloc buffer on ENOTSUP; returning success would expose that buffer.
	 * Do not change ordinary permission checks to a denial. */
	if (args.flags & MINISANDBOX_QUERY_FILTER_DATA) {
		return ENOTSUP;
	}
	return copyout(&allowed, args.result, sizeof(allowed));
}

static int
minisandbox_extension_issue_output(user_addr_t arg)
{
	struct {
		user_addr_t extension_class;
		uint64_t type;
		user_addr_t resource;
		uint64_t flags;
		user_addr_t token;
		int64_t pid;
		uint64_t pidversion;
	} args;
	/* libsystem_sandbox itself emits this exact NUL-terminated sentinel
	 * for its unresolved/no-op path. consume("invalid") returns handle 0
	 * without a syscall; release(0) is already a no-op in our policy.
	 * Thus there is no invented authorization state, ID allocation or leak. */
	static const char no_op_token[] = "invalid";
	char string[1024];
	size_t length;
	int error = copyin(arg, &args, sizeof(args));
	if (error) {
		return error;
	}
	if (args.type > 6 || args.token == 0 ||
	    (args.flags & ~0x3c07fULL) != 0 ||
	    ((args.flags & 0x20000) && !(args.flags & 0x10000)) ||
	    (args.type != 3 && args.resource == 0)) {
		return EINVAL;
	}
	/* Match the two type-specific rejections visible in the native issuer. */
	if (((args.flags & 4) && args.type == 0) ||
	    ((args.flags & 8) && args.type != 0)) {
		return ENOTSUP;
	}
	error = copyinstr(args.extension_class, string, 256, &length);
	if (error) {
		return error;
	}
	if (length <= 1) {
		return EINVAL;
	}
	if (args.resource) {
		error = copyinstr(args.resource, string, sizeof(string), &length);
		if (error) {
			return error;
		}
	}
	if (args.flags & 0x10000) {
		proc_t target;
		if (args.pid != (int)args.pid) {
			return ESRCH;
		}
		target = proc_find((int)args.pid);
		if (target == PROC_NULL) {
			return ESRCH;
		}
		error = (args.flags & 0x20000) &&
		    (uint64_t)proc_pidversion(target) != args.pidversion ? ESRCH : 0;
		proc_rele(target);
		if (error) {
			return error;
		}
	}
	/* Request 5's fixed ABI supplies a 2048-byte output allocation. */
	return copyout(no_op_token, args.token, sizeof(no_op_token));
}

static int
minisandbox_bulk_check_output(user_addr_t arg)
{
	struct {
		int64_t pid;
		uint64_t pidversion;
		user_addr_t operation;
		uint64_t flags, count;
		user_addr_t items, results;
	} args;
	/* Native request 21 returns ONE BYTE per item, not int32_t. Its
	 * non-confined fast path does not inspect the 16-byte input items. */
	static const unsigned char allowed[256] = { 0 };
	proc_t target;
	uint64_t offset = 0;
	int error = copyin(arg, &args, sizeof(args));
	if (error) {
		return error;
	}
	if (args.operation == 0 || args.items == 0 || args.results == 0 || args.count == 0) {
		return EINVAL;
	}
	if (args.count >> 60 || args.count > MINISANDBOX_BULK_MAX ||
	    args.results > (user_addr_t)-1 - (args.count - 1)) {
		return ERANGE;
	}
	if (args.pid != (int)args.pid) {
		return ESRCH;
	}
	target = proc_find((int)args.pid);
	if (target == PROC_NULL) {
		return ESRCH;
	}
	error = (uint64_t)proc_pidversion(target) != args.pidversion ? ESRCH : 0;
	proc_rele(target);
	if (error) {
		return error;
	}
	/* Bounded chunks avoid allocating count * 16 bytes merely to allow.
	 * A copy fault returns failure even if an earlier chunk was written. */
	while (offset < args.count) {
		size_t bytes = args.count - offset;
		if (bytes > sizeof(allowed)) {
			bytes = sizeof(allowed);
		}
		error = copyout(allowed, args.results + offset, bytes);
		if (error) {
			return error;
		}
		offset += bytes;
	}
	return 0;
}
