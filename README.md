# GTA VI launch-day Twitch forecaster

Entry for make.fun `gta6-twitch-ccu-forecast-01`: a Python 3.13 stdlib-only
program (`main.py`) that reads one case (`/input/<id>.in`) and writes five
quantiles of Twitch's hourly viewers for each of hours 2-24 of GTA VI's
release day (2026-11-19 UTC).

## Method

Launch days fall into families. Console-only rolling-midnight launches
already have a large hour-1 audience at 00:00 UTC and rise to an evening
peak ~1.3x-5x hour 1 as the Americas unlock; PC / simultaneous-global /
early-access launches behave differently (flat, or a 100x-2000x ramp from a
near-zero hour 1). So for each forecast hour the program takes a
similarity-weighted empirical distribution of the comparables'
hour-to-hour-1 ratios (3x weight for console-only launches, a log-normal
kernel on hour-1 size with sigma 1, 0.3x for early-access-contaminated or
weak-tier launches; the GTA VI pre-release pseudo-comparable is excluded)
and reports its weighted 5/25/50/75/95% quantiles, scaled by the case's own
hour-1 print.

## Validation

Leave-one-out cross-validation on the 37 comparables shipped in the kit:
mean pinball loss **0.42** (median 0.32), vs **0.93** for the flat-persistence
house baseline; on the console-only family **0.21** vs **0.32**. The house
baseline scores about 0.387 on the practice cases.

## Run

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=output python3 main.py
```

Deterministic, offline, no network, no model calls. Runtime is well under
the 8-second limit per case.
