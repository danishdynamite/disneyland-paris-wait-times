#!/usr/bin/env python3

import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

PARKS = {
    4: "Disneyland Park",
    28: "Disney Adventure World",
}

# Queue-Times exposes single-rider queues as separate ride records.  These IDs
# pair each single-rider record with its normal standby attraction.  Using IDs
# also avoids name differences such as trademark symbols and Ratatouille's
# French standby name versus English single-rider name.
SINGLE_RIDER_PARENT_IDS = {
    "7306": "2",       # Indiana Jones
    "7278": "8",       # Hyperspace Mountain
    "10849": "10848",  # Flight Force
    "10846": "10845",  # Spider-Man W.E.B.
    "7277": "32",      # Crush's Coaster
    "7279": "37",      # Ratatouille
    "7280": "34",      # RC Racer
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
    "standby_wait_minutes",
    "single_rider_wait_minutes",
    "single_rider_status",
    "last_updated",
    "ride_id",
    "single_rider_ride_id",
]
OLD_FIELDNAMES = [
    "timestamp", "date", "day", "time", "park", "land", "attraction",
    "status", "wait_minutes", "last_updated", "ride_id",
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


def migrate_old_csv_if_needed():
    """Convert the original one-row-per-queue CSV to the combined schema."""
    if not DATA_FILE.exists() or DATA_FILE.stat().st_size == 0:
        return

    with DATA_FILE.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames == FIELDNAMES:
            return
        if reader.fieldnames != OLD_FIELDNAMES:
            raise RuntimeError(f"Unexpected CSV schema: {reader.fieldnames}")
        old_rows = list(reader)

    # Index standby rows by observation + park + ride ID.
    combined = {}
    for row in old_rows:
        ride_id = row["ride_id"]
        if ride_id in SINGLE_RIDER_PARENT_IDS:
            continue
        key = (row["timestamp"], row["park"], ride_id)
        combined[key] = {
            "timestamp": row["timestamp"],
            "date": row["date"],
            "day": row["day"],
            "time": row["time"],
            "park": row["park"],
            "land": row["land"],
            "attraction": row["attraction"],
            "status": row["status"],
            "standby_wait_minutes": row["wait_minutes"],
            "single_rider_wait_minutes": "",
            "single_rider_status": "",
            "last_updated": row["last_updated"],
            "ride_id": ride_id,
            "single_rider_ride_id": "",
        }

    # Merge the separate single-rider records into their parent attraction.
    for row in old_rows:
        sr_id = row["ride_id"]
        parent_id = SINGLE_RIDER_PARENT_IDS.get(sr_id)
        if not parent_id:
            continue
        key = (row["timestamp"], row["park"], parent_id)
        parent = combined.get(key)
        if parent:
            parent["single_rider_wait_minutes"] = row["wait_minutes"]
            parent["single_rider_status"] = row["status"]
            parent["single_rider_ride_id"] = sr_id

    with DATA_FILE.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(combined.values())
    print(f"Migrated {len(old_rows)} old queue rows to {len(combined)} combined attraction rows")


def existing_keys():
    if not DATA_FILE.exists() or DATA_FILE.stat().st_size == 0:
        return set()
    keys = set()
    with DATA_FILE.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            keys.add((row.get("timestamp", ""), row.get("park", ""), row.get("ride_id", "")))
    return keys


def main():
    migrate_old_csv_if_needed()
    now = datetime.now(TIMEZONE)

    if not (8 <= now.hour <= 23):
        print(f"Skipping collection outside Paris daytime window: {now.isoformat()}")
        return 0

    minute = (now.minute // 15) * 15
    bucket = now.replace(minute=minute, second=0, microsecond=0)
    timestamp = bucket.isoformat()
    seen = existing_keys()
    rows = []

    for park_id, park_name in PARKS.items():
        payload = fetch_json(f"https://queue-times.com/parks/{park_id}/queue_times.json")
        rides = [(land, ride) for land, ride in iter_rides(payload)]
        by_id = {str(ride.get("id", "")): (land, ride) for land, ride in rides}

        # First emit normal/standby attractions.
        park_rows = {}
        for land_name, ride in rides:
            ride_id = str(ride.get("id", ""))
            if ride_id in SINGLE_RIDER_PARENT_IDS:
                continue
            key = (timestamp, park_name, ride_id)
            if key in seen:
                continue
            is_open = bool(ride.get("is_open", False))
            wait = ride.get("wait_time")
            park_rows[ride_id] = {
                "timestamp": timestamp,
                "date": bucket.strftime("%Y-%m-%d"),
                "day": bucket.strftime("%A"),
                "time": bucket.strftime("%H:%M"),
                "park": park_name,
                "land": land_name,
                "attraction": ride.get("name", ""),
                "status": "OPEN" if is_open else "CLOSED",
                "standby_wait_minutes": wait if wait is not None else "",
                "single_rider_wait_minutes": "",
                "single_rider_status": "",
                "last_updated": ride.get("last_updated", ""),
                "ride_id": ride_id,
                "single_rider_ride_id": "",
            }

        # Then merge each single-rider queue into its parent row.
        for sr_id, parent_id in SINGLE_RIDER_PARENT_IDS.items():
            sr_entry = by_id.get(sr_id)
            parent = park_rows.get(parent_id)
            if not sr_entry or not parent:
                continue
            _, sr_ride = sr_entry
            sr_wait = sr_ride.get("wait_time")
            parent["single_rider_wait_minutes"] = sr_wait if sr_wait is not None else ""
            parent["single_rider_status"] = "OPEN" if bool(sr_ride.get("is_open", False)) else "CLOSED"
            parent["single_rider_ride_id"] = sr_id

        rows.extend(park_rows.values())

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

    print(f"Added {len(rows)} attraction rows for {timestamp}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Collector failed: {exc}", file=sys.stderr)
        raise
