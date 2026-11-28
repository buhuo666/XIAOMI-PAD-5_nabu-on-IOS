static int
minisandbox_policy_syscall(struct proc *p, int call, user_addr_t arg)
{
	if (call >= 0 && call < 64 && (minisandbox_seen & (1ULL << call)) == 0) {
		minisandbox_seen |= 1ULL << call;
		printf("minisandbox: request %d (first seen from %s[%d]): %s\n", call, p->p_comm, proc_getpid(p),
		    call == SANDBOX_SYSCALL_CONTAINER_PATH ? "answered" : "allowed");
	}
	if (call == SANDBOX_SYSCALL_CONTAINER_PATH) {
		return minisandbox_container_path(arg);
	}
	return 0;
}
