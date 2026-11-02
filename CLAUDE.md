# HASS-Ultrasonic-Tank

This is a HACS custom integration. Its domain is `ultrasonic_tank`. It runs a
kinematic model over a raw ultrasonic distance sensor and outputs volume (L),
net flow (L/min), change in flow (L/min²), level (%), and low water. See
README.md for the physics.

## Rules

- **The model's input is the RAW distance sensor and nothing else.** Never feed
  it a filtered sensor, a pressure sensor, or any other source. On the
  reference tank, a hydrostatic sensor was used **for validation only**. That
  sensor will be retired.
- **`model.py` stays pure Python** (no `homeassistant` imports). It is the
  tested and replayable core. It matches the original offline reference to
  within 0.0001 % on 26k ticks.
- **Do not change model behaviour without replaying recorded raw data.** Score
  it against an independent reference. The fill cap (2.5 %/min) is a safety
  constraint: at 8 %/min the estimate latched onto the top reflector for 11 h.
- **Only ONE stationary reflector is modelled.** That covers the reference
  tank, at 0.245 m. Deeper "reflectors" seen during operation are multipath
  that depends on the water level. They were measured absent when the tank was
  empty, and the velocity cap already rejects them. Do not add bands for them.
- **A coasted estimate must never decide low water.** `LowWaterAlarm` holds its
  state while the surface is unseen. This protects against a false "empty" at
  night.
- **Cold start replays recorder history from empty.** Never seed the model from
  a short window: a few minutes of frames can be 100 % reflector echoes on an
  empty tank, or 100 % multipath on a partly full one. Both were measured.
- **Nothing is persisted on the sensor device.** State lives in HA storage
  (`.storage/ultrasonic_tank.<entry_id>`).

## Releases

release-please manages releases, the same way as HASS-Smart-Climate. Use
Conventional Commits. Never hand-edit the version in `manifest.json`.

## Tests

`pytest`. The physics tests are in `tests/test_model.py`, and the units and
config-flow tests are in `tests/test_entities.py`.
