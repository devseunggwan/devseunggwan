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


Point = tuple[float, float]
Segment = tuple[Point, Point, Point, Point]


def smooth_segments(points: list[Point]) -> list[Segment]:
    """One cubic Bezier (start, control, control, end) per pair of points.

    Uses Steffen's monotone cubic interpolation (A&A 239, 443, 1990): between
    two points the curve never rises above the higher one or dips below the
    lower one, so a zero day stays on the baseline and a peak is not inflated.
    Points are evenly spaced, so each segment is one cubic Bezier.
    """
    n = len(points)
    h = points[1][0] - points[0][0]
    slopes = [(points[i + 1][1] - points[i][1]) / h for i in range(n - 1)]

    def sign(v: float) -> float:
        return (v > 0) - (v < 0)

    tangents = [slopes[0]]
    for a, b in zip(slopes, slopes[1:]):
        tangents.append((sign(a) + sign(b)) * min(abs(a), abs(b), abs(a + b) / 4))
    tangents.append(slopes[-1])

    return [
        (
            (x0, y0),
            (x0 + h / 3, y0 + tangents[i] * h / 3),
            (x1 - h / 3, y1 - tangents[i + 1] * h / 3),
            (x1, y1),
        )
        for i, ((x0, y0), (x1, y1)) in enumerate(zip(points, points[1:]))
    ]


def fmt(p: Point) -> str:
    return f"{p[0]:.1f},{p[1]:.1f}"


def curve_path(segments: list[Segment]) -> str:
    """Path data drawing the segments as one continuous curve."""
    d = f"M{fmt(segments[0][0])}"
    for _, c1, c2, end in segments:
        d += f" C{fmt(c1)} {fmt(c2)} {fmt(end)}"
    return d


def dashed_path(segment: Segment, dashes: int = 7) -> str:
    """Path data for a dashed version of one Bezier segment.

    The dashes are separate sub-paths rather than stroke-dasharray, since the
    GitHub app's image renderer already failed on less common SVG features
    (#10). Each dash is a short straight piece sampled from the curve.
    """
    p0, p1, p2, p3 = segment

    def at(t: float) -> Point:
        u = 1 - t
        return (
            u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
        )

    pieces = []
    step = 1 / (2 * dashes - 1)
    for k in range(dashes):
        t0, t1 = 2 * k * step, (2 * k + 1) * step
        samples = [at(t0 + (t1 - t0) * j / 3) for j in range(4)]
        pieces.append("M" + " L".join(fmt(p) for p in samples))
    return " ".join(pieces)


def render(login: str, days: list[tuple[date, int]]) -> str:
    plot_w = WIDTH - LEFT - RIGHT
    plot_h = HEIGHT - TOP - BOTTOM
    top = nice_max(max(count for _, count in days))

    def x(i: int) -> float:
        return LEFT + plot_w * i / (len(days) - 1)

    def y(count: int) -> float:
        return TOP + plot_h * (1 - count / top)

    points = [(x(i), y(count)) for i, (_, count) in enumerate(days)]
    # Plain <path> data only: the GitHub mobile app's image renderer showed a
    # broken image for the first version, which used a gradient, polygon,
    # polyline and per-point <title>. The stats card, which renders there,
    # sticks to basic shapes, so this does too.
    # The last point is today, which is still in progress (#13): it is drawn
    # with a dashed segment and a hollow point, and left out of the filled
    # area, so a low count reads as "so far" rather than as a drop.
    segments = smooth_segments(points)
    line = curve_path(segments[:-1])
    area = f"{line} L{points[-2][0]:.1f},{TOP + plot_h} L{LEFT},{TOP + plot_h} Z"
    total = sum(count for _, count in days)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" '
        f'aria-label="Contributions by {escape(login)} over the last {DAYS} days">',
        "<style>text{font-family:'Segoe UI',Ubuntu,'Helvetica Neue',sans-serif}</style>",
        f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="4.5" '
        f'fill="{BG}" stroke="{BORDER}"/>',
        f'<text x="24" y="40" fill="{ACCENT}" font-size="20" font-weight="600">'
        f"Contribution graph</text>",
        f'<text x="{WIDTH - 24}" y="40" fill="{LABEL}" font-size="16" text-anchor="end">'
        f"Last {DAYS} days (UTC) · {total:,} contributions</text>",
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
    # A date label every 5 days, counted back from today so the last is always
    # shown. Days are GitHub's contribution days, which are UTC (#15).
    for i in range(len(days) - 1, -1, -5):
        label = "Today" if i == len(days) - 1 else days[i][0].strftime("%m/%d")
        out.append(
            f'<text x="{x(i):.1f}" y="{HEIGHT - 20}" fill="{LABEL}" font-size="15" '
            f'text-anchor="middle">{label}</text>'
        )
    out.append(f'<path d="{area}" fill="{ACCENT}" fill-opacity="0.15"/>')
    out.append(f'<path d="{line}" fill="none" stroke="{ACCENT}" stroke-width="3"/>')
    out.append(
        f'<path d="{dashed_path(segments[-1])}" fill="none" stroke="{ACCENT}" '
        'stroke-width="3"/>'
    )
    for px, py in points[:-1]:
        out.append(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{BG}" stroke="{ACCENT}" '
            'stroke-width="2"/>'
        )
    tx, ty = points[-1]
    out.append(
        f'<circle cx="{tx:.1f}" cy="{ty:.1f}" r="5" fill="{BG}" stroke="{LABEL}" '
        'stroke-width="2"/>'
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
    out_path = sys.argv[2] if len(sys.argv) > 2 else "stats/activity.svg"

    days = collect(login, datetime.now(timezone.utc).date())
    print(f"  days={len(days)} total={sum(c for _, c in days)}", file=sys.stderr)
    with open(out_path, "w") as handle:
        handle.write(render(login, days))
    print(f"wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
