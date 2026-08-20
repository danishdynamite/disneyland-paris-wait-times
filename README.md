# disneyland-paris-wait-times

Automated snapshots of Disneyland Paris attraction wait times and operating status for both parks.

## What is collected

Every observation contains:

- `timestamp` — timezone-aware Paris timestamp, bucketed to 15 minutes
- `date` — `YYYY-MM-DD`
- `day` — weekday name for easy filtering
- `time` — local Paris time (`HH:MM`)
- `park` — Disneyland Park or Disney Adventure World
- `land` — themed land/area when supplied by the API
- `attraction` — attraction name
- `status` — `OPEN` or `CLOSED`
- `wait_minutes` — reported standby wait in minutes
- `last_updated` — source timestamp
- `ride_id` — Queue-Times ride identifier

The raw data is appended to [`data/wait_times.csv`](data/wait_times.csv).

## Collection schedule

GitHub Actions runs the collector every 15 minutes from 07:00 through 21:45 UTC, which corresponds to 09:00 through 23:45 in Paris while daylight-saving time is in effect. The collector has an additional local-time guard to avoid accidental overnight snapshots.

A run can also be started manually from **Actions → Collect Disneyland Paris wait times → Run workflow**.

## Google Sheets

Because this repository is public, Google Sheets can import the CSV directly with:

```text
=IMPORTDATA("https://raw.githubusercontent.com/danishdynamite/disneyland-paris-wait-times/master/data/wait_times.csv")
```

Google Sheets controls its own refresh/cache interval, so it may lag behind the repository rather than update instantly after every 15-minute commit.

## Data source

Live wait times and ride operating status come from the free Queue-Times.com real-time API:

https://queue-times.com/pages/api

**Powered by [Queue-Times.com](https://queue-times.com/).**

Queue-Times updates its real-time data approximately every five minutes. The API exposes an `is_open` flag and wait time; it does not explicitly distinguish a temporary breakdown from an attraction that is closed for the day. That distinction can be inferred later from status changes over time (for example OPEN → CLOSED → OPEN).

Park IDs used:

- `4` — Disneyland Park Paris
- `28` — Disney Adventure World Paris
