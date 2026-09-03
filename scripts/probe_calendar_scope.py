#!/usr/bin/env python3
"""Temporary probe: does contributionCalendar answer the same under any token?

Deleted immediately after the measurement — it exists only to produce a CI log
line under secrets.GITHUB_TOKEN that can be compared against the owner's own.
"""

import json
import subprocess
import sys

Q = """query($l:String!,$f:DateTime!,$t:DateTime!){
  user(login:$l){ contributionsCollection(from:$f,to:$t){
    contributionCalendar{ totalContributions }
    restrictedContributionsCount
    totalCommitContributions
  } }
}"""

login = sys.argv[1]
total = 0
for year in range(2020, 2027):
    end = "2026-09-03T12:00:00Z" if year == 2026 else f"{year}-12-31T23:59:59Z"
    out = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={Q}", "-F", f"l={login}",
         "-F", f"f={year}-01-01T00:00:00Z", "-F", f"t={end}"],
        capture_output=True, text=True, check=True)
    c = json.loads(out.stdout)["data"]["user"]["contributionsCollection"]
    cal = c["contributionCalendar"]["totalContributions"]
    total += cal
    print(f"  {year} calendar={cal} commits={c['totalCommitContributions']} "
          f"restricted={c['restrictedContributionsCount']}")
print(f"calendar_all_time={total}")
