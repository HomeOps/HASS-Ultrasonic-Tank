# Ultrasonic Tank

A Home Assistant integration that turns a **raw ultrasonic distance sensor**
looking down into a gravity-drained water tank into:

| Entity | Unit | Device class |
|---|---|---|
| Volume | L | `volume_storage` |
| Net flow (+ in / − out) | L/min | `volume_flow_rate` |
| Flow change | L/min² | — (diagnostic) |
| Level | % (derived from volume) | — |
| Surface distance | m | `distance` (diagnostic) |
| Surface locked | on/off | diagnostic |
| Level uncertain | on/off | — |
| Low water | on/off | `problem` |

## Why a model instead of a filter

An ultrasonic sensor in a tank returns many echoes: the water surface, fixed
reflectors, and multipath that is always deeper than the surface. Which echo
wins changes with the water level, so **no fixed filter** (median, quantile,
jump gate) is right in every regime. On the tank this was built for, the
median filter it replaced was off by 18 % on average and up to 88 %.

The surface, however, obeys physics:

- it **falls no faster than gravity drains the tank** (Torricelli:
  `dL/dt = −2·b·√L`),
- it **rises no faster than the fastest fill**,
- its **acceleration is always small**.

Every raw frame is checked against the last valid frame's position, velocity
and timestamp. A frame that breaks the velocity or acceleration cap is a
reflection and is discarded. The published level integrates a velocity clamped
to the same envelope, so it never jumps. While the surface is not visible, the
estimate coasts along the last drain rate. It never invents a fill.

Checked against an independent hydrostatic sensor, by correlation only: it
measures pressure (hPa), not level, so it shows whether the level rises, falls
and holds when the water does, never how many % the level is off. The
benchmark charts in `docs/` show it per window; on Nov 6-8, with clean echoes,
the level ranks in the same order as pressure (rank correlation 0.98) and
moves with it in every hour.

## Requirements

- A **raw, unfiltered** distance sensor in metres, publishing every frame. A
  filtered sensor breaks the model. `esphome/water-tank-sensor.yaml` is the
  device this was built for: a MaxBotix MB7851 on an M5 Atom Lite.
- The recorder (default). On first start, the integration replays recent
  history to find the level.

## Install

HACS → Custom repositories → `https://github.com/HomeOps/HASS-Ultrasonic-Tank`
(type: Integration), install, restart, then *Settings → Devices & services →
Add integration → Ultrasonic Tank*.

## Configuration

At setup:

- the raw sensor,
- capacity (L at 100 %),
- distance when empty,
- distance at 100 %.

Everything else is in the options flow, and the defaults are the fitted values
for a 5000 L, ~2 m vertical tank:

| Option | Default | Meaning |
|---|---|---|
| Drain coefficient `b` | 0.002 | Torricelli constant, with the level as a fraction |
| Fastest fill | 2.5 %/min | Rise cap. Raising it lets the top reflector capture the estimate |
| Per-frame noise | 0.02 m | Tolerance on each frame |
| Largest change in velocity | 1.0 %/min² | Acceleration cap |
| Velocity smoothing | 2 min | |
| Stationary reflector | 0.245 m ± 0.05 | Ignored unless the tank is already near full. 0 disables it |
| Low-water threshold | 25 % | |
| Low water: surface seen within | 30 min | |
| Low water: delay | 15 min | |
| First start: history to replay | 12 h | |

**Low water is only decided while the surface has been seen recently and the
level is certain.** While the model is coasting or the level is uncertain, the
alarm holds its last state, so a guessed estimate can neither announce an empty
tank nor hide one.

**Level uncertain** turns on when, over the last 30 min, a group of echoes away
from the surface the level follows holds at least 25 % of the time. Some wrong
echoes are as steady as the water itself, and nothing in the distance stream
says which one is real, so the level is then a guess. Its attributes give the
competing echo's distance and the last level published while certain, and when.
On the reference tank, 33 of the 35 hours where the level moved differently from
the pressure sensor (Oct 25 – Nov 8) were flagged.

**State survives restarts** in Home Assistant's storage. Nothing is written to
the sensor device's flash. On first install, the model replays the last 12 h
of recorder history, starting from empty. A few minutes of frames cannot seed the model, because
they can be 100 % reflector echoes on an empty tank.

## Known limits

- **Fills lag by design.** The rise is capped at 2.5 %/min, so a 15-minute truck
  fill shows up over about 40 minutes.
- **A fast fill that ends on the stationary reflector is not accepted.** On the
  reference tank that is 92–98 %. The level stays at the pre-fill value until
  draining moves the surface off the reflector. No statistic of the echoes
  separates "full" from "reflector over a low tank". In the field data a
  reflector-only run lasted 78 min at 50 %. In that state `Surface locked` is
  **off**, so nothing downstream should trust the level.
- **The flow output is noisy during drains.** An acceleration limit on the
  published flow is planned.

## Development

```bash
pip install -r requirements_test.txt
pytest
```

`custom_components/ultrasonic_tank/model.py` is pure Python with no Home
Assistant imports, so you can replay it against exported raw history.
Releases are managed by release-please and use Conventional Commits.
