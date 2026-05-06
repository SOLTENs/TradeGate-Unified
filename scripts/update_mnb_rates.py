"""Fetch USD/HUF exchange rates from the MNB SOAP API and merge into pnl/mnb_rates.json."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta

RATES_FILE = "pnl/mnb_rates.json"
SOAP_URL = "https://www.mnb.hu/arfolyamok.asmx"
SOAP_ACTION = "http://www.mnb.hu/webservices/GetExchangeRates"


def soap_body(start_date: str, end_date: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        '<soap:Body>'
        '<GetExchangeRates xmlns="http://www.mnb.hu/webservices/">'
        f'<startDate>{start_date}</startDate>'
        f'<endDate>{end_date}</endDate>'
        '<currencyNames>USD</currencyNames>'
        '</GetExchangeRates>'
        '</soap:Body>'
        '</soap:Envelope>'
    )


def fetch_rates(start_date: str, end_date: str) -> dict[str, float]:
    body = soap_body(start_date, end_date).encode("utf-8")
    req = urllib.request.Request(
        SOAP_URL,
        data=body,
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": SOAP_ACTION,
            "User-Agent": "TradeGate-PNL/1.0 (+https://github.com)",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        text = resp.read().decode("utf-8")

    m = re.search(r"<GetExchangeRatesResult>(.*?)</GetExchangeRatesResult>", text, re.DOTALL)
    if not m:
        return {}
    inner = (
        m.group(1)
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&amp;", "&")
    )

    rates: dict[str, float] = {}
    for day_match in re.finditer(r'<Day[^>]*date="([^"]+)"[^>]*>(.*?)</Day>', inner, re.DOTALL):
        d = day_match.group(1)
        block = day_match.group(2)
        rate_m = re.search(r'<Rate[^>]*curr="USD"[^>]*>([^<]+)</Rate>', block)
        if rate_m:
            r = rate_m.group(1).replace(",", ".")
            try:
                rates[d] = float(r)
            except ValueError:
                pass
    return rates


def main() -> int:
    if os.path.exists(RATES_FILE):
        with open(RATES_FILE, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"USD": {}, "_meta": {}}

    data.setdefault("USD", {})
    data.setdefault("_meta", {})

    date_from = os.environ.get("DATE_FROM", "").strip()
    date_to = os.environ.get("DATE_TO", "").strip()
    if date_from and date_to:
        try:
            start = datetime.strptime(date_from, "%Y-%m-%d").date()
            end = datetime.strptime(date_to, "%Y-%m-%d").date()
        except ValueError as e:
            print(f"Invalid date input: {e}", file=sys.stderr)
            return 1
    else:
        end = date.today()
        start = end - timedelta(days=7)

    if start > end:
        print(f"start ({start}) is after end ({end}); nothing to do.")
        return 0

    chunk = timedelta(days=300)
    cursor = start
    new_rates: dict[str, float] = {}
    while cursor <= end:
        chunk_end = min(cursor + chunk, end)
        try:
            r = fetch_rates(cursor.isoformat(), chunk_end.isoformat())
            new_rates.update(r)
            print(f"Fetched {cursor} to {chunk_end}: {len(r)} business days")
        except Exception as e:
            print(f"Failed {cursor} to {chunk_end}: {e}", file=sys.stderr)
        cursor = chunk_end + timedelta(days=1)

    before = len(data["USD"])
    data["USD"].update(new_rates)
    added = len(data["USD"]) - before
    data["_meta"]["lastUpdate"] = datetime.utcnow().isoformat() + "Z"
    data["_meta"]["count"] = len(data["USD"])

    os.makedirs(os.path.dirname(RATES_FILE), exist_ok=True)
    with open(RATES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"Saved {len(data['USD'])} total dates to {RATES_FILE} ({added} newly added)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
