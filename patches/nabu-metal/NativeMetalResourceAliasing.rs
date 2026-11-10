// SPDX-License-Identifier: MIT
// Included in NativeMetalObjects.rs; preserve its handle and error conventions.
#[unsafe(no_mangle)]
pub extern "C" fn nmb_buffer_make_aliasable(buffer: *const NmbBuffer) -> bool {
    guard(false, || {
        get(buffer)?.0.make_aliasable().map_err(e("buffer makeAliasable"))?;
        Ok(true)
    })
}

#[unsafe(no_mangle)]
pub extern "C" fn nmb_buffer_is_aliasable(buffer: *const NmbBuffer) -> bool {
    guard(false, || Ok(get(buffer)?.0.is_aliasable()))
}

#[unsafe(no_mangle)]
pub extern "C" fn nmb_texture_make_aliasable(texture: *const NmbTexture) -> bool {
    guard(false, || {
        get(texture)?.0.make_aliasable().map_err(e("texture makeAliasable"))?;
        Ok(true)
    })
}

#[unsafe(no_mangle)]
pub extern "C" fn nmb_texture_is_aliasable(texture: *const NmbTexture) -> bool {
    guard(false, || Ok(get(texture)?.0.is_aliasable()))
}
