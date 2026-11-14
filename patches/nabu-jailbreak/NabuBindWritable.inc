/* Writable bindfs operations for the Nabu persistent jailbreak prefix.
 * Included after the original bindfs read operations and before its vnode table.
 * Writable file mappings use the lower vnode's VM object via the mmap calldown below.
 */
extern memory_object_control_t ubc_getobject(vnode_t, int);

static int
nabu_bind_lower(vnode_t upper, vnode_t *lower)
{
    if (upper == NULL) { *lower = NULL; return 0; }
    *lower = BINDVPTOLOWERVP(upper);
    return vnode_getwithvid(*lower, BINDVPTOLOWERVID(upper));
}

static void
nabu_bind_size(vnode_t upper, vnode_t lower)
{
    if (vnode_isreg(upper)) (void)ubc_setsize(upper, ubc_getsize(lower));
}

#define NABU_BIND_ONE(name, member, mutates, call) \
static int nabu_bindfs_##name(struct vnop_##name##_args *ap) { \
    vnode_t upper = ap->member, lower = NULL; \
    if ((mutates) && vfs_isrdonly(vnode_mount(upper))) return EROFS; \
    int error = nabu_bind_lower(upper, &lower); \
    if (error) return error; \
    error = (call); \
    if (mutates) nabu_bind_size(upper, lower); \
    vnode_put(lower); \
    return error; \
}

NABU_BIND_ONE(write, a_vp, 1, VNOP_WRITE(lower, ap->a_uio, ap->a_ioflag, ap->a_context))
NABU_BIND_ONE(setattr, a_vp, 1, VNOP_SETATTR(lower, ap->a_vap, ap->a_context))
NABU_BIND_ONE(setxattr, a_vp, 1, VNOP_SETXATTR(lower, ap->a_name, ap->a_uio, ap->a_options, ap->a_context))
NABU_BIND_ONE(removexattr, a_vp, 1, VNOP_REMOVEXATTR(lower, ap->a_name, ap->a_options, ap->a_context))
NABU_BIND_ONE(allocate, a_vp, 1, VNOP_ALLOCATE(lower, ap->a_length, ap->a_flags, ap->a_bytesallocated, ap->a_offset, ap->a_context))
NABU_BIND_ONE(ioctl, a_vp, 0, VNOP_IOCTL(lower, ap->a_command, ap->a_data, ap->a_fflag, ap->a_context))
NABU_BIND_ONE(advlock, a_vp, 0, VNOP_ADVLOCK(lower, ap->a_id, ap->a_op, ap->a_fl, ap->a_flags, ap->a_context, ap->a_timeout))
NABU_BIND_ONE(fsync, a_vp, 0, VNOP_FSYNC(lower, ap->a_waitfor, ap->a_context))
#undef NABU_BIND_ONE

static int
nabu_bind_created(vnode_t directory, vnode_t lower, struct componentname *name, vnode_t *result)
{
    int error = bind_nodeget(vnode_mount(directory), lower, directory, result, name, 0);
    if (!error) nabu_bind_size(*result, lower);
    vnode_put(lower);
    return error;
}

#define NABU_BIND_CREATE(name, call) \
static int nabu_bindfs_##name(struct vnop_##name##_args *ap) { \
    if (vfs_isrdonly(vnode_mount(ap->a_dvp))) return EROFS; \
    vnode_t directory = NULL, created = NULL; \
    int error = nabu_bind_lower(ap->a_dvp, &directory); \
    if (error) return error; \
    error = (call); \
    vnode_put(directory); \
    if (!error) error = nabu_bind_created(ap->a_dvp, created, ap->a_cnp, ap->a_vpp); \
    return error; \
}
NABU_BIND_CREATE(create, VNOP_CREATE(directory, &created, ap->a_cnp, ap->a_vap, ap->a_context))
NABU_BIND_CREATE(mkdir, VNOP_MKDIR(directory, &created, ap->a_cnp, ap->a_vap, ap->a_context))
NABU_BIND_CREATE(mknod, VNOP_MKNOD(directory, &created, ap->a_cnp, ap->a_vap, ap->a_context))
NABU_BIND_CREATE(symlink, VNOP_SYMLINK(directory, &created, ap->a_cnp, ap->a_vap, ap->a_target, ap->a_context))
#undef NABU_BIND_CREATE

static int
nabu_bind_pair(vnode_t first, vnode_t second, vnode_t *lower_first, vnode_t *lower_second)
{
    int error = nabu_bind_lower(first, lower_first);
    if (error) return error;
    error = nabu_bind_lower(second, lower_second);
    if (error) vnode_put(*lower_first);
    return error;
}

