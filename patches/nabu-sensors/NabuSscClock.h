// SPDX-License-Identifier: BSD-2-Clause-Patent
// Local clock correlation only. SSC's epoch must be established separately for
// this AP/SLPI session; neither a received sample nor a previous boot proves it.
// See analysis/nabu-ssc-clock-control-20261110.md. No heap, floating point, or I/O.
#pragma once
#include <stdint.h>

namespace NabuSsc {
constexpr uint64_t ClockFrequency = UINT64_C(19200000);
// Values also describe the explicit nabu-ssc-clock boot policy. Unknown is the
// production default until retained device evidence establishes the relation.
enum class ClockEpoch : unsigned { Unknown = 0, Virtual = 1, Physical = 2 };
enum class ClockUpdate : unsigned {
    Initial, Refreshed, Discontinuity, PolicyPending, WideBracket,
    BadFrequency, BadOrder, ArithmeticOverflow
};
enum class ClockSampleResult : unsigned {
    Converted, EpochPending, ObservationPending, AgePolicyPending,
    BeforeSegment, Future, TooOld, NonMonotonic, ArithmeticOverflow
};
struct ClockBracket {
    uint64_t mach_before = 0, physical_ticks = 0, virtual_ticks = 0;
    uint64_t frequency = 0, mach_after = 0;
};
struct ClockCursor {
    bool seen = false;
    uint64_t generation = 0, ssc_ticks = 0, mach_ticks = 0;
};
struct ClockStamp {
    uint64_t mach_ticks = 0, earliest_mach = 0, latest_mach = 0;
    uint64_t age_ticks = 0, generation = 0;
};
struct ClockOffsetRange { int64_t low = 0, high = 0; };

namespace ClockDetail {
constexpr uint64_t Sign = UINT64_C(1) << 63;
inline bool difference(uint64_t a, uint64_t b, int64_t &out) {
    if (a >= b) {
        if (a - b > uint64_t(INT64_MAX)) return false;
        out = int64_t(a - b);
    } else {
        uint64_t n = b - a;
        if (n > Sign) return false;
        out = n == Sign ? INT64_MIN : -int64_t(n);
    }
    return true;
}
inline bool add(uint64_t value, int64_t offset, uint64_t &out) {
    if (offset >= 0) {
        if (uint64_t(offset) > UINT64_MAX - value) return false;
        out = value + uint64_t(offset);
    } else {
        const uint64_t magnitude = UINT64_C(0) - uint64_t(offset);
        if (value < magnitude) return false;
        out = value - magnitude;
    }
    return true;
}
inline uint64_t ordered(int64_t n) { return uint64_t(n) ^ Sign; }
inline int64_t from_ordered(uint64_t n) {
    return n >= Sign ? int64_t(n - Sign) : INT64_MIN + int64_t(n);
}
inline int64_t midpoint(ClockOffsetRange r) {
    uint64_t low = ordered(r.low), high = ordered(r.high);
    return from_ordered(low + (high - low) / 2);
}
inline bool range(const ClockBracket &b, uint64_t counter, uint64_t uncertainty,
                  ClockOffsetRange &r) {
    if (!difference(b.mach_before, counter, r.low) ||
        !difference(b.mach_after, counter, r.high)) return false;
    const uint64_t low = ordered(r.low), high = ordered(r.high);
    if (uncertainty > low || uncertainty > UINT64_MAX - high) return false;
    r.low = from_ordered(low - uncertainty);
    r.high = from_ordered(high + uncertainty);
    return true;
}
inline bool intersect(ClockOffsetRange a, ClockOffsetRange b, ClockOffsetRange &out) {
    out.low = a.low > b.low ? a.low : b.low;
    out.high = a.high < b.high ? a.high : b.high;
    return out.low <= out.high;
}
} // namespace ClockDetail

// Exact floor conversions at 19.2 MHz, without overflowing an intermediate
// ticks*1e9. False means the mathematical nanosecond result does not fit u64.
inline bool clock_ticks_to_nanoseconds(uint64_t ticks, uint64_t &nanoseconds) {
    const uint64_t whole = ticks / 12, fraction = (ticks % 12) * 625 / 12;
    if (whole > (UINT64_MAX - fraction) / 625) return false;
    nanoseconds = whole * 625 + fraction;
    return true;
}
inline uint64_t clock_nanoseconds_to_ticks(uint64_t nanoseconds) {
    return (nanoseconds / 625) * 12 + (nanoseconds % 625) * 12 / 625;
}

// All methods are called by one serialized worker. Capture ordered local reads:
// Mach-before, ISB/CNTPCT, ISB/CNTVCT, CNTFRQ, Mach-after. The bracket bounds the
// local clock offset; SSC data is deliberately absent from observe().
class ClockMapping {
    ClockBracket latest_{};
    ClockOffsetRange physical_{}, virtual_{};
    uint64_t first_physical_ = 0, first_virtual_ = 0, generation_ = 1;
    ClockEpoch epoch_ = ClockEpoch::Unknown;
    bool have_bracket_ = false, observation_ready_ = false, exhausted_ = false;

