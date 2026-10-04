"""The one definition of "a week" for the whole QA app: Sunday through Saturday.

Every page that counts, groups or labels by week (the weekly 3-per-agent quota,
the Weekly/Monthly picker, the weekly batch's default range, the disputes
"Week of ..." groups, Home's "Logged This Week") goes through these helpers so
the rule lives in exactly one place. To change the week's first day, change
WEEK_STARTS_ON below and nothing else.
"""

from datetime import date, timedelta

# Python's date.weekday(): Monday=0 ... Sunday=6.
WEEK_STARTS_ON = 6  # Sunday

WEEK_NAME = "Sunday to Saturday"


def week_start(d: date) -> date:
    """The first day (Sunday) of the week that `d` falls in."""
    return d - timedelta(days=(d.weekday() - WEEK_STARTS_ON) % 7)


def week_end(d: date) -> date:
    """The last day (Saturday) of the week that `d` falls in."""
    return week_start(d) + timedelta(days=6)


def week_bounds(d: date) -> tuple[date, date]:
    start = week_start(d)
    return start, start + timedelta(days=6)


def in_week(qa_date, d: date) -> bool:
    """True if the ISO date string `qa_date` (YYYY-MM-DD...) is in the same week as `d`."""
    if not qa_date:
        return False
    start, end = week_bounds(d)
    return start.isoformat() <= str(qa_date)[:10] <= end.isoformat()
