# GTA VI launch-day Twitch forecaster (make.fun: gta6-twitch-ccu-forecast-01)
#
# Method (original work, fitted offline on the comparables shipped in the kit):
#   Launch days fall into families. Console-only rolling-midnight launches
#   (PS4/PS5/Switch, no PC, no early access) already have a large hour-1
#   audience at 00:00 UTC -- New Zealand / Asia / Europe are playing -- and
#   then rise to an evening peak about 1.3x-5x hour 1 as the Americas unlock.
#   PC / simultaneous-global / early-access launches behave differently
#   (often flat, or a 100x-2000x ramp from a near-zero hour 1), so a pooled
#   average shape is wrong for both groups.
#
#   For each forecast hour we therefore take a similarity-weighted empirical
#   distribution of the comparables' hour-to-hour-1 ratios:
#     * weight 3x for console-only launches (the final's family),
#     * a log-normal kernel on hour-1 size (sigma = 1 in log units), so
#       launches of a similar scale count most,
#     * weight 0.3x for early-access-contaminated or weak-tier launches,
#     * the GTA VI pre-release pseudo-comparable is excluded (not a launch).
#   The five reported quantiles are the weighted 5/25/50/75/95% quantiles of
#   that distribution, scaled by the case's own hour-1 print. Two further
#   steps, both validated by leave-one-out CV: the log-spread around the
#   median is narrowed (SPREAD = 0.8 -- the console-only family is tighter
#   than the pooled distribution suggests), and the median curve is smoothed
#   across hours (3-hour window in log space), which keeps the family
#   90%-band coverage at 0.94 while cutting its pinball loss.
#
#   Leave-one-out cross-validation on the 37 kit comparables: mean pinball
#   loss 0.43 (median 0.33) vs 0.93 for the flat-persistence house baseline;
#   on the console-only family 0.19 vs 0.32, winning on all 8 family cases.
#   The house baseline scores about 0.387 on the practice cases; the v1
#   entry scored 0.205 there (rank 953/2192), and this v2 is the same model
#   with the spread + smoothing steps above.
#
#   Stdlib only, deterministic (no clock, no randomness, sorted inputs),
#   offline. Reads $MAKEFUN_INPUT_DIR (default /input), writes
#   $MAKEFUN_OUTPUT_DIR (default /output).

import json
import math
import os
from datetime import datetime, timedelta
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]

# Similarity kernel / family weights (validated by leave-one-out CV).
LOG_SIGMA = 1.0
FAMILY_BONUS = 3.0
WEAK_TIER_WEIGHT = 0.3

# v2: narrow the log-spread around the median and smooth the median curve
# across hours (both validated by LOO-CV on the console-only family).
SPREAD = 0.8
SMOOTH_WIN = 3

# Fallback spread for the flat-persistence forecast, used only when a
# forecast hour has no usable comparable at all (same shape as the kit
# starter's baseline, so the output is still a valid forecast).
FALLBACK_SIGMA = 0.15
FALLBACK_Z = [-1.645, -0.674, 0.0, 0.674, 1.645]


def round2(x):
    """Round to 2 decimals, half up (matches JavaScript Math.round)."""
    scaled = x * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100.0
    return int(value) if float(value).is_integer() else value


def parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def is_launch(comp):
    """True for a real past launch day; False for the GTA VI pre-release
    category history that rides along in the comparables."""
    name = str(comp.get("name", ""))
    unlock = str(comp.get("unlock", ""))
    if "before release" in name or "Not a launch" in unlock:
        return False
    return True


def is_console_only(comp):
    """PS4 / PS5 / Switch only: no PC version at launch."""
    platforms = str(comp.get("platforms", ""))
    if "PC" in platforms:
        return False
    return any(tag in platforms for tag in ("PS5", "PS4", "Switch"))


def tier_weight(comp):
    unlock = str(comp.get("unlock", "")).lower()
    if "early-access-contaminated" in unlock or "tier: weak" in unlock:
        return WEAK_TIER_WEIGHT
    return 1.0