    void install(const ClockBracket &b, ClockOffsetRange physical, ClockOffsetRange virt) {
        latest_ = b; physical_ = physical; virtual_ = virt;
        first_physical_ = b.physical_ticks; first_virtual_ = b.virtual_ticks;
        have_bracket_ = observation_ready_ = true;
    }
public:
    uint64_t generation() const { return generation_; }
    ClockEpoch epoch() const { return epoch_; }
    bool has_bracket() const { return have_bracket_; }
    bool observation_ready() const { return have_bracket_ && observation_ready_; }
    bool valid() const { return have_bracket_ && observation_ready_ && epoch_ != ClockEpoch::Unknown; }
    const ClockBracket &latest() const { return latest_; }
    ClockOffsetRange offset(ClockEpoch source) const {
        return source == ClockEpoch::Physical ? physical_ : virtual_;
    }
    uint64_t segment_start(ClockEpoch source) const {
        return source == ClockEpoch::Physical ? first_physical_ : first_virtual_;
    }

    // Call on an observed AP sleep, SLPI restart, or lost transport continuity.
    // Cursors retain the last published Mach time across this invalidation.
    void invalidate() {
        epoch_ = ClockEpoch::Unknown; have_bracket_ = observation_ready_ = false;
        if (generation_ == UINT64_MAX) exhausted_ = true;
        else ++generation_;
    }

    // max_bracket_ticks and read_uncertainty_ticks are caller policy, not device
    // facts. Zero max means pending. A nonzero uncertainty expands each local
    // interval before intersection; it must have independent measurement support.
    // Contradictory intervals indicate a discontinuity, not its physical cause.
    ClockUpdate observe(const ClockBracket &b, uint64_t max_bracket_ticks,
                        uint64_t read_uncertainty_ticks = 0) {
        observation_ready_ = false;
        if (!max_bracket_ticks || exhausted_) return ClockUpdate::PolicyPending;
        if (b.frequency != ClockFrequency) { invalidate(); return ClockUpdate::BadFrequency; }
        if (b.mach_after < b.mach_before) { invalidate(); return ClockUpdate::BadOrder; }
        if (b.mach_after - b.mach_before > max_bracket_ticks) return ClockUpdate::WideBracket;
        ClockOffsetRange physical, virt;
        if (!ClockDetail::range(b, b.physical_ticks, read_uncertainty_ticks, physical) ||
            !ClockDetail::range(b, b.virtual_ticks, read_uncertainty_ticks, virt)) {
            invalidate(); return ClockUpdate::ArithmeticOverflow;
        }
        if (!have_bracket_) { install(b, physical, virt); return ClockUpdate::Initial; }
        ClockOffsetRange p_common, v_common;
        const bool backwards = b.mach_before < latest_.mach_after ||
            b.physical_ticks < latest_.physical_ticks || b.virtual_ticks < latest_.virtual_ticks;
        if (backwards || !ClockDetail::intersect(physical_, physical, p_common) ||
            !ClockDetail::intersect(virtual_, virt, v_common)) {
            invalidate();
            if (exhausted_) return ClockUpdate::PolicyPending;
            install(b, physical, virt);
            return ClockUpdate::Discontinuity;
        }
        physical_ = p_common; virtual_ = v_common; latest_ = b;
        observation_ready_ = true;
        return ClockUpdate::Refreshed;
    }

