/* hostap crypto's common.c alias boundary, isolated from unrelated OS helpers.
 * Equivalent to the small common.c helper from hostap 2.11 (BSD license). */
void * __attribute__((noinline)) __hide_aliasing_typecast(void *p)
{
    return p;
}
