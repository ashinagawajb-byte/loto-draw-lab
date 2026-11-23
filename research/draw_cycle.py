#!/usr/bin/env python3
"""Compare independent drive hypotheses and replay visible extraction events."""

import argparse
import csv
import math
import sys

# Times are first visual confirmation of an isolated ball in the gate pocket.
# Delay is the later observed drop from the pocket into the lower guide.
# No motor RPM or dwell is inferred by this replay.
OBSERVATIONS = (
    (2151.8, 2.5, "main"),
    (2199.1, 2.8, "main"),
    (2245.8, 2.7, "main"),
    (2292.5, 2.6, "main"),
    (2339.4, 2.6, "main"),
    (2385.8, 2.7, "main"),
    (2533.9, 2.4, "bonus"),
)
FIELDS = (
    "model", "time_s", "released", "balls_left", "tier", "event",
    "pallet_target_rpm", "pallet_rpm", "ball_mean_rpm_proxy",
)


def replay(count):
    origin = OBSERVATIONS[0][0]
    for number, (time, delay, stage) in enumerate(OBSERVATIONS[:count], 1):
        yield ("c", round(time - origin, 1), number, 43 - number, stage,
               "gate_pocket_visible", "", "", "")
        yield ("c", round(time - origin + delay, 1), number, 43 - number,
               stage, "lower_guide_visible", "", "", "")


def simulate(model, count, rpm, dwell, brake, accelerate):
    """Use one shared tangential relaxation model and synthetic release times.

    Timings for A and B give both drives equivalent gate events. The legacy
    comparison models only the browser simulator's timed transitions, not Rapier.
    """
    step = 0.05
    if model == "legacy":
        # 8 s initial mix, 1.2 s approach, 0.66 s ejection, 1 s reverse mix.
        # Times start at the beginning of initial mix, after the upper chamber.
        release_ticks = [round((9.2 + i * 2.86) / step) for i in range(count)]
    else:
        interval = brake + dwell + accelerate + 5.0
        release_ticks = [round((8.0 + i * interval) / step) for i in range(count)]
    released = 0
    last_release = None
    ball_rpm = 0.0
    for tick in range(release_ticks[-1] + 1):
        time = tick * step
        event = ""
        if released < count and tick == release_ticks[released]:
            released += 1
            last_release = time
            event = "synthetic_capture"
        elapsed = None if last_release is None else time - last_release
        target = rpm
        actual = rpm
        if model == "legacy" and elapsed is not None:
            # The existing simulator reverses when its ejection animation ends.
            completed_ejections = released - int(elapsed < 0.66)
            target = actual = rpm * (-1 if completed_ejections % 2 else 1)
        if model == "b" and elapsed is not None:
            restarting = elapsed >= brake + dwell
            target = rpm if restarting else 0.0
            # A first-order ball response allows coasting with the drive stopped.
            if restarting:
                actual = rpm * min(1.0, (elapsed - brake - dwell) / accelerate)
            else:
                actual = rpm * max(0.0, 1 - elapsed / brake)
        if tick:
            ball_rpm += (0.2 * actual - ball_rpm) * -math.expm1(-step / 0.4)
        tier = ("main" if released < 7 else "bonus") if event else ""
        yield (model, round(time, 2), released, 43 - released, tier, event,
               round(target, 3), round(actual, 3), round(ball_rpm, 3))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=("legacy", "a", "b", "c", "all"),
                        default="all")
    parser.add_argument("--main-only", action="store_true")
    parser.add_argument("--rpm", type=float, default=90.0, help="Assumed pallet RPM")
    parser.add_argument("--dwell", type=float, default=2.0, help="B zero-RPM hold, seconds")
    parser.add_argument("--brake", type=float, default=1.0, help="B braking time, seconds")
    parser.add_argument("--accelerate", type=float, default=1.0, help="B acceleration time, seconds")
    args = parser.parse_args()
    if not all(math.isfinite(x) and x > 0 for x in (args.rpm, args.brake, args.accelerate)):
        parser.error("rpm, brake and accelerate must be positive finite numbers")
    if not math.isfinite(args.dwell) or args.dwell < 0:
        parser.error("dwell must be a non-negative finite number")
    count = 6 if args.main_only else 7
    models = ("legacy", "a", "b", "c") if args.model == "all" else (args.model,)
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(FIELDS)
    for model in models:
        rows = replay(count) if model == "c" else simulate(
            model, count, args.rpm, args.dwell, args.brake, args.accelerate)
        writer.writerows(rows)


if __name__ == "__main__":
    main()