    // This is an explicit trust boundary: the caller supplies evidence that SSC
    // timestamps use this counter's epoch in THIS generation. Local brackets,
    // a first sample's receipt time, a previous boot, or stale boot policy after
    // a discontinuity are insufficient. No automatic epoch detection is done.
    bool confirm_epoch(uint64_t observed_generation, ClockEpoch source) {
        if (exhausted_ || !have_bracket_ || !observation_ready_ || observed_generation != generation_ ||
            (source != ClockEpoch::Physical && source != ClockEpoch::Virtual)) return false;
        if (epoch_ != ClockEpoch::Unknown && epoch_ != source) return false;
        epoch_ = source;
        return true;
    }

    // Each sensor owns a cursor. A positive age bound is explicit policy;
    // UINT64_MAX permits old cached data only inside the current valid segment.
    // No old/batched sample is projected through an unknown sleep boundary.
    ClockSampleResult convert(uint64_t ssc_ticks, ClockCursor &cursor,
                              uint64_t max_age_ticks, ClockStamp &stamp) const {
        stamp = ClockStamp{};
        if (!have_bracket_ || epoch_ == ClockEpoch::Unknown) return ClockSampleResult::EpochPending;
        if (!observation_ready_) return ClockSampleResult::ObservationPending;
        if (!max_age_ticks) return ClockSampleResult::AgePolicyPending;
        const uint64_t start = segment_start(epoch_);
        const uint64_t now = epoch_ == ClockEpoch::Physical ? latest_.physical_ticks : latest_.virtual_ticks;
        if (ssc_ticks < start) return ClockSampleResult::BeforeSegment;
        if (ssc_ticks > now) return ClockSampleResult::Future;
        const uint64_t age = now - ssc_ticks;
        if (age > max_age_ticks) return ClockSampleResult::TooOld;
        if (cursor.seen && cursor.generation == generation_ && ssc_ticks <= cursor.ssc_ticks)
            return ClockSampleResult::NonMonotonic;
        const ClockOffsetRange r = offset(epoch_);
        ClockStamp result;
        if (!ClockDetail::add(ssc_ticks, r.low, result.earliest_mach) ||
            !ClockDetail::add(ssc_ticks, r.high, result.latest_mach) ||
            !ClockDetail::add(ssc_ticks, ClockDetail::midpoint(r), result.mach_ticks))
            return ClockSampleResult::ArithmeticOverflow;
        if (cursor.seen && result.mach_ticks <= cursor.mach_ticks) return ClockSampleResult::NonMonotonic;
        result.age_ticks = age; result.generation = generation_;
        cursor.seen = true; cursor.generation = generation_;
        cursor.ssc_ticks = ssc_ticks; cursor.mach_ticks = result.mach_ticks;
        stamp = result;
        return ClockSampleResult::Converted;
    }
};

struct ClockQualificationPolicy {
    uint32_t required_stream_mask = 0, minimum_samples = 0;
    uint64_t minimum_span_ticks = 0, max_age_ticks = 0, max_sample_gap_ticks = 0;
};
enum class ClockQualificationResult : unsigned {
    PolicyPending, ObservationPending, IgnoredStream, BeforeSegment, Future,
    TooOld, NonMonotonic, SampleGap, Collecting, Qualified, GenerationChanged
};

// First-session corroboration of a domain already selected from hardware/API
// evidence. This checks SSC against that domain without fitting any offset.
// One instance can be armed once. A generation change permanently retires it;
// do not construct another one on a wake merely to reapply the same boot policy.
class ClockQualification {
public:
    enum : unsigned { MaxStreams = 8 };
private:
    struct Progress {
        uint64_t source_low = 0, source_high = 0;
        uint64_t first_ssc = 0, last_ssc = 0, first_counter = 0, last_counter = 0;
        uint32_t count = 0;
    } streams_[MaxStreams]{};
    ClockQualificationPolicy policy_{};
    ClockEpoch candidate_ = ClockEpoch::Unknown;
    uint64_t generation_ = 0;
    bool attempted_ = false, armed_ = false, qualified_ = false, retired_ = false;

