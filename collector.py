#!/usr/bin/env python3

import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

PARKS = {
    4: "Disneyland Park",
    28: "Disney Adventure World",
}

TIMEZONE = ZoneInfo("Europe/Paris")
DATA_FILE = Path("data/wait_times.csv")
FIELDNAMES = [
    "timestamp",
    "date",
    "day",
    "time",
    "park",
    "land",
    "attraction",
    "status",
    "wait_minutes",
    "last_updated",
    "ride_id",
]


def fetch_json(url: str):
    req = Request(url, headers={"User-Agent": "disneyland-paris-wait-times/1.0"})
    with urlopen(req, timeout=30) as response:
        return json.load(response)


def iter_rides(payload):
    for land in payload.get("lands", []):
        land_name = land.get("name", "")
        for ride in land.get("rides", []):
            yield land_name, ride

    for ride in payload.get("rides", []):
        yield "", ride


def existing_keys():
    if not DATA_FILE.exists() or DATA_FILE.stat().st_size == 0:
        return set()

    keys = set()
    with DATA_FILE.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            keys.add((row.get("timestamp", ""), row.get("park", ""), row.get("ride_id", "")))
    return keys


def main():
    now = datetime.now(TIMEZONE)

    # The workflow already runs only around park hours, but this guard prevents
    # accidental manual/scheduled collection in the middle of the night.
    if not (8 <= now.hour <= 23):
        print(f"Skipping collection outside Paris daytime window: {now.isoformat()}")
        return 0

    # Bucket observations to a 15-minute timestamp so delayed/retried Actions
    # runs do not create duplicate snapshots.
    minute = (now.minute // 15) * 15
    bucket = now.replace(minute=minute, second=0, microsecond=0)
    timestamp = bucket.isoformat()

    seen = existing_keys()
    rows = []

    for park_id, park_name in PARKS.items():
        url = f"https://queue-times.com/parks/{park_id}/queue_times.json"
        payload = fetch_json(url)

        for land_name, ride in iter_rides(payload):
            ride_id = str(ride.get("id", ""))
            key = (timestamp, park_name, ride_id)
            if key in seen:
                continue

            is_open = bool(ride.get("is_open", False))
            wait = ride.get("wait_time")
            rows.append({
                "timestamp": timestamp,
                "date": bucket.strftime("%Y-%m-%d"),
                "day": bucket.strftime("%A"),
                "time": bucket.strftime("%H:%M"),
                "park": park_name,
                "land": land_name,
                "attraction": ride.get("name", ""),
                "status": "OPEN" if is_open else "CLOSED",
                "wait_minutes": wait if wait is not None else "",
                "last_updated": ride.get("last_updated", ""),
                "ride_id": ride_id,
            })

    if not rows:
        print(f"No new rows for {timestamp}")
        return 0

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_header = not DATA_FILE.exists() or DATA_FILE.stat().st_size == 0
    with DATA_FILE.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)

    print(f"Added {len(rows)} rows for {timestamp}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Collector failed: {exc}", file=sys.stderr)
        raise
