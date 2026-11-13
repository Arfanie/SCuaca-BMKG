#!/usr/bin/env python3
"""Rd Smart Display: jadwal shalat Aceh Utara (WIB) untuk 10 hari.

Sumber utama: myQuran API v3, cadangan: myQuran API v2.
Keduanya layanan pihak ketiga yang menyatakan memakai data Bimas Islam
Kemenag RI, bukan akses resmi langsung ke Kemenag.

Menulis shalat.json hanya setelah seluruh tanggal & jam tervalidasi.
Jalankan dengan `python fetch_shalat.py` (Python >=3.9).
"""
from __future__ import annotations
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Jakarta")
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "shalat.json"
DAYS = 10
V3_CITY_ID = "6512bd43d9caa6e02c990b0a82652dca"  # KAB. ACEH UTARA
V2_CITY_ID = "0111"  # KAB. ACEH UTARA
FIELDS = ("imsak", "subuh", "terbit", "dzuhur", "ashar", "maghrib", "isya")
TIME_RX = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")


def get_json(url: str) -> dict:
    request = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Rd-Smart-Display/2.3 (prayer-data; GitHub Actions)",
    })
    with urlopen(request, timeout=20) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status}: {url}")
        raw = resp.read(650001)
    if len(raw) > 650000:
        raise RuntimeError("Respons JSON terlalu besar")
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("status") is not True:
        raise ValueError("Status respons API tidak sukses")
    return data


def normalized_name(value: object) -> str:
    value = str(value or "").upper().replace("KABUPATEN", "KAB")
    return re.sub(r"[^A-Z0-9]+", " ", value).strip()


def assert_aceh_utara(location: str) -> None:
    if normalized_name(location) != "KAB ACEH UTARA":
        raise ValueError(f"Wilayah sumber salah: {location!r}")


def canonical_date(raw: object, year: int, month: int) -> str:
    if isinstance(raw, int) or (isinstance(raw, str) and raw.isdecimal()):
        day = int(raw)
        return date(year, month, day).isoformat()
    if isinstance(raw, str):
        try:
            candidate = date.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError(f"Tanggal tidak dikenali: {raw!r}") from exc
        if (candidate.year, candidate.month) != (year, month):
            raise ValueError(f"Tanggal berbeda bulan: {raw}")
        return candidate.isoformat()
    raise ValueError(f"Format tanggal tidak valid: {raw!r}")


def clean_row(row: dict, day: str) -> dict:
    output = {"date": day}
    for field in FIELDS:
        value = row.get(field)
        if not isinstance(value, str) or not TIME_RX.fullmatch(value):
            raise ValueError(f"Jam {field} salah pada {day}: {value!r}")
        output[field] = value
    if [output[k] for k in FIELDS] != sorted(output[k] for k in FIELDS):
        raise ValueError(f"Urutan jam tidak wajar pada {day}")
    return output


def v3_month(data: dict, year: int, month: int) -> dict[str, dict]:
    obj = data.get("data") or {}
    if not isinstance(obj, dict):
        raise ValueError("Respons v3.data bukan objek")
    assert_aceh_utara(obj.get("kabko", ""))
    if obj.get("id") and str(obj["id"]) != V3_CITY_ID:
        raise ValueError("ID kota v3 tidak cocok")
    if obj.get("prov") and normalized_name(obj.get("prov")) != "ACEH":
        raise ValueError("Provinsi API v3 bukan Aceh")
    schedule = obj.get("jadwal")
    if not isinstance(schedule, (dict, list)):
        raise ValueError("Tidak ada data jadwal bulanan v3")
    out = {}
    iterable = schedule.items() if isinstance(schedule, dict) else [(None, row) for row in schedule]
    for key, row in iterable:
        if not isinstance(row, dict):
            continue
        date_value = key or row.get("date") or row.get("tanggal")
        day = canonical_date(date_value, year, month)
        if day in out:
            raise ValueError("Tanggal duplikat di v3")
        out[day] = clean_row(row, day)
    return out


def v2_month(data: dict, year: int, month: int) -> dict[str, dict]:
    obj = data.get("data") or {}
    if not isinstance(obj, dict):
        raise ValueError("Respons v2.data bukan objek")
    assert_aceh_utara(obj.get("lokasi", ""))
    if obj.get("daerah") and normalized_name(obj["daerah"]) not in ("ACEH", "NANGGROE ACEH DARUSSALAM"):
        raise ValueError("Provinsi API v2 bukan Aceh")
    schedule = obj.get("jadwal")
    if not isinstance(schedule, (dict, list)):
        raise ValueError("Tidak ada data jadwal bulanan v2")
    out = {}
    iterable = schedule.items() if isinstance(schedule, dict) else [(None, row) for row in schedule]
    for key, row in iterable:
        if not isinstance(row, dict):
            continue
        date_value = row.get("date") or row.get("tanggal") or key
        day = canonical_date(date_value, year, month)
        if day in out:
            raise ValueError("Tanggal duplikat di v2")
        out[day] = clean_row(row, day)
    return out


def desired_days(today: date) -> list[str]:
    return [(today + timedelta(days=i)).isoformat() for i in range(DAYS)]


def collect(source: str, today: date) -> list[dict]:
    needed = desired_days(today)
    months = sorted({(int(d[:4]), int(d[5:7])) for d in needed})
    records = {}
    for year, month in months:
        if source == "myQuran v3":
            url = f"https://api.myquran.com/v3/sholat/jadwal/{V3_CITY_ID}/{year}-{month:02d}"
            month_records = v3_month(get_json(url), year, month)
        else:
            url = f"https://api.myquran.com/v2/sholat/jadwal/{V2_CITY_ID}/{year}/{month}"
            month_records = v2_month(get_json(url), year, month)
        records.update(month_records)
    missing = [d for d in needed if d not in records]
    if missing:
        raise RuntimeError(f"Tanggal belum ada dari {source}: {', '.join(missing)}")
    return [records[d] for d in needed]


def make_payload(rows: list[dict], source: str, now: datetime) -> dict:
    return {
        "location": "Kabupaten Aceh Utara",
        "authority": "kemenag",  # identitas sumber jadwal yg dinyatakan oleh penyedia
        "timezone": "Asia/Jakarta",
        "source": source + " (pihak ketiga, menyatakan mengacu Bimas Islam Kemenag RI)",
        "note": "Jadwal tingkat kabupaten; cocokkan dengan masjid setempat.",
        "updated_at": now.isoformat(timespec="seconds"),
        "days": rows,
    }


def main() -> int:
    now = datetime.now(TZ)
    for source in ("myQuran v3", "myQuran v2"):
        try:
            rows = collect(source, now.date())
            payload = make_payload(rows, source, now)
            temp = OUTPUT.with_suffix(".json.tmp")
            temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
            temp.replace(OUTPUT)
            print(f"[SHALAT] BERHASIL {len(rows)} hari, {source}, {rows[0]['date']} s.d. {rows[-1]['date']}")
            return 0
        except Exception as exc:
            print(f"[SHALAT] {source} gagal: {type(exc).__name__}: {exc}", file=sys.stderr)
    print("[SHALAT] Semua sumber gagal; shalat.json lama tidak diubah.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