    ClockQualificationResult reject(unsigned stream, ClockQualificationResult result) {
        streams_[stream] = Progress{};
        return result;
    }
public:
    bool arm(const ClockMapping &mapping, ClockEpoch candidate, ClockQualificationPolicy policy) {
        if (attempted_) return false;
        attempted_ = true;
        if ((candidate != ClockEpoch::Virtual && candidate != ClockEpoch::Physical) ||
            !policy.required_stream_mask || (policy.required_stream_mask >> MaxStreams) ||
            policy.minimum_samples < 2 || !policy.minimum_span_ticks || !policy.max_age_ticks ||
            policy.max_age_ticks == UINT64_MAX || !policy.max_sample_gap_ticks ||
            mapping.epoch() != ClockEpoch::Unknown) return false;
        policy_ = policy; candidate_ = candidate; generation_ = mapping.generation();
        armed_ = true;
        return true;
    }
    bool qualified(const ClockMapping &mapping) const {
        return qualified_ && !retired_ && mapping.generation() == generation_ &&
            mapping.epoch() == candidate_ && mapping.valid();
    }
    bool retired() const { return retired_; }
    uint64_t generation() const { return generation_; }
    uint32_t samples(unsigned stream) const { return stream < MaxStreams ? streams_[stream].count : 0; }

    // stream_id identifies a required continuous sensor; source_low/high bind
    // the observations to one SUID so different instances cannot combine proof.
    // On-change/configuration events must pass continuous=false and never count.
    ClockQualificationResult consider(ClockMapping &mapping, unsigned stream_id,
                                      bool continuous, uint64_t ssc_ticks,
                                      uint64_t source_low, uint64_t source_high) {
        if (!armed_) return ClockQualificationResult::PolicyPending;
        if (retired_ || mapping.generation() != generation_) {
            retired_ = true; qualified_ = false;
            return ClockQualificationResult::GenerationChanged;
        }
        if (!mapping.observation_ready()) return ClockQualificationResult::ObservationPending;
        if (qualified_) return ClockQualificationResult::Qualified;
        if (!continuous || stream_id >= MaxStreams || !(policy_.required_stream_mask & (1u << stream_id)))
            return ClockQualificationResult::IgnoredStream;
        const auto &bracket = mapping.latest();
        const uint64_t now = candidate_ == ClockEpoch::Physical ? bracket.physical_ticks : bracket.virtual_ticks;
        if (ssc_ticks < mapping.segment_start(candidate_))
            return reject(stream_id, ClockQualificationResult::BeforeSegment);
        if (ssc_ticks > now) return reject(stream_id, ClockQualificationResult::Future);
        if (now - ssc_ticks > policy_.max_age_ticks) return reject(stream_id, ClockQualificationResult::TooOld);
        Progress &p = streams_[stream_id];
        if (p.count && (p.source_low != source_low || p.source_high != source_high)) p = Progress{};
        if (p.count && ssc_ticks <= p.last_ssc)
            return reject(stream_id, ClockQualificationResult::NonMonotonic);
        if (p.count && ssc_ticks - p.last_ssc > policy_.max_sample_gap_ticks)
            return reject(stream_id, ClockQualificationResult::SampleGap);
        if (!p.count) {
            p.source_low = source_low; p.source_high = source_high;
            p.first_ssc = ssc_ticks; p.first_counter = now;
        }
        p.last_ssc = ssc_ticks; p.last_counter = now;
        if (p.count < policy_.minimum_samples) ++p.count;
        for (unsigned i = 0; i != MaxStreams; ++i) {
            if (!(policy_.required_stream_mask & (1u << i))) continue;
            const Progress &s = streams_[i];
            if (s.count < policy_.minimum_samples || s.last_ssc - s.first_ssc < policy_.minimum_span_ticks ||
                s.last_counter - s.first_counter < policy_.minimum_span_ticks || s.last_ssc > now ||
                now - s.last_ssc > policy_.max_age_ticks) return ClockQualificationResult::Collecting;
        }
        // The only confirmation path: no source/offset guess from sample arrival.
        if (!mapping.confirm_epoch(generation_, candidate_)) return ClockQualificationResult::ObservationPending;
        qualified_ = true;
        return ClockQualificationResult::Qualified;
    }
};
} // namespace NabuSsc
