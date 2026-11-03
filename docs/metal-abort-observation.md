# Metal abort operands (0181)

The existing mediaserverd abort stack has a shared return address for two
different validation failures. Patch 0181 distinguishes the live conditions
without changing Metal, user objects, return values, or the shared cache.
It is an observation needed to select a functional repair, not a desktop fix.

Enable with `nabumtlprobe=1`. Only `mediaserverd` SIGABRT is observed. At most
16 search frame records plus two parent records, a fixed codeword table,
and four saved-operand reads are
copied through `copyin`; no heap scan, allocation, user invocation, or write
is performed. One complete console record is attempted per matching crash.
Existing LOGQ counters continue to account for any publication loss.

## Frame derivation

This layout belongs to Metal image UUID
`494e0f55-a2d7-3564-9d3a-8fb84a90bcd2` and Portrait image UUID
`013ee646-4106-379d-ab24-0a435242a950` in the analyzed iPadOS cache. The live
probe checks selected ordinary instructions and the three adjacent return
addresses. It does not authenticate the complete installed cache. PAC/RETAB
instructions are excluded because the existing compatibility engine may
replace them. Addresses below are unslid.

| Frame | Saved LR | Parent FP distance | Observation |
| --- | --- | --- | --- |
| `_MTLReportFailure.cold.1` | `0x181d29fd4` | 208 | FP−8 = caller x19 = line |
| `_MTLReportFailure` | `0x181c1c4d4` | 64 | FP−8 = setter x19 = computeFunction; FP−56 = caller x25 = loop byte offset |
| `setComputeFunction:` | `0x1c22f1d7c` | 128 | parent FP identifies `_setupPipelines` |

The cold helper subtracts 32 bytes and sets FP=SP+16. ReportFailure subtracts
208 and sets FP=SP+192; setter subtracts 64 and sets FP=SP+48; setup subtracts
128 and sets FP=SP+112. Setup SP+24 (FP−88) is MTLLibrary, SP+16 (FP−96) is
pipeline library. The setter leaves x25 unchanged. ReportFailure saves x25
at SP+136 (FP−56). Loop offset must be divisible by 8 and less than 96.

Accepted interpretations require either line 692 with null computeFunction,
or line 697 with non-null computeFunction. Line 696 uses a different return
address and is deliberately rejected. A missing read, different instruction,
changed chain or inconsistent value remains unknown.

Shader indices: 0 lkt_bgra2yuva; 1 lkt_zero_flow; 2 lkt_downscale_2x;
3 lkt_features; 4 lkt_features_derivatives; 5 lkt_solver_prepare_matrices;
6 lkt_solver_box_y; 7 lkt_solver_box_x_and_Axb; 8 lkt_flow_consistency;
9 lkt_keypoints_from_flow; 10 lkt_nlreg_hegbf; 11 lkt_copy.

## Record interpretation

`NABU MTL1: pid=… status=… line=… fn_null=… index=… lib_null=… pipe_null=…`

Only status 0 makes the other fields meaningful. Status 1 means unmatched or
unreadable frame chain; 2 means code layout mismatch; 3 means unavailable
operands; 4 means inconsistent line, function or loop. No raw heap string,
object address or device identity is emitted. A nil result does not by itself
prove the shader file is missing. A Metal abort does not by itself prove the
cause of the logo stall.

CI compiles the actual helper with a synthetic user memory map, exercises both
accepted branches and shader endpoints, missing reads, broken chains, each
codeword mismatch, invalid values, bounded reads and the opt-in/process/signal
gates. Local validation remains limited to the downloaded macOS kernel and
its build evidence. The physical experiment retains the prior complete boot
materials and storage boundary; only the downloaded kernel and observation
boot argument change.
