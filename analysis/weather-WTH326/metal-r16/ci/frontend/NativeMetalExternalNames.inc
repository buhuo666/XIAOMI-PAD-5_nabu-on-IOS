// CHG311 Notifications reached this private selector while creating icons.
// 20F66 MTLLibraryData::externFunctionNames (0x181af2a80) returns nil for
// ordinary libraries. Nabu loads standalone AIR/metallib, without external
// function libraries or a dynamic-link table; keep that same answer.
- (NSArray<NSString *> *)externFunctionNames { return nil; }
