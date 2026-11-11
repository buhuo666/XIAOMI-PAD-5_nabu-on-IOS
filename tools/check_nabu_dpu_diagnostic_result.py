#!/usr/bin/env python3
"""Verify a fresh paired-host DPU diagnostic without claiming visual acceptance."""
import argparse
import json
from pathlib import Path

GOP = 0x9C000000


def verify(data):
    issues = []

    def require(value, message):
        if not value:
            issues.append(message)

    request = data.get("request", {})
    action, identifier = request.get("Action"), request.get("ID")
    polled, resume_irq = action == "DpuActivateGopPolled", action == "DpuResumeIrq"
    activate, flip = action in ("DpuActivateGop", "DpuActivateGopPolled"), action == "DpuFlipGop"
    halt = action == "DpuHaltResume"
    dpu = data.get("dpu", {})
    result = dpu.get("result", {})
    require(action in ("DpuSnapshot", "DpuHaltResume", "DpuActivateGop", "DpuActivateGopPolled", "DpuResumeIrq", "DpuFlipGop"),
            "Unexpected request action")
    require(identifier and identifier == dpu.get("request_id") == result.get("request_id"),
            "Stale or missing request identity")
    require(dpu.get("uid") == 0, "Diagnostic helper did not run as root")
    require(dpu.get("available") is True and dpu.get("submit_status") == 0,
            "Diagnostic request not accepted")
    require(not dpu.get("timeout") and dpu.get("state") == "diagnostic-complete",
            "Diagnostic not completed")
    require(result.get("status") == 0, "Hardware diagnostic returned failure")
    require(result.get("halt_resume_requested") is halt and
            result.get("activate_gop_requested") is activate and
            result.get("flip_gop_requested", False) is flip, "Wrong diagnostic mutation flags")
    require(result.get("activate_gop_polled_requested", False) is polled and
            result.get("resume_irq_requested", False) is resume_irq, "Wrong IRQ isolation request flags")
    if polled or resume_irq:
        require(result.get("irq_qualification_complete") is resume_irq, "IRQ qualification state differs")
    if polled:
        enabled = result.get("after", {}).get("irq_enable")
        require(enabled is not None and enabled & 0x3c000000 == 0, "Polled control did not keep display IRQs masked")
    require(result.get("smmu_changed") is activate and
            result.get("scanout_address_changed") is flip, "Unexpected context/address mutation")
    require(result.get("gop_writer_frozen") is False, "GOP writer remains frozen")
    require(result.get("finished_us", 0) > result.get("started_us", 0) > 0,
            "Invalid execution interval")
    for phase in ("before", "after"):
        for name in ("vig0_address", "vig1_address"):
            require(result.get(phase, {}).get(name) == GOP, f"{phase}/{name}: GOP address differs")
    if not flip:
        require(result.get("sample_us", 0) >= 50000, "Counter observation interval too short")
        for name in ("master_frame_delta", "slave_frame_delta"):
            require(0 < result.get(name, 0) < 0x80000000, f"{name}: no forward progress")
    if halt or activate or flip or resume_irq:
        for name in ("halt_request", "halt_ack"):
            value = result.get("after", {}).get(name)
            require(value is not None and value & 0x11 == 0, f"{name}: halt not cleared")
        for name in ("vig0_clock", "vig1_clock"):
            before, after = result.get("before", {}).get(name), result.get("after", {}).get(name)
            require(before is not None and after is not None and (before & 1) == (after & 1),
                    f"{name}: force bit not restored")
    if halt or (activate and not polled) or flip or resume_irq:
        require(result.get("irq_fault") == 0, "IRQ fault observed")
        for name in ("irq_count_delta", "irq_frame_sequence_delta", "master_vsync_delta", "slave_vsync_delta"):
            require(result.get(name, 0) > 0, f"{name}: no new postresume hardware events")
        for name in ("master_underrun_delta", "slave_underrun_delta"):
            require(result.get(name) == 0, f"{name}: scanout underrun observed")
    if halt:
        if result.get("halt_audit_requested"):
            require(result.get("halt_audit_prepare_status") == 0 and result.get("halt_audit_status") == 0,
                    "Read-only halted audit failed")
            require(result.get("halt_audit_sctlr") == 0xE0 and result.get("smmu_programmed") is False,
                    "Read-only control did not retain inherited bypass")
            require(result.get("halt_audit_us", 0) > 0, "Read-only audit timing is missing")
        for name in ("irq_start_status", "irq_pause_fault", "halt_status", "resume_status", "irq_resume_fault"):
            require(result.get(name) == 0, f"{name}: missing or nonzero")
        for name in ("halted_request", "halted_ack"):
            require(result.get(name, 0) & 0x11 == 0x11, f"{name}: both XIN ACKs not observed")
    if activate:
        require(result.get("activate_status") == 0 and result.get("irq_start_status") == 0,
                "Identity activation or IRQ start failed")
        pixels_before, pixels_after = result.get("gop_pixels_before", {}), result.get("gop_pixels_after", {})
        require(pixels_before.get("sampled_words") == 8000 and pixels_after.get("sampled_words") == 8000,
                "Missing original GOP page content samples")
        require(pixels_before.get("hash") is not None and pixels_before.get("hash") == pixels_after.get("hash"),
                "CPU-visible GOP contents changed while the writer was frozen")
    if resume_irq:
        require(result.get("irq_resume_fault") == 0, "Independent IRQ rearm failed")
    if flip:
        for name in ("test_flip_status", "gop_flip_status", "retire_status"):
            require(result.get(name) == 0, f"{name}: missing or nonzero")
        first, returned = result.get("test_acceptance", {}), result.get("gop_acceptance", {})
        require(first.get("accepted") is True and returned.get("accepted") is True,
                "Both CTL/dual-interface acceptances are required")
        iova = first.get("current_iova", 0)
        require(0x20000000 <= iova < 0x60000000 and first.get("retired_iova") == GOP,
                "Test acceptance does not replace GOP with an owned slot")
        require(returned.get("current_iova") == GOP and returned.get("retired_iova") == iova,
                "Return acceptance does not retire the test slot")
        sequence = first.get("sequence", 0)
        require(sequence > 0 and sequence == result.get("test_scan_sequence") and
                returned.get("sequence", 0) > sequence and returned.get("retired_sequence") == sequence,
                "Scan generations did not advance through the roundtrip")
        require(returned.get("observed_us", 0) > first.get("observed_us", 0),
                "Return acceptance predates the test acceptance")
        require(result.get("test_mapping_token", 0) > 0 and result.get("test_hold_us", 0) >= 3000000,
                "Missing mapped generation or visible hold interval")
        require(result.get("test_uses_original_surface_pages") is True and result.get("gpu_rendered") is False,
                "Wrong test surface provenance")
        require(result.get("test_surface_released") is True, "Test surface/lease not released after retirement")
    mapper = result.get("mapper")
    if activate or flip or resume_irq or mapper is not None:
        m = mapper or {}
        require(result.get("smmu_programmed") is True and m.get("status") == 0,
                "No successful active mapper readback")
        require(m.get("poisoned") is False, "Mapper has a recorded failure")
        for name in ("active", "context_matches", "routes_unchanged", "gop_identity"):
            require(m.get(name) is True, f"Mapper {name} missing or false")
        require(m.get("identity_pages") == 4000, "Whole GOP identity map not verified")
        root = m.get("root_physical", 0)
        require(0 < root < (1 << 40) and root % 4096 == 0, "Invalid table root")
        # Foundation can serialize registers with bit 63 set as signed integers.
        ttbr0 = m.get("ttbr0", 0) & ((1 << 64) - 1)
        ttbr1 = m.get("ttbr1", 0) & ((1 << 64) - 1)
        require(ttbr0 & ((1 << 40) - 4096) == root, "Actual TTBR0 differs")
        require(ttbr0 >> 48 == m.get("asid"), "Actual TTBR ASID differs")
        require(ttbr1 == m.get("asid", 0) << 48, "Unexpected TTBR1")
        require(m.get("sctlr", 0) & 0x61 == 0x21, "MMU/CFRE/CFIE readback differs")
        require(m.get("mair0") == 0xFF44 and m.get("mair1") == 0, "Memory attributes differ")
        require(m.get("actlr") == 0x103 and m.get("tcr", 0) & 0x3f00 == 0x400,
                "Nabu display upstream table-walk profile differs")
        require(m.get("global_fsr") == 0 and m.get("fsr", 0xC00001FE) & 0xC00001FE == 0,
                "Actual SMMU fault observed")
        require(m.get("tlb_status", 1) & 1 == 0, "TLB synchronization still busy")
    return {"passed": not issues, "issues": issues, "action": action, "request_id": identifier,
            "hardware_result": result, "cb2_takeover_verified": activate and not polled and not issues,
            "polled_takeover_verified": polled and not issues,
            "independent_irq_resume_verified": resume_irq and not issues,
            "page_flip_hardware_verified": flip and not issues, "visual_verified": False,
            "sustained_high_refresh_verified": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = verify(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    raise SystemExit(0 if report["passed"] else 1)
