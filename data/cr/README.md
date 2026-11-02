# Reference tank recordings (Costa Rica)

These are raw Home Assistant state histories from the reference tank: a
5000 L, ~2 m vertical tank with a MaxBotix MB7851 on an M5 Atom Lite. They will
be used to replay the model, to refine it, and as fixtures for unit tests.

**All times are Costa Rica local time (UTC-6, no daylight saving), and all data
is split into one file per Costa Rica day, always.**

## Files

There is one file per day, `YYYY-MM-DD.csv`, sorted by time. Each file has
three columns:

| Column | Meaning |
|---|---|
| `Time` | When HA saw the state change (`last_changed`), ISO 8601 Costa Rica time with ms, e.g. `2026-10-31T22:20:00.000-06:00` |
| `EntityId` | The HA entity |
| `State` | The state as HA stored it: a number, `unavailable` or `unknown` |

HA records only *changes*, so a value that repeats does not add a row. That is
also exactly what the integration receives, so a replay sees the same frames.

## Entities

Only two instruments are recorded, nothing else:

| Entity | Role |
|---|---|
| `sensor.driveway_water_tank_sensor_tank_distance_raw` | **Model input.** Raw ultrasonic distance, m |
| `sensor.aboveground_water_tank_pressure` | **Validation only.** Hydrostatic sensor, hPa. Sparse, often `unavailable` |
| `sensor.aboveground_water_tank_level` | **Validation only.** The same pressure sensor as a %. Adjust it with 5 % → empty, 80 % → full |

The pressure sensor is the independent reference. **It is never a model
input,** and it will be retired.

## Hand-entered truth: `reference-annotations.csv`

Where the pressure sensor has no data, the owner's knowledge of the tank is
recorded as a level range over a time span:

| Column | Meaning |
|---|---|
| `Start`, `End` | The span, ISO 8601 Costa Rica time |
| `MinPct`, `MaxPct` | The true level was inside this range, % |
| `Source`, `Note` | Who said so and why |

| Span | Truth | Why |
|---|---|---|
| 10-28 14:22 → 10-31 22:20 | 0–5 % | Owner: empty or almost empty. The pressure sensor was `unavailable`; the truck fill at 22:20 took the raw distance from 2.46 m to 0.30 m in ~15 min |

## Long-term statistics: `statistics/`

HA's statistics for the raw sensor and the pressure level (the hPa entity has
no statistics in HA), recovered from the recorder. Columns `Start, StatisticId,
Mean, Min, Max`, one file per day:

- `statistics/hour/YYYY-MM-DD.csv`: hourly, raw since 2026-07-26 and pressure
  since 2026-07-31. HA keeps these forever.
- `statistics/5minute/YYYY-MM-DD.csv`: 5-minute, from 2026-10-23. HA purges
  these with the recorder, so these files are the only copy of the oldest days.

## Known events

- 10-28 14:22 → 10-31 22:20: tank empty (see the annotation above). While empty
  the raw distance sat at ~2.46 m, well past the model's 2.05 m empty distance.
- 10-31 22:20: truck delivery, empty → ~97 % in about 15 minutes.
- 11-01 18:50–20:15: the surface was hidden behind the 0.26 m reflector. A
  deeper echo at ~1.49 m pulled the model from 48 % to 30 %. When the real
  surface (~1.30 m) came back, the model climbed at its 125 L/min fill cap and
  reported water coming in. The pressure sensor shows a steady drain
  throughout, with no inflow.
- 11-02 05:15: city delivery, ~41 % → full by 06:00.

## Collecting

`Save-WaterTankHistory` (MyHass) reads the last few hours from HA and merges them
into these files, with no duplicates. It runs hourly while the collection is on.
