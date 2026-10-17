# EMAY EMO-80 Pulse Oximeter for Home Assistant

A custom integration that downloads the **stored overnight recordings** from an
[EMAY EMO-80](https://www.emaycare.com/) sleep oxygen monitor straight into Home
Assistant over Bluetooth. You don't need the phone app or an ESP32.

> **Not a medical device.** This is a hobby project. The readings and the
> estimated ODI are for personal interest only and must not be used for
> diagnosis or treatment. Talk to your doctor about your results.

## What you get

| Entity | What it shows |
|---|---|
| `button.emo_80_download_all` | Downloads every session stored on the oximeter |
| `sensor.emo_80_spo2` | Typical SpO₂ of the latest session, plus hourly history for every downloaded night |
| `sensor.emo_80_pulse_rate` | Typical pulse of the latest session, plus hourly history |
| `sensor.emo_80_estimated_odi` | Estimated Oxygen Desaturation Index (4% drops per hour; the 3% value is an attribute) |
| `sensor.emo_80_desat_events` | Number of desaturation events in the latest session, plus hourly history |
| `sensor.emo_80_measurements` | Details of the latest session (start time, duration, raw points) |
| `sensor.emo_80_download_summary` | How many sessions the last download found |
| `sensor.emo_80_download_log` | Transfer log for troubleshooting (disabled by default) |

The download back-fills Home Assistant's long-term statistics, so the history
graphs show each whole night at the time it was recorded, not just the
moment you pressed the button.

## Requirements

- Home Assistant with a working **connectable** Bluetooth adapter. That can
  be the host's built-in Bluetooth (a Raspberry Pi works) or an active
  ESPHome Bluetooth proxy.
- The oximeter within range while it downloads. A weak signal works, but
  the download is slower: a 9-hour night takes about 6–7 minutes at around
  -90 dBm.

## Installation

### HACS (recommended)
1. In HACS, open the menu → **Custom repositories**.
2. Add `https://github.com/gjg4000-debug/ha-emay-emo80`, category **Integration**.
3. Install **EMAY EMO-80 Pulse Oximeter**, then restart Home Assistant.

### Manual
Copy `custom_components/emay_emo80` into your `config/custom_components/`
folder and restart Home Assistant.

## Setup

1. Find the oximeter's Bluetooth MAC address. Wake it up, then check
   **Settings → System → Hardware → Bluetooth → Advertisement monitor**, or use
   a BLE scanner app such as nRF Connect.
2. Go to **Settings → Devices & services → Add integration → EMAY EMO-80** and
   enter the address.

## Usage

1. Wear the oximeter overnight as usual.
2. In the morning, wake it (put your finger in or press its button) so it
   advertises, then press **EMO-80 Download All**.
3. The screen on the device shows that it's uploading. When it's finished,
   the sensors update.

Each download pulls **every** stored session. Nothing is deleted from the device.

To download automatically, call `button.press` on
`button.emo_80_download_all` from an automation, for example every morning.

## Troubleshooting

- **"not currently advertising / not seen by any Bluetooth adapter"**: the
  oximeter is asleep or out of range. Wake it and try again within a minute.
- **The download is very slow**: move the oximeter closer to the adapter or proxy.
- Turn on `sensor.emo_80_download_log` to see the full transfer log.
- ESP32 note: some ESP32 Bluetooth stacks failed to connect to this device
  (a 20 s timeout, then status 133). Host Bluetooth via BlueZ works reliably.

## How it works

The EMO-80 uses EMAY's "MrdStoreBlue" frame protocol over a custom GATT service
(`0000ff12-…`). This protocol was worked out independently, for interoperability
with hardware the user owns. The integration sets the device clock, lists the
stored sessions, then pulls each one page by page and decodes the SpO₂ and
pulse samples. The ODI is estimated from the full per-sample SpO₂ stream with
a simple rolling-baseline method (see `odi.py`). It is not a certified
clinical algorithm.

## Credits & license

MIT licensed. Not affiliated with or endorsed by EMAY.
