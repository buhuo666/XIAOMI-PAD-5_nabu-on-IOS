// SPDX-License-Identifier: MIT
// Run180: the copied registry owns this mapping until its entry is removed.
use std::ptr::NonNull;

unsafe extern "C" {
    static mach_task_self_: u32;
    fn mach_vm_remap(
        target_task: u32,
        target_address: *mut u64,
        size: u64,
        mask: u64,
        flags: i32,
        source_task: u32,
        source_address: u64,
        copy: i32,
        current_protection: *mut i32,
        maximum_protection: *mut i32,
        inheritance: i32,
    ) -> i32;
    fn mach_vm_deallocate(task: u32, address: u64, size: u64) -> i32;
}

pub(super) struct OwnedPages {
    pointer: NonNull<u8>,
    length: u64,
}

// The entry's registry lock serializes accesses and removal. This value alone
// owns the new mapping; its drop never deallocates the caller's address range.
unsafe impl Send for OwnedPages {}

impl OwnedPages {
    /// Retain the same VM object without copying its bytes or raising permissions.
    /// The caller's range is readable when this call succeeds; later changes to
    /// that VA do not replace the object in this mapping.
    pub(super) unsafe fn new(pointer: NonNull<u8>, length: usize) -> Result<Self, i32> {
        let mut address = 0u64;
        let (mut current, mut maximum) = (0i32, 0i32);
        // XNU8796 vm_statistics.h: ANYWHERE | RETURN_DATA_ADDR. The latter
        // preserves an unaligned source's offset within the retained pages.
        let status = unsafe {
            mach_vm_remap(mach_task_self_, &mut address, length as u64, 0,
                          0x00000001 | 0x00100000, mach_task_self_,
                          pointer.as_ptr() as u64, 0, &mut current, &mut maximum, 0)
        };
        if status != 0 {
            return Err(status);
        }
        let owned = Self {
            // VM_FLAGS_ANYWHERE chooses a non-null user mapping.
            pointer: unsafe { NonNull::new_unchecked(address as *mut u8) },
            length: length as u64,
        };
        if current & 1 == 0 {
            // An initially unreadable range remains a failed import. Drop the
            // newly created alias before returning KERN_PROTECTION_FAILURE.
            return Err(2);
        }
        Ok(owned)
    }

    pub(super) fn pointer(&self) -> NonNull<u8> {
        self.pointer
    }
}

impl Drop for OwnedPages {
    fn drop(&mut self) {
        // mach_vm_deallocate rounds the data range to the pages returned by
        // remap, including any leading offset. Only this alias is removed.
        unsafe { mach_vm_deallocate(mach_task_self_, self.pointer.as_ptr() as u64, self.length); }
    }
}