#define NABU_BIND_REMOVE(name, call) \
static int nabu_bindfs_##name(struct vnop_##name##_args *ap) { \
    if (vfs_isrdonly(vnode_mount(ap->a_dvp))) return EROFS; \
    vnode_t directory = NULL, lower = NULL; \
    int error = nabu_bind_pair(ap->a_dvp, ap->a_vp, &directory, &lower); \
    if (error) return error; \
    error = (call); \
    if (!error) { cache_purge(ap->a_dvp); cache_purge(ap->a_vp); } \
    vnode_put(lower); vnode_put(directory); \
    return error; \
}
NABU_BIND_REMOVE(remove, VNOP_REMOVE(directory, lower, ap->a_cnp, ap->a_flags, ap->a_context))
NABU_BIND_REMOVE(rmdir, VNOP_RMDIR(directory, lower, ap->a_cnp, ap->a_context))
#undef NABU_BIND_REMOVE

static int
nabu_bindfs_link(struct vnop_link_args *ap)
{
    if (vfs_isrdonly(vnode_mount(ap->a_tdvp))) return EROFS;
    vnode_t lower = NULL, directory = NULL;
    int error = nabu_bind_pair(ap->a_vp, ap->a_tdvp, &lower, &directory);
    if (error) return error;
    error = VNOP_LINK(lower, directory, ap->a_cnp, ap->a_context);
    if (!error) { cache_purge(ap->a_tdvp); cache_purge(ap->a_vp); }
    vnode_put(directory); vnode_put(lower);
    return error;
}

static int
nabu_bind_rename(vnode_t fdvp, vnode_t fvp, struct componentname *fcnp,
    vnode_t tdvp, vnode_t tvp, struct componentname *tcnp, vfs_rename_flags_t flags,
    int extended, vfs_context_t context)
{
    if (vfs_isrdonly(vnode_mount(fdvp)) || vfs_isrdonly(vnode_mount(tdvp))) return EROFS;
    vnode_t upper[] = {fdvp, fvp, tdvp, tvp}, lower[4] = {NULL};
    int error = 0, held = 0;
    for (; held < 4; held++) {
        error = nabu_bind_lower(upper[held], &lower[held]);
        if (error) goto out;
    }
    error = extended ? VNOP_RENAMEX(lower[0], lower[1], fcnp, lower[2], lower[3], tcnp, flags, context) :
        VNOP_RENAME(lower[0], lower[1], fcnp, lower[2], lower[3], tcnp, context);
    if (!error) {
        vnode_update_identity(fvp, tdvp, tcnp->cn_nameptr, tcnp->cn_namelen, tcnp->cn_hash,
            VNODE_UPDATE_PARENT | VNODE_UPDATE_NAME | VNODE_UPDATE_CACHE);
        if (tvp) {
            if (flags & VFS_RENAME_SWAP) vnode_update_identity(tvp, fdvp, fcnp->cn_nameptr,
                fcnp->cn_namelen, fcnp->cn_hash, VNODE_UPDATE_PARENT | VNODE_UPDATE_NAME | VNODE_UPDATE_CACHE);
            else cache_purge(tvp);
        }
        cache_purge(fdvp); cache_purge(tdvp);
    }
out:
    while (held > 0) { --held; if (lower[held]) vnode_put(lower[held]); }
    return error;
}

static int
nabu_bindfs_rename(struct vnop_rename_args *ap)
{
    return nabu_bind_rename(ap->a_fdvp, ap->a_fvp, ap->a_fcnp, ap->a_tdvp, ap->a_tvp, ap->a_tcnp, 0, 0, ap->a_context);
}

static int
nabu_bindfs_renamex(struct vnop_renamex_args *ap)
{
    return nabu_bind_rename(ap->a_fdvp, ap->a_fvp, ap->a_fcnp, ap->a_tdvp, ap->a_tvp, ap->a_tcnp,
        ap->a_flags, 1, ap->a_context);
}

/* Keep MAP_SHARED, normal I/O, locks and fsync on the same backing file.
 * Read-only bindfs mounts retain their original independent pager behavior.
 * The alias holds a usecount on its lower vnode for the lifetime of this lookup.
 */
memory_object_control_t
nabu_bindfs_mmap_getobject(vnode_t vp, int flags)
{
    if (vnode_tag(vp) == VT_BINDFS && !vfs_isrdonly(vnode_mount(vp))) {
        vnode_t lower = NULL;
        if (nabu_bind_lower(vp, &lower)) return MEMORY_OBJECT_CONTROL_NULL;
        memory_object_control_t control = nabu_bindfs_mmap_getobject(lower, flags);
        vnode_put(lower);
        return control;
    }
    return ubc_getobject(vp, flags);
}
