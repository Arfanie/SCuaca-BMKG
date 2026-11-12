#!/usr/bin/env python3
"""SAKA Smart Display: 10-day rolling Bimas Islam Kemenag prayer times for
Kabupaten Aceh Utara, through Sajadah's public *mirror* of official timetables.
This is not an official Kemenag API; compare against SIHAT/your local mosque.
Automatically run in GitHub Actions; failed requests leave old data intact.
"""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Jakarta")
TODAY = datetime.now(TZ).date()
DAYS = 10
BASE = "https://sajadah.org/api/v1"
OUT = Path(__file__).resolve().parent / "shalat.json"
TIME_FIELDS = {
    "imsak": "imsak", "fajr": "subuh", "sunrise": "terbit",
    "dhuhr": "dzuhur", "asr": "ashar", "maghrib": "maghrib", "isha": "isya",
}

def get_json(url, maximum=900000):
    request = Request(url, headers={
        "User-Agent": "SAKA-Smart-Display/1.9 (prayer-table-cache)",
        "Accept": "application/json",
    })
    with urlopen(request, timeout=35) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}: {url}")
        data = response.read(maximum + 1)
        if len(data) > maximum:
            raise RuntimeError("JSON melebihi batas ukuran")
    return json.loads(data)

def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()

index = get_json(BASE + "/regions.json", 900000)
regions = index.get("regions", [])
# Do not guess an ID; locate the exact district in the official mirror's index.
candidates = [r for r in regions if
    r.get("country", "").upper() == "ID" and
    r.get("authority") == "kemenag" and
    norm(r.get("province", "")) == "aceh" and
    norm(r.get("nameOfficial", r.get("name", ""))).replace("kab ", "kabupaten ") in
      ("kabupaten aceh utara", "aceh utara")]
if len(candidates) != 1:
    raise RuntimeError(f"Kabupaten Aceh Utara ambiguous/unavailable in region index (found {len(candidates)})")
region = candidates[0]
region_id = region["id"]

wanted = [(TODAY + timedelta(days=i)).isoformat() for i in range(DAYS)]
years = sorted({int(date[:4]) for date in wanted})
records = {}
for year in years:
    if year not in {int(y) for y in region.get("years", [])}:
        raise RuntimeError(f"Tabel tahun {year} belum tersedia untuk {region_id}")
    url = f"{BASE}/times/id/{quote(region_id, safe='')}/{year}.json"
    payload = get_json(url, 500000)
    if (payload.get("country") != "ID" or
        payload.get("year") != year or
        payload.get("region", {}).get("id") != region_id or
        payload.get("region", {}).get("tz") != "Asia/Jakarta" or
        payload.get("authority", {}).get("id") != "kemenag" or
        payload.get("official") is not True):
        raise ValueError("Response does not identify Kemenag Kabupaten Aceh Utara WIB")
    fields = payload.get("fields", [])
    for required in ["date", *TIME_FIELDS.keys()]:
        if required not in fields:
            raise ValueError(f"Missing field: {required}")
    for values in payload.get("days", []):
        if not isinstance(values, list) or len(values) != len(fields):
            raise ValueError("Invalid daily record")
        row = dict(zip(fields, values))
        date = row["date"]
        if date not in wanted:
            continue
        result = {"date": date}
        for source, dest in TIME_FIELDS.items():
            value = row[source]
            if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
                raise ValueError(f"Invalid {source} for {date}: {value!r}")
            result[dest] = value
        order = [result[name] for name in ("imsak", "subuh", "terbit", "dzuhur", "ashar", "maghrib", "isya")]
        if order != sorted(order):
            raise ValueError(f"Unexpected daily order {date}")
        records[date] = result
if not all(date in records for date in wanted):
    raise ValueError("Incomplete timetable; preserving previous shalat.json")

output = {
    "location": "Kabupaten Aceh Utara", "authority": "kemenag",
    "timezone": "Asia/Jakarta",
    "source": "Sajadah public mirror of Bimas Islam Kemenag RI tables",
    "mirror_region": region_id,
    "note": "Jadwal kabupaten. Cocokkan dengan jadwal masjid Paloh Gadeng.",
    "updated_at": datetime.now(TZ).isoformat(timespec="seconds"),
    "days": [records[date] for date in wanted],
}

# Atomic replace avoids corrupting output on incomplete downloads.
tmp = OUT.with_suffix(".tmp")
tmp.write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
tmp.replace(OUT)
print(f"Updated {len(wanted)} days of Kemenag Aceh Utara data from Sajadah mirror, id={region_id}")
