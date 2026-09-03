#!/usr/bin/env python3
"""Render a contribution-activity card from GitHub's own GraphQL API.

The card this replaces read `contributionsCollection`'s per-type totals
(commits, PRs, issues), and those answer from the *viewer's* vantage point: the
same query returns 9,465 all-time commits to the account owner and 1,162 to a
token that can only see public repositories, of which this account has 11
against 62 private. Nothing was broken — that card and the streak card beside it
were each right about a different population, which is what made the profile
read as self-contradicting.

`contributionCalendar` is the field that does not move. Measured in CI under
`secrets.GITHUB_TOKEN`, every year's total matched the owner's own to the digit
(2026: 13,521 both ways) while `totalCommitContributions` collapsed from 4,793
to 652. So every metric here is derived from the calendar: one population, no
token to keep in a secret, and the same numbers the streak card counts.

None of the four rows repeats a number the streak card already prints.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

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

PROFILE_QUERY = """
query($login:String!) {
  user(login:$login) { contributionsCollection { contributionYears } }
}
"""

# The streak card's own palette, so the two sit together without introducing a
# second design system (#4).
BG = "#0d1117"
BORDER = "#2e343b"
LABEL = "#8b949e"
VALUE = "#c9d1d9"
ACCENT = "#58a6ff"

# Matches the streak card's rendered height at its README width, so the two
# cards' tops line up on one row (#4).
WIDTH, HEIGHT = 331, 195


def graphql(query: str, **variables: object) -> dict[str, Any]:
    command = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        command += ["-F", f"{key}={value}"]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh api graphql failed: {result.stderr.strip()}")
    payload = json.loads(result.stdout)
    if payload.get("errors"):
        raise RuntimeError(f"graphql returned errors: {payload['errors']}")
    return payload["data"]


def collect(login: str) -> list[tuple[str, int]]:
    """Every day this account contributed on, oldest first.

    A year that cannot be read raises rather than contributing zero days: a
    silently smaller card is the defect this generator exists to remove, so a
    wrong number has to cost a red workflow run.
    """
    years = graphql(PROFILE_QUERY, login=login)["user"]["contributionsCollection"][
        "contributionYears"
    ]
    if not years:
        raise RuntimeError(f"{login} has no contribution years — refusing to render an empty card")

    now = datetime.now(timezone.utc)
    days: list[tuple[str, int]] = []
    for year in sorted(years):
        start = f"{year}-01-01T00:00:00Z"
        end = (
            now.strftime("%Y-%m-%dT%H:%M:%SZ")
            if year == now.year
            else f"{year}-12-31T23:59:59Z"
        )
        calendar = graphql(CALENDAR_QUERY, login=login, **{"from": start, "to": end})[
            "user"
        ]["contributionsCollection"]["contributionCalendar"]
        # A year's window is padded out to whole weeks at both ends, so the
        # neighbouring years' days come back too. Filtering by the day's own
        # date rather than by which request returned it is what keeps them from
        # being counted twice.
        days += [
            (day["date"], day["contributionCount"])
            for week in calendar["weeks"]
            for day in week["contributionDays"]
            if day["contributionCount"] and day["date"][:4] == str(year)
        ]
    days.sort()
    return days


def summarize(days: list[tuple[str, int]]) -> tuple[str, list[tuple[str, str]]]:
    total = sum(count for _, count in days)
    this_year = str(datetime.now(timezone.utc).year)
    rows = [
        ("Active days", f"{len(days):,}"),
        ("Per active day", f"{total / len(days):.1f}"),
        ("Best day", f"{max(count for _, count in days):,}"),
        ("This year", f"{sum(c for d, c in days if d[:4] == this_year):,}"),
    ]
    return days[0][0], rows


def escape(text: object) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(login: str, since: str, rows: list[tuple[str, str]]) -> str:
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" '
        f'aria-label="GitHub contribution activity for {escape(login)}">',
        "<style>text{font-family:'Segoe UI',Ubuntu,'Helvetica Neue',sans-serif}</style>",
        f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="4.5" '
        f'fill="{BG}" stroke="{BORDER}"/>',
        f'<text x="24" y="34" fill="{ACCENT}" font-size="15" font-weight="600">Activity</text>',
        # The window is printed because three of the four rows are all-time
        # figures while the streak card beside it counts a rolling one.
        f'<text x="24" y="52" fill="{LABEL}" font-size="11">All time · since {escape(since)}</text>',
    ]
    step = 26
    y = (HEIGHT + 58 - (len(rows) - 1) * step) // 2
    for label, value in rows:
        lines.append(f'<text x="24" y="{y}" fill="{LABEL}" font-size="14">{escape(label)}</text>')
        lines.append(
            f'<text x="{WIDTH - 24}" y="{y}" fill="{VALUE}" font-size="14" '
            f'text-anchor="end">{escape(value)}</text>'
        )
        y += step
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: build_stats_card.py <login> [out_path]")
    login = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else "stats/stats.svg"

    days = collect(login)
    since, rows = summarize(days)
    print(f"  days={len(days)} total={sum(c for _, c in days)} since={since}", file=sys.stderr)
    for label, value in rows:
        print(f"  {label}: {value}", file=sys.stderr)

    with open(out_path, "w") as handle:
        handle.write(render(login, since, rows))
    print(f"wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
