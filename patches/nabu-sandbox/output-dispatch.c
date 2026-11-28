static int
minisandbox_policy_syscall(struct proc *p, int call, user_addr_t arg)
{
	if (call >= 0 && call < 64 && (minisandbox_seen & (1ULL << call)) == 0) {
		minisandbox_seen |= 1ULL << call;
		printf("minisandbox: request %d (first seen from %s[%d]): %s\n", call, p->p_comm, proc_getpid(p),
		    call == SANDBOX_SYSCALL_CONTAINER_PATH || call == 2 || call == 5 || call == 21 ? "answered" : "allowed");
	}
	if (call == SANDBOX_SYSCALL_CONTAINER_PATH) {
		return minisandbox_container_path(arg);
	}
	if (call == 2) {
		return minisandbox_check_output(arg);
	}
	if (call == 5) {
		return minisandbox_extension_issue_output(arg);
	}
	if (call == 21) {
		return minisandbox_bulk_check_output(arg);
	}
	return 0;
}
