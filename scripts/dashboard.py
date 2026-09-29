"""Local 6-panel dashboard built from data/logs.jsonl and config/dashboard.yaml.

Usage:
    python scripts/dashboard.py                    # serve http://127.0.0.1:8501 (auto-refresh 30s)
    python scripts/dashboard.py --html out.html    # write a single static snapshot

Only the standard library and PyYAML are used. Panel ids, units, the 60-minute range and the
threshold lines come from config/dashboard.yaml, so the picture always matches the contract.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = REPO_ROOT / "data" / "logs.jsonl"
CONFIG_PATH = REPO_ROOT / "config" / "dashboard.yaml"

# Categorical slots 1-4 of the reference palette (light / dark), assigned in fixed order.
SERIES_COLORS = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"]

W, H = 560, 230
ML, MR, MT, MB = 52, 14, 14, 30


# ---------------------------------------------------------------- data
def load_records(now: datetime, minutes: int) -> list[dict]:
    if not LOG_PATH.exists():
        return []
    start = now - timedelta(minutes=minutes)
    out: list[dict] = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            ts = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
        except (ValueError, KeyError, TypeError):
            continue
        if start <= ts <= now:
            rec["_min"] = (now - ts).total_seconds() / 60  # minutes ago, 0 = now
            out.append(rec)
    return out


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100
    lo, hi = math.floor(k), math.ceil(k)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def by_minute(records: list[dict], minutes: int) -> dict[int, list[dict]]:
    buckets: dict[int, list[dict]] = defaultdict(list)
    for rec in records:
        buckets[min(minutes - 1, int(rec["_min"]))].append(rec)
    return buckets


# ---------------------------------------------------------------- svg helpers
def nice_max(value: float) -> float:
    if value <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 2.5, 5, 10):
        if value <= step * exp:
            return step * exp
    return 10 * exp


def fmt(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value / 1000:.2f}".rstrip("0").rstrip(".") + "k"
    if abs(value) >= 10 or value == int(value):
        return f"{value:.0f}"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def line_chart(series, threshold, minutes: int, unit: str, y_min: float = 0.0, extra=None) -> str:
    """series: [(name, color, [(minutes_ago, value)])]; threshold: (value, label)."""
    all_vals = [v for _, _, pts in series for _, v in pts] + [threshold[0]] + ([extra[0]] if extra else [])
    y_max = 4 * nice_max(max(all_vals) * 1.1 / 4)
    pw, ph = W - ML - MR, H - MT - MB

    def px(minutes_ago: float) -> float:
        return ML + (1 - minutes_ago / minutes) * pw

    def py(value: float) -> float:
        return MT + (1 - (value - y_min) / (y_max - y_min)) * ph

    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(unit)} over the last {minutes} minutes">']
    for i in range(5):  # recessive grid + y labels
        val = y_min + (y_max - y_min) * i / 4
        y = py(val)
        parts.append(f'<line class="grid" x1="{ML}" x2="{W - MR}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{ML - 6}" y="{y + 4:.1f}" text-anchor="end">{fmt(val)}</text>')
    for m in (60, 45, 30, 15, 0):
        label = "now" if m == 0 else f"-{m}m"
        parts.append(f'<text class="tick" x="{px(m):.1f}" y="{H - 10}" text-anchor="middle">{label}</text>')
    ty = py(threshold[0])
    parts.append(f'<line class="thr" x1="{ML}" x2="{W - MR}" y1="{ty:.1f}" y2="{ty:.1f}"/>')
    parts.append(f'<text class="thr-label" x="{ML + 6}" y="{ty - 5:.1f}" text-anchor="start">{html.escape(threshold[1])}</text>')
    if extra:  # optional annotation line, e.g. the challenge threshold (not part of the contract)
        ey = py(extra[0])
        parts.append(f'<line class="thr extra" x1="{ML}" x2="{W - MR}" y1="{ey:.1f}" y2="{ey:.1f}"/>')
        parts.append(f'<text class="thr-label extra" x="{ML + 6}" y="{ey - 5:.1f}" text-anchor="start">{html.escape(extra[1])}</text>')
    for name, color, pts in series:
        pts = sorted(pts, key=lambda p: -p[0])  # oldest first
        if not pts:
            continue
        path = " ".join(f"{'M' if i == 0 else 'L'}{px(m):.1f},{py(v):.1f}" for i, (m, v) in enumerate(pts))
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>')
        for m, v in pts:
            parts.append(
                f'<circle cx="{px(m):.1f}" cy="{py(v):.1f}" r="3.5" fill="{color}" class="pt">'
                f"<title>{html.escape(name)}: {fmt(v)} {html.escape(unit)} ({m:.0f} min ago)</title></circle>"
            )
    parts.append("</svg>")
    return "".join(parts)


def bar_chart(name, color, points, threshold, minutes: int, unit: str) -> str:
    """Per-minute bars (traffic)."""
    y_max = 4 * nice_max(max([v for _, v in points] + [threshold[0]]) * 1.1 / 4)
    pw, ph = W - ML - MR, H - MT - MB
    bw = max(3.0, pw / minutes - 2)
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(unit)} per minute">']
    for i in range(5):
        val = y_max * i / 4
        y = MT + (1 - val / y_max) * ph
        parts.append(f'<line class="grid" x1="{ML}" x2="{W - MR}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{ML - 6}" y="{y + 4:.1f}" text-anchor="end">{fmt(val)}</text>')
    for m in (60, 45, 30, 15, 0):
        x = ML + (1 - m / minutes) * pw
        parts.append(f'<text class="tick" x="{x:.1f}" y="{H - 10}" text-anchor="middle">{"now" if m == 0 else f"-{m}m"}</text>')
    for m, v in points:
        x = ML + (1 - (m + 1) / minutes) * pw
        h = v / y_max * ph
        parts.append(
            f'<rect x="{x:.1f}" y="{MT + ph - h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="2" fill="{color}">'
            f"<title>{fmt(v)} {html.escape(unit)} ({m} min ago)</title></rect>"
        )
    ty = MT + (1 - threshold[0] / y_max) * ph
    parts.append(f'<line class="thr" x1="{ML}" x2="{W - MR}" y1="{ty:.1f}" y2="{ty:.1f}"/>')
    parts.append(f'<text class="thr-label" x="{ML + 6}" y="{ty - 5:.1f}" text-anchor="start">{html.escape(threshold[1])}</text>')
    parts.append("</svg>")
    return "".join(parts)


def legend(items) -> str:
    return '<ul class="legend">' + "".join(
        f'<li><span class="sw" style="background:{c}"></span>{html.escape(n)}</li>' for n, c in items
    ) + "</ul>"


def status(ok: bool | None, text: str) -> str:
    if ok is None:
        return f'<span class="stat nodata">– no data</span>'
    icon, cls = ("✓", "ok") if ok else ("▲", "bad")
    return f'<span class="stat {cls}">{icon} {html.escape(text)}</span>'


def passes(value: float, threshold: dict) -> bool:
    return value <= threshold["value"] if threshold["operator"] == "lte" else value >= threshold["value"]


def thr_label(threshold: dict, unit: str) -> str:
    sign = "≤" if threshold["operator"] == "lte" else "≥"
    return f"SLO {threshold['aggregation']} {sign} {fmt(threshold['value'])} {unit}"


# ---------------------------------------------------------------- panels
def build_panels(cfg: dict, records: list[dict], only=None, mark_ms=None) -> list[str]:
    minutes = cfg["time_range_minutes"]
    panels = {p["id"]: p for p in cfg["panels"]}
    buckets = by_minute(records, minutes)
    sent = [r for r in records if r.get("event") == "response_sent"]
    received = [r for r in records if r.get("event") == "request_received"]
    failed = [r for r in records if r.get("event") == "request_failed"]
    sent_b = by_minute(sent, minutes)
    out: dict[str, str] = {}

    # 1. latency
    p = panels["latency"]
    lat = [r["latency_ms"] for r in sent if "latency_ms" in r]
    ttft = [r["ttft_ms"] for r in sent if "ttft_ms" in r]
    names = [("P50", 50, "latency_ms"), ("P95", 95, "latency_ms"), ("P99", 99, "latency_ms"), ("TTFT P95", 95, "ttft_ms")]
    series = [
        (n, SERIES_COLORS[i], [(m, percentile([r[f] for r in rs if f in r], q)) for m, rs in sent_b.items()])
        for i, (n, q, f) in enumerate(names)
    ]
    p95 = percentile(lat, 95)
    out["latency"] = (
        f'{status(passes(p95, p["threshold"]) if lat else None, f"P95 {p95:.0f} ms")}'
        f'<div class="kv">P50 {percentile(lat, 50):.0f} · P95 {p95:.0f} · P99 {percentile(lat, 99):.0f} · TTFT P95 {percentile(ttft, 95):.0f} ms</div>'
        + legend([(n, c) for n, c, _ in series])
        + line_chart(
            series, (p["threshold"]["value"], thr_label(p["threshold"], "ms")), minutes, "ms",
            extra=(mark_ms, f"Challenge threshold {mark_ms} ms") if mark_ms else None,
        )
    )

    # 2. traffic
    p = panels["traffic"]
    pts = [(m, len([r for r in rs if r.get("event") == "request_received"])) for m, rs in buckets.items()]
    pts = [(m, v) for m, v in pts if v]
    span = min(minutes, max(1.0, max((r["_min"] for r in received), default=1.0)))
    rate = len(received) / span  # requests/min over the span in which traffic was observed
    out["traffic"] = (
        f'{status(passes(rate, p["threshold"]) if received else None, f"{rate:.1f} req/min avg")}'
        f'<div class="kv">{len(received)} requests over the last {span:.0f} active min (window {minutes} min)</div>'
        + bar_chart("requests", SERIES_COLORS[0], pts, (p["threshold"]["value"], thr_label(p["threshold"], "req/min")), minutes, "requests")
    )

    # 3. errors
    p = panels["errors"]
    err_pct = len(failed) / len(received) * 100 if received else 0.0
    tool = [r for r in records if r.get("tool_success") is not None]
    tool_ok = sum(1 for r in tool if r["tool_success"]) / len(tool) * 100 if tool else 100.0
    breakdown = Counter(r.get("error_type", "unknown") for r in failed)
    ser: list = []
    e_pts = []
    for m, rs in buckets.items():
        n_in = sum(1 for r in rs if r.get("event") == "request_received")
        n_err = sum(1 for r in rs if r.get("event") == "request_failed")
        if n_in:
            e_pts.append((m, n_err / n_in * 100))
    ser.append(("Error rate %", SERIES_COLORS[1], e_pts))
    bd = ", ".join(f"{k}: {v}" for k, v in breakdown.items()) or "none"
    out["errors"] = (
        f'{status(passes(err_pct, p["threshold"]) if received else None, f"error rate {err_pct:.1f}%")}'
        f'<div class="kv">Breakdown by error_type — {html.escape(bd)} · Retrieval success {tool_ok:.1f}% (SLO ≥ 90%)</div>'
        + line_chart(ser, (p["threshold"]["value"], thr_label(p["threshold"], "%")), minutes, "% of requests")
    )

    # 4. cost (cumulative so the total can be compared to the budget line)
    p = panels["cost"]
    total_cost = sum(r.get("cost_usd", 0) for r in sent)
    run, c_pts = 0.0, []
    for m in sorted(sent_b, reverse=True):
        run += sum(r.get("cost_usd", 0) for r in sent_b[m])
        c_pts.append((m, run))
    out["cost"] = (
        f'{status(passes(total_cost, p["threshold"]) if sent else None, f"total ${total_cost:.4f}")}'
        f'<div class="kv">Cumulative USD over the window (per-minute sums add up to the total)</div>'
        + line_chart([("Cumulative cost", SERIES_COLORS[0], c_pts)], (p["threshold"]["value"], thr_label(p["threshold"], "USD")), minutes, "USD")
    )

    # 5. tokens (cumulative per field)
    p = panels["tokens"]
    t_in = sum(r.get("tokens_in", 0) for r in sent)
    t_out = sum(r.get("tokens_out", 0) for r in sent)
    ri = ro = 0
    pi, po = [], []
    for m in sorted(sent_b, reverse=True):
        ri += sum(r.get("tokens_in", 0) for r in sent_b[m])
        ro += sum(r.get("tokens_out", 0) for r in sent_b[m])
        pi.append((m, ri))
        po.append((m, ro))
    worst = max(t_in, t_out)
    out["tokens"] = (
        f'{status(passes(worst, p["threshold"]) if sent else None, f"in {t_in:,} · out {t_out:,} tokens")}'
        f'<div class="kv">Cumulative tokens per field over the window</div>'
        + legend([("Input tokens", SERIES_COLORS[0]), ("Output tokens", SERIES_COLORS[1])])
        + line_chart(
            [("Input tokens", SERIES_COLORS[0], pi), ("Output tokens", SERIES_COLORS[1], po)],
            (p["threshold"]["value"], thr_label(p["threshold"], "tokens")), minutes, "tokens",
        )
    )

    # 6. quality
    p = panels["quality"]
    q_all = [r["quality_score"] for r in sent if "quality_score" in r]
    q_mean = sum(q_all) / len(q_all) if q_all else 0.0
    q_pts = [(m, sum(r["quality_score"] for r in rs) / len(rs)) for m, rs in sent_b.items() if rs]
    out["quality"] = (
        f'{status(passes(q_mean, p["threshold"]) if q_all else None, f"mean {q_mean:.2f}")}'
        f'<div class="kv">Heuristic quality proxy (0–1), mean per minute</div>'
        + line_chart([("Quality mean", SERIES_COLORS[2], q_pts)], (p["threshold"]["value"], thr_label(p["threshold"], "score")), 60, "score (0–1)")
    )

    cards = []
    for pid in ("latency", "traffic", "errors", "cost", "tokens", "quality"):
        if only and pid not in only:
            continue
        panel = panels[pid]
        cards.append(
            f'<section class="card"><h2>{html.escape(panel["title"])} <small>[{html.escape(panel["unit"])}]</small></h2>{out[pid]}</section>'
        )
    return cards


CSS = """
:root{color-scheme:light;--bg:#f4f3f0;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--grid:#e6e5e1;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--ok:#0a6b0a;--bad:#c22f2e}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#111110;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;
--grid:#2d2d2b;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--ok:#4cc26a;--bad:#ff7a78}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,Segoe UI,sans-serif}
header{padding:16px}h1{font-size:18px;margin:0}header p{margin:4px 0 0;color:var(--ink2)}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr));gap:12px;padding:0 16px 24px}
.card{background:var(--surface);border-radius:10px;padding:14px 16px}
h2{font-size:15px;margin:0 0 6px}h2 small{color:var(--ink2);font-weight:400}
.kv{color:var(--ink2);font-size:12.5px;margin:4px 0 6px}.stat{font-weight:600}.stat.ok{color:var(--ok)}
.stat.bad{color:var(--bad)}.stat.nodata{color:var(--ink2)}
.legend{list-style:none;display:flex;flex-wrap:wrap;gap:4px 14px;margin:0 0 4px;padding:0;font-size:12.5px;color:var(--ink2)}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}
svg{width:100%;height:auto;display:block}.grid{stroke:var(--grid);stroke-width:1}
.tick{fill:var(--ink2);font-size:11px}.thr{stroke:var(--ink2);stroke-width:1.5;stroke-dasharray:6 4}
.thr-label{fill:var(--ink2);font-size:11px}.thr.extra{stroke:var(--s2)}.thr-label.extra{fill:var(--ink);font-weight:600}.pt{stroke:var(--surface);stroke-width:2}
"""


def render(refresh: int | None = 30, at: datetime | None = None, only=None, note: str | None = None, mark_ms: int | None = None) -> str:
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))["dashboard"]
    now = at or datetime.now(timezone.utc)
    records = load_records(now, cfg["time_range_minutes"])
    cards = build_panels(cfg, records, only=only, mark_ms=mark_ms)
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    stamp = now.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">{meta}'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{html.escape(cfg["title"])}</title><style>{CSS}</style></head><body>'
        f'<header><h1>{html.escape(cfg["title"])}</h1>'
        f'<p>Student MAIPHANANHTUNG 2A202602980 · time range: last {cfg["time_range_minutes"]} min · '
        f'auto-refresh {refresh or 0}s · {len(records)} log records · {"window end" if at else "rendered"} {stamp}</p>{f"<p><strong>{html.escape(note)}</strong></p>" if note else ""}</header>'
        f'<main>{"".join(cards)}</main></body></html>'
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = render().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--html", type=Path, help="write a static snapshot instead of serving")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--at", help="window end as ISO time, e.g. 2026-09-29T08:30:00Z (default: now)")
    parser.add_argument("--only", help="comma-separated panel ids to render, e.g. latency,traffic")
    parser.add_argument("--note", help="caption shown under the header (annotation only)")
    parser.add_argument("--mark-ms", type=int, help="draw an extra latency line, e.g. the challenge threshold")
    args = parser.parse_args()
    if args.html:
        at = datetime.fromisoformat(args.at.replace("Z", "+00:00")) if args.at else None
        only = set(args.only.split(",")) if args.only else None
        args.html.write_text(render(None, at, only, args.note, args.mark_ms), encoding="utf-8")
        print(f"wrote {args.html}")
        return 0
    print(f"Dashboard on http://127.0.0.1:{args.port} (Ctrl+C to stop)")
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
