#!/usr/bin/env python3
"""Render an all-time contribution stats card from GitHub's own GraphQL API.

The third-party card this replaces reported 1.1k all-time commits for an
account whose 2026 alone holds 4,791 — its generator documents a query-cost
failure on high-volume user-years, and a year it fails to fetch disappears from
the sum without a trace. So the rule here is that a year which cannot be read
raises: a wrong number must cost a red workflow run, never a quietly smaller
total.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

CONTRIBUTIONS_QUERY = """
query($login:String!, $from:DateTime!, $to:DateTime!) {
  user(login:$login) {
    contributionsCollection(from:$from, to:$to) {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalPullRequestReviewContributions
    }
  }
}
"""

PROFILE_QUERY = """
query($login:String!) {
  user(login:$login) {
    createdAt
    contributionsCollection { contributionYears }
  }
}
"""

# The summary card's own palette, so this sits beside the streak card without
# introducing a second design system (#3).
BG = "#0d1117"
BORDER = "#2e343b"
LABEL = "#8b949e"
VALUE = "#c9d1d9"
ACCENT = "#58a6ff"

# Matches the streak card's rendered height at its README width, so the two
# cards' tops line up on one row (#3).
WIDTH, HEIGHT = 331, 195

METRICS = (
    ("Commits", "totalCommitContributions"),
    ("Pull requests", "totalPullRequestContributions"),
    ("Issues", "totalIssueContributions"),
    ("Reviews", "totalPullRequestReviewContributions"),
)


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


def collect(login: str) -> tuple[str, list[dict[str, Any]], dict[str, int]]:
    profile = graphql(PROFILE_QUERY, login=login)["user"]
    years = sorted(profile["contributionsCollection"]["contributionYears"])
    if not years:
        raise RuntimeError(f"{login} has no contribution years — refusing to render a zeroed card")

    now = datetime.now(timezone.utc)
    per_year: list[dict[str, Any]] = []
    totals = {field: 0 for _, field in METRICS}
    for year in years:
        start = f"{year}-01-01T00:00:00Z"
        end = (
            now.strftime("%Y-%m-%dT%H:%M:%SZ")
            if year == now.year
            else f"{year}-12-31T23:59:59Z"
        )
        # One year per request: the combined multi-year form is what trips
        # GitHub's cost estimator on heavy accounts.
        collection = graphql(CONTRIBUTIONS_QUERY, login=login, **{"from": start, "to": end})[
            "user"
        ]["contributionsCollection"]
        row = {"year": year, **{field: collection[field] for _, field in METRICS}}
        per_year.append(row)
        for _, field in METRICS:
            totals[field] += row[field]
    return profile["createdAt"], per_year, totals


def escape(text: object) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(login: str, since_year: str, totals: dict[str, int]) -> str:
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" '
        f'aria-label="All-time GitHub contribution stats for {escape(login)}">',
        "<style>text{font-family:'Segoe UI',Ubuntu,'Helvetica Neue',sans-serif}</style>",
        f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="4.5" '
        f'fill="{BG}" stroke="{BORDER}"/>',
        f'<text x="24" y="34" fill="{ACCENT}" font-size="15" font-weight="600">Stats</text>',
        # The window is printed because the streak card beside this one counts a
        # different span; unlabelled, the two totals read as contradicting.
        f'<text x="24" y="52" fill="{LABEL}" font-size="11">All time · since {escape(since_year)}</text>',
    ]
    # Deliberately no "Contributions" row: the streak card already prints that
    # total over a slightly different window, and two near-but-unequal copies of
    # one number is the defect this card exists to remove.
    step = 26
    y = (HEIGHT + 58 - (len(METRICS) - 1) * step) // 2
    for label, field in METRICS:
        lines.append(f'<text x="24" y="{y}" fill="{LABEL}" font-size="14">{escape(label)}</text>')
        lines.append(
            f'<text x="{WIDTH - 24}" y="{y}" fill="{VALUE}" font-size="14" '
            f'text-anchor="end">{totals[field]:,}</text>'
        )
        y += step
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def main() -> None:
    login = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GITHUB_LOGIN", "")
    if not login:
        raise SystemExit("usage: build_stats_card.py <login>")
    out_path = sys.argv[2] if len(sys.argv) > 2 else "stats/stats.svg"

    created_at, per_year, totals = collect(login)
    for row in per_year:
        print(f"  {row}", file=sys.stderr)
    print(f"  totals={totals}", file=sys.stderr)

    with open(out_path, "w") as handle:
        handle.write(render(login, created_at[:4], totals))
    print(f"wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
