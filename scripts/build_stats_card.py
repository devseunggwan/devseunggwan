#!/usr/bin/env python3
"""Render an all-time contribution stats card from GitHub's own GraphQL API.

contributionsCollection answers from the *viewer's* vantage point, so the same
query returns 9,463 all-time commits to the account owner and 1,162 to a token
that can only see public repositories. The third-party card this replaces was
reading the public view and was not wrong; it simply counted a different
population than the streak card beside it, which reports the profile calendar
and does include private contributions.

Both failure modes here are silent by nature — a year that errors and a token
that cannot see 62 of 73 repositories both just make the total smaller. So both
raise: a wrong number must cost a red workflow run.
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
      restrictedContributionsCount
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

# 1%: above it the token is blind to whole repositories rather than to the
# handful of contributions no token ever recovers.
BLIND_TOKEN_RATIO = 0.01

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
    restricted = 0
    for year in years:
        start = f"{year}-01-01T00:00:00Z"
        end = (
            now.strftime("%Y-%m-%dT%H:%M:%SZ")
            if year == now.year
            else f"{year}-12-31T23:59:59Z"
        )
        # One year per request so the workflow log carries a per-year audit
        # trail: a total that looks wrong is then readable without a rerun.
        collection = graphql(CONTRIBUTIONS_QUERY, login=login, **{"from": start, "to": end})[
            "user"
        ]["contributionsCollection"]
        row = {"year": year, **{field: collection[field] for _, field in METRICS}}
        per_year.append(row)
        restricted += collection["restrictedContributionsCount"]
        for _, field in METRICS:
            totals[field] += row[field]

    # Contributions in repositories the token cannot read are reported only as
    # this count, never inside the metrics, so a blind token yields a smaller
    # card and nothing else in the response objects. A residue survives every
    # token — 14 of this account's, all in 2021, sit in a repository even the
    # owner can no longer read — so the test is proportion, not presence. The
    # two cases are three orders of magnitude apart (0.07% against roughly 87%
    # for a public-only token), which is what makes the constant unimportant.
    visible = sum(totals.values())
    if restricted > BLIND_TOKEN_RATIO * (visible + restricted):
        raise RuntimeError(
            f"{restricted} of {visible + restricted} contributions sit in repositories "
            "this token cannot read, so the card would undercount. Run with a token "
            "that can read them (the workflow expects the STATS_TOKEN secret)."
        )
    print(f"  restricted={restricted} visible={visible}", file=sys.stderr)
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
