#!/usr/bin/env python3
"""Render a line graph of the last 31 days of contributions.

This replaces the image from github-readme-activity-graph.vercel.app. That
public deployment has answered HTTP 402 (DEPLOYMENT_DISABLED) since late August
2026 (upstream issue #264), so the README showed a broken image. The graph is
drawn here instead, from the same `contributionCalendar` field the stats card
uses, so it needs no PAT and depends on no outside renderer.
"""

import sys
from datetime import date, datetime, timedelta, timezone

from build_stats_card import ACCENT, BG, BORDER, LABEL, VALUE, escape, graphql

CALENDAR_QUERY = """
query($login:String!, $from:DateTime!, $to:DateTime!) {
  user(login:$login) {
    contributionsCollection(from:$from, to:$to) {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""

DAYS = 31
GRID = "#21262d"
WIDTH, HEIGHT = 830, 320
# Plot area inside the card: room for the title above and date labels below.
LEFT, RIGHT, TOP, BOTTOM = 64, 28, 88, 52


def collect(login: str, today: date) -> list[tuple[date, int]]:
    """One entry per day of the window, oldest first, zero-filled."""
    start = today - timedelta(days=DAYS - 1)
    calendar = graphql(
        CALENDAR_QUERY,
        login=login,
        **{
            "from": f"{start.isoformat()}T00:00:00Z",
            "to": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )["user"]["contributionsCollection"]["contributionCalendar"]
    # The calendar pads to whole weeks, so days outside the window come back
    # too; keep only the ones inside it.
    counts = {
        date.fromisoformat(day["date"]): day["contributionCount"]
        for week in calendar["weeks"]
        for day in week["contributionDays"]
    }
    return [(start + timedelta(days=i), counts.get(start + timedelta(days=i), 0)) for i in range(DAYS)]


def nice_max(value: int) -> int:
    """Round the y-axis top up to a value that divides into 4 clean steps."""
    raw = max(1, -(-value // 4))  # ceil(value / 4)
    magnitude = 10 ** (len(str(raw)) - 1)
    step = next(m * magnitude for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10) if m * magnitude >= raw)
    return int(step * 4)


def render(login: str, days: list[tuple[date, int]]) -> str:
    plot_w = WIDTH - LEFT - RIGHT
    plot_h = HEIGHT - TOP - BOTTOM
    top = nice_max(max(count for _, count in days))

    def x(i: int) -> float:
        return LEFT + plot_w * i / (len(days) - 1)

    def y(count: int) -> float:
        return TOP + plot_h * (1 - count / top)

    points = [(x(i), y(count)) for i, (_, count) in enumerate(days)]
    line = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
    area = f"{LEFT},{TOP + plot_h} {line} {LEFT + plot_w},{TOP + plot_h}"
    total = sum(count for _, count in days)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" '
        f'aria-label="Contributions by {escape(login)} over the last {DAYS} days">',
        "<style>text{font-family:'Segoe UI',Ubuntu,'Helvetica Neue',sans-serif}</style>",
        '<defs><linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{ACCENT}" stop-opacity="0.35"/>'
        f'<stop offset="1" stop-color="{ACCENT}" stop-opacity="0"/>'
        "</linearGradient></defs>",
        f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="4.5" '
        f'fill="{BG}" stroke="{BORDER}"/>',
        f'<text x="24" y="40" fill="{ACCENT}" font-size="20" font-weight="600">'
        f"Contribution graph</text>",
        f'<text x="{WIDTH - 24}" y="40" fill="{LABEL}" font-size="16" text-anchor="end">'
        f"Last {DAYS} days · {total:,} contributions</text>",
    ]
    for step in range(5):
        value = top * step // 4
        gy = y(value)
        out.append(
            f'<line x1="{LEFT}" y1="{gy:.1f}" x2="{LEFT + plot_w}" y2="{gy:.1f}" '
            f'stroke="{GRID}" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{LEFT - 10}" y="{gy + 5:.1f}" fill="{LABEL}" font-size="15" '
            f'text-anchor="end">{value:,}</text>'
        )
    # A date label every 5 days, counted back from today so the last is always shown.
    for i in range(len(days) - 1, -1, -5):
        out.append(
            f'<text x="{x(i):.1f}" y="{HEIGHT - 20}" fill="{LABEL}" font-size="15" '
            f'text-anchor="middle">{days[i][0].strftime("%m/%d")}</text>'
        )
    out.append(f'<polygon points="{area}" fill="url(#fill)"/>')
    out.append(
        f'<polyline points="{line}" fill="none" stroke="{ACCENT}" stroke-width="3" '
        'stroke-linejoin="round" stroke-linecap="round"/>'
    )
    for (px, py), (day, count) in zip(points, days):
        out.append(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{BG}" stroke="{ACCENT}" '
            f'stroke-width="2"><title>{day.isoformat()}: {count}</title></circle>'
        )
    out.append(
        f'<text x="{LEFT}" y="{TOP - 16}" fill="{VALUE}" font-size="15">Contributions / day</text>'
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: build_activity_graph.py <login> [out_path]")
    login = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else "stats/activity-graph.svg"

    days = collect(login, datetime.now(timezone.utc).date())
    print(f"  days={len(days)} total={sum(c for _, c in days)}", file=sys.stderr)
    with open(out_path, "w") as handle:
        handle.write(render(login, days))
    print(f"wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
