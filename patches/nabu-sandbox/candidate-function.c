static int
minisandbox_container_path(user_addr_t arg)
{
	struct {
		int64_t     pid;
		uint64_t    pidversion;
		user_addr_t buffer;
		user_size_t size;
		uint64_t    check_pidversion;
	} args;
	const size_t prefix_len = sizeof(SANDBOX_CONTAINER_VARIABLE) - 1;
	proc_t p;
	task_t task;
	vm_map_t map;
	vm_map_copy_t copy = NULL;
	vm_offset_t strings = 0;
	vm_size_t strings_size;
	user_addr_t user_stack;
	size_t argslen, len;
	const char *s, *end;
	int error;

	error = copyin(arg, &args, sizeof(args));
	if (error) {
		return error;
	}
	p = proc_find((int)args.pid);
	if (p == PROC_NULL) {
		return ESRCH;
	}
	if (args.check_pidversion && (uint64_t)proc_pidversion(p) != args.pidversion) {
		proc_rele(p);
		return ESRCH;
	}
	user_stack = p->user_stack;
	argslen = p->p_argslen;
	task = proc_task(p);
	if (user_stack == 0 || argslen == 0 || task == TASK_NULL) {
		proc_rele(p);
		return ENOENT;
	}
	/* the same way as sysctl_procargsx(): the task keeps the map alive once the process is let go */
	task_reference(task);
	proc_rele(p);
	map = get_task_map_reference(task);
	task_deallocate(task);
	if (map == VM_MAP_NULL) {
		return ENOENT;
	}
	strings_size = vm_map_round_page(argslen, vm_map_page_mask(map));
	if (kmem_alloc(kernel_map, &strings, strings_size, KMA_DATA | KMA_ZERO, VM_KERN_MEMORY_BSD) != KERN_SUCCESS) {
		vm_map_deallocate(map);
		return ENOMEM;
	}
	if (vm_map_copyin(map, (vm_map_address_t)(user_stack - strings_size), strings_size, FALSE, &copy) != KERN_SUCCESS) {
		copy = NULL;
	}
	vm_map_deallocate(map);
	if (copy == NULL || vm_map_copy_overwrite(kernel_map, strings, copy, strings_size, FALSE) != KERN_SUCCESS) {
		if (copy != NULL) {
			vm_map_copy_discard(copy);
		}
		kmem_free(kernel_map, strings, strings_size);
		return ENOENT;                       /* the process is on its way out, or has unmapped its own stack */
	}

	/* No success without an actual, NUL-terminated container path. */
	error = ENOENT;
	end = (const char *)(strings + strings_size);
	for (s = end - argslen; s < end; s += len + 1) {
		len = strnlen(s, end - s);
		if (len > prefix_len && s + len < end && strncmp(s, SANDBOX_CONTAINER_VARIABLE, prefix_len) == 0) {
			s += prefix_len;
			len -= prefix_len;
			error = len < args.size ? copyout(s, args.buffer, len + 1) : ENAMETOOLONG;
			break;
		}
	}
	kmem_free(kernel_map, strings, strings_size);
	return error;
}
