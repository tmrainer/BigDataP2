"""recalcula el kpi 2 en kpis_by_date; con --all, los 5 kpis.
uso: python scripts/recompute_kpis.py [--start AAAA-MM-DD] [--end AAAA-MM-DD] [--all]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from config import cassandra_session  # noqa: E402
from kpis import compute_kpis, growth_kpi, save_kpis  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=date.fromisoformat)
    ap.add_argument("--end", type=date.fromisoformat)
    ap.add_argument("--all", action="store_true", help="recalcular los 5 KPIs, no solo el crecimiento")
    args = ap.parse_args()

    s = cassandra_session()
    days = sorted(r.event_date.date() for r in s.execute("SELECT event_date FROM daily_totals"))
    days = [d for d in days if (args.start is None or d >= args.start) and (args.end is None or d <= args.end)]
    for d in days:
        kpis = compute_kpis(d) if args.all else [growth_kpi(s, d)]
        save_kpis(d, kpis)
        print(d, {k["kpi_name"]: k["kpi_value"] for k in kpis}, flush=True)
    print(f"listo: {len(days)} fechas recalculadas")


if __name__ == "__main__":
    main()