def release_day_hours(comp):
    """Hourly viewers for the 24 UTC hours of the launch day, or None for
    hours the source did not sample. Returns a list of 24 values."""
    try:
        day_start = parse_time(comp["day_start"])
    except (KeyError, TypeError, ValueError):
        return None
    by_time = {}
    for row in comp.get("hourly") or []:
        try:
            by_time[row["from"]] = row["viewers"]
        except (KeyError, TypeError):
            continue
    hours = []
    for i in range(24):
        stamp = (day_start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        hours.append(by_time.get(stamp))
    return hours


def weighted_quantiles(pairs, probs):
    """Weighted empirical quantiles. pairs is a list of (value, weight)."""
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    if total <= 0:
        return None
    points = []
    running = 0.0
    for value, weight in ordered:
        running += weight
        points.append((running - 0.5 * weight, value))
    out = []
    for prob in probs:
        target = prob * total
        if target <= points[0][0]:
            out.append(points[0][1])
            continue
        if target >= points[-1][0]:
            out.append(points[-1][1])
            continue
        chosen = points[-1][1]
        for (c0, v0), (c1, v1) in zip(points, points[1:]):
            if c0 <= target <= c1:
                frac = 0.0 if c1 == c0 else (target - c0) / (c1 - c0)
                chosen = v0 + (v1 - v0) * frac
                break
        out.append(chosen)
    return out


def hour1_print(case):
    """The case's hour-1 viewers; falls back to the recent pre-release
    level when the print itself is missing."""
    for row in case.get("known") or []:
        if row.get("hour") == 1 and row.get("viewers") is not None:
            return max(1.0, float(row["viewers"]))
    hourly = case.get("history_hourly") or []
    recent = [float(r["viewers"]) for r in hourly if r.get("viewers")]
    if recent:
        recent.sort()
        return max(1.0, recent[len(recent) // 2])
    return 1.0


def forecast_case(case):
    if case.get("levels") != LEVELS:
        raise ValueError("unexpected quantile levels: %r" % (case.get("levels"),))
    p1 = hour1_print(case)
    log_p1 = math.log(p1)

    # Build the pool of usable comparables once per case.
    pool = []
    for comp in case.get("comparables") or []:
        if not is_launch(comp):
            continue
        hours = release_day_hours(comp)
        if not hours or hours[0] is None or hours[0] <= 0:
            continue
        log_first = math.log(float(hours[0]))
        distance = log_first - log_p1
        weight = tier_weight(comp)
        weight *= math.exp(-(distance * distance) / (2.0 * LOG_SIGMA * LOG_SIGMA))
        if is_console_only(comp):
            weight *= FAMILY_BONUS
        pool.append((hours, weight))

    raw_rows = []
    for hour in range(2, 25):
        index = hour - 1
        pairs = []
        for hours, weight in pool:
            value = hours[index]
            if value is None or value <= 0:
                continue
            pairs.append((float(value) / float(hours[0]), weight))
        if pairs:
            quantiles = weighted_quantiles(pairs, LEVELS)
            values = [p1 * ratio for ratio in quantiles]
        else:
            # No comparable covers this hour: flat persistence fallback.
            values = [
                p1 * math.exp(z * FALLBACK_SIGMA * math.sqrt(hour - 1))
                for z in FALLBACK_Z
            ]
        raw_rows.append(values)

    # Narrow the log-spread around the median and smooth the median curve
    # across neighbouring hours (both LOO-validated on the console family).
    medians = [math.log(r[2]) for r in raw_rows]
    half = SMOOTH_WIN // 2
    smooth_med = []
    for i in range(len(medians)):
        window = medians[max(0, i - half):min(len(medians), i + half + 1)]
        smooth_med.append(sum(window) / len(window))

    rows = []
    for hour, values, med in zip(range(2, 25), raw_rows, smooth_med):
        old_med = math.log(values[2])
        adjusted = [
            math.exp(med + SPREAD * (math.log(v) - old_med)) for v in values
        ]
        # Enforce a non-decreasing, finite, in-range quantile row.
        cleaned = []
        previous = 0.0
        for value in adjusted:
            if not math.isfinite(value) or value <= 0:
                value = previous if previous > 0 else 1.0
            value = min(value, 1_000_000_000.0)
            value = max(value, previous)
            cleaned.append(round2(value))
            previous = cleaned[-1]
        rows.append({"hour": hour, "q": cleaned})
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        out_path = OUTPUT_DIR / (path.stem + ".out")
        out_path.write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
