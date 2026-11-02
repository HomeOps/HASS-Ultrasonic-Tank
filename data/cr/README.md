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

## Known events

- 2026-11-01 18:50–20:15 CR (00:50–02:15 UTC on 11-02): the surface was hidden
  behind the 0.26 m reflector. A deeper echo at ~1.49 m pulled the model from
  48 % to 30 %. When the real surface (~1.30 m) came back, the model climbed at
  its 125 L/min fill cap and reported water coming in. The pressure sensor shows
  a steady drain throughout, with no inflow.

## Collecting

`Save-WaterTankHistory` (MyHass) reads the last few hours from HA and merges them
into these files, with no duplicates. It runs hourly while the collection is on.
