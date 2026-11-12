#!/usr/bin/env python3
"""SAKA-BMKG: sinkronisasi prakiraan resmi BMKG untuk Paloh Gadeng.
Dijalankan oleh GitHub Actions. Tidak memerlukan password Wi-Fi ESP32.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen

ADM4 = "11.08.02.2004"
URL = f"https://api.bmkg.go.id/publik/prakiraan-cuaca?adm4={ADM4}"
OUTPUT = Path(__file__).resolve().parent / "bmkg.json"

req = Request(URL, headers={"User-Agent": "SAKA-Cuaca/1.7 (BMKG public API)",
                            "Accept": "application/json"})
with urlopen(req, timeout=30) as res:
    if res.status != 200:
        raise RuntimeError(f"BMKG returned HTTP {res.status}")
    body = res.read(1_000_001)
    if len(body) > 1_000_000:
        raise RuntimeError("BMKG JSON unexpectedly large")

raw = json.loads(body)
if not isinstance(raw, dict) or not isinstance(raw.get("data"), list) or not raw["data"]:
    raise ValueError("BMKG: data[0] tidak ada")
root = raw["data"][0]
if str(root.get("lokasi", {}).get("adm4")) != ADM4:
    raise ValueError("Lokasi BMKG tidak sesuai Paloh Gadeng")
cuaca = root.get("cuaca")
if not isinstance(cuaca, list):
    raise ValueError("BMKG: cuaca bukan array")

fields = ("local_datetime", "weather_desc", "t", "hu", "ws", "wd")
days = []
count = 0
for day in cuaca:
    if not isinstance(day, list):
        continue
    cleaned = []
    for record in day:
        if not isinstance(record, dict):
            continue
        if not record.get("local_datetime"):
            continue
        cleaned.append({k: record.get(k) for k in fields})
        count += 1
        if count >= 30:
            break
    if cleaned:
        days.append(cleaned)
    if count >= 30:
        break
if not count:
    raise ValueError("BMKG tidak mengembalikan prakiraan")

result = {
    "sumber": "BMKG - Badan Meteorologi Klimatologi dan Geofisika",
    "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "data": [{"lokasi": {"adm4": ADM4}, "cuaca": days}],
}
# Write after successful validation only; failed requests keep previous GitHub JSON.
tmp = OUTPUT.with_suffix(".json.tmp")
tmp.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
tmp.replace(OUTPUT)
print(f"OK, saved {count} forecasts, bytes={OUTPUT.stat().st_size}")
