# Reference tank recordings (Costa Rica)

These are raw Home Assistant state histories from the reference tank: a
5000 L, ~2 m vertical tank with a MaxBotix MB7851 on an M5 Atom Lite. They will
be used to replay the model, to refine it, and as fixtures for unit tests.

## Files

There is one file per UTC day, `YYYY-MM-DD.csv`, sorted by time. Each file has
three columns:

| Column | Meaning |
|---|---|
| `TimeUtc` | When HA saw the state change (`last_changed`), ISO 8601 UTC with ms |
| `EntityId` | The HA entity |
| `State` | The state as HA stored it: a number, `on`/`off`, `unavailable` or `unknown` |

HA records only *changes*, so a value that repeats does not add a row. That is
also exactly what the integration receives, so a replay sees the same frames.

## Entities

| Entity | Role |
|---|---|
| `sensor.driveway_water_tank_sensor_tank_distance_raw` | **Model input.** Raw ultrasonic distance, m |
| `sensor.driveway_water_tank_sensor_sensor_teach_confidence` | Sensor teach confidence, % (not a usable gate) |
| `sensor.aboveground_water_tank_pressure` | **Validation only.** Hydrostatic sensor, hPa. Sparse, often `unavailable` |
| `sensor.aboveground_water_tank_level` | **Validation only.** The same pressure sensor as a %. Adjust it with 5 % → empty, 80 % → full |
| `sensor.water_tank_level` / `_volume` / `_net_flow` | What the integration published live (%, L, L/min) |
| `sensor.water_tank_surface_distance` | The integration's accepted surface, m |
| `binary_sensor.water_tank_surface_locked` / `_low_water` | The integration's lock and alarm states |

The pressure sensor is the independent reference. **It is never a model
input,** and it will be retired.

Also recorded, for validation and context only (never model inputs): the pump
switch's power (`switch.driveway_water_level_switch`, `..._electric_consumption_w/a/v/kwh`),
the pressure device's `sensor.aboveground_water_tank_distance` / `_volume` /
`_level_direction`, `binary_sensor.main_tank_water_low` / `main_water_tank_connection`,
`sensor.main_tank_water_level_sensor_distance_max`, and the sensor's
`..._overflow_risk` / `..._sensor_fault` flags. `sensor.aboveground_water_tank_level_by_distance`
is deliberately not recorded.

## Hand-entered truth: `reference-annotations.csv`

Where the pressure sensor has no data, the owner's knowledge of the tank is
recorded as a level range over a time span:

| Column | Meaning |
|---|---|
| `StartUtc`, `EndUtc` | The span, ISO 8601 UTC |
| `MinPct`, `MaxPct` | The true level was inside this range, % |
| `Source`, `Note` | Who said so and why |

The replay tool scores against it like the pressure sensor: a published level
inside the range has no error, outside it the error is the distance to the range.

| Span (CR) | Truth | Why |
|---|---|---|
| 10-28 14:22 → 10-31 22:20 | 0–5 % | Owner: empty or almost empty. The pressure sensor was `unavailable`; the truck fill at 22:20 took the raw distance from 2.46 m to 0.30 m in ~15 min |

## Long-term statistics: `statistics/`

HA's statistics for the raw sensor, the pressure level and the integration's
level, recovered from the recorder (columns `StartUtc, StatisticId, Mean, Min, Max`):

- `statistics/hour/YYYY-MM.csv`: hourly, raw since 2026-07-26 and pressure
  since 2026-07-31. HA keeps these forever.
- `statistics/5minute/YYYY-MM-DD.csv`: 5-minute, from 2026-10-23. HA purges
  these with the recorder, so these files are the only copy of the oldest days.

## Known events

- 2026-10-28 → 10-31: tank empty (see the annotation above). While empty the
  raw distance sat at ~2.46 m, well past the model's 2.05 m empty distance.
- 2026-10-31 22:20 CR: truck delivery, empty → ~97 % in about 15 minutes.

- 2026-11-01 18:50–20:15 CR (00:50–02:15 UTC on 11-02): the surface was hidden
  behind the 0.26 m reflector. A deeper echo at ~1.49 m pulled the model from
  48 % to 30 %. When the real surface (~1.30 m) came back, the model climbed at
  its 125 L/min fill cap and reported water coming in. The pressure sensor shows
  a steady drain throughout, with no inflow.

## Collecting

`Save-WaterTankHistory` (MyHass) reads the last few hours from HA and merges them
into these files, with no duplicates. It runs hourly while the collection is on.
