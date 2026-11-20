"""Privacy-safe usage counts and feedback for the public site (CR19).

What is kept, per UTC day, in one small S3 object (<prefix>/ops/usage/<day>.json):
  events:    counts of a fixed list of events (a visit, a tab opened, a match run, a question)
  referrers: counts of the site a visit came from, as a bare host name ("linkedin.com")
Nothing about a person: no IP address, no user agent, no cookie or ID, no resume content.

Feedback is one S3 object per message (<prefix>/ops/feedback/<day>/<time>-<random>.json) with
the message, the tab it was sent from and the time. Only the owner can read either, through
GET /usage behind the passphrase.

Two requests at the same instant can lose one count; at this traffic that is acceptable.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

EVENTS = (
    "visit",
    "tab:today",
    "tab:employers",
    "tab:insights",
    "tab:ask",
    "match",
    "ask",
    "feedback",
)
MAX_EVENTS_PER_DAY = 20_000  # stops a script from running up S3 requests
MAX_FEEDBACK_PER_DAY = 50
MAX_REFERRERS = 50  # distinct sites kept per day; the rest count as "other"
_HOST = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")


def clean_referrer(text: str | None) -> str:
    """A bare host name ('linkedin.com') from a referrer URL or host, or 'direct'.
    Paths and query strings are dropped: they can carry personal details."""
    if not text:
        return "direct"
    host = text.strip().lower()
    host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", host).split("/")[0].split("?")[0].split(":")[0]
    host = host.removeprefix("www.").removeprefix("m.")
    if len(host) > 60 or not _HOST.match(host):
        return "other"
    return host


def _missing(e: Exception) -> bool:
    return type(e).__name__ in ("NoSuchKey", "ClientError")


@dataclass
class UsageLog:
    s3: object
    bucket: str
    prefix: str = "prod"

    def _day_key(self, day: str) -> str:
        return f"{self.prefix}/ops/usage/{day}.json"

    def day(self, day: str) -> dict:
        try:
            body = self.s3.get_object(Bucket=self.bucket, Key=self._day_key(day))["Body"].read()
            data = json.loads(body)
        except Exception as e:
            if not _missing(e):
                raise
            data = {}
        return {"events": data.get("events", {}), "referrers": data.get("referrers", {})}

    def add(self, event: str, referrer: str | None = None, now: datetime | None = None) -> bool:
        """Count one event. Returns False (and stores nothing) for an unknown event or once
        today's cap is reached."""
        if event not in EVENTS:
            return False
        day = (now or datetime.now(UTC)).date().isoformat()
        data = self.day(day)
        if sum(data["events"].values()) >= MAX_EVENTS_PER_DAY:
            return False
        data["events"][event] = data["events"].get(event, 0) + 1
        if event == "visit":
            ref = clean_referrer(referrer)
            refs = data["referrers"]
            if ref not in refs and len(refs) >= MAX_REFERRERS:
                ref = "other"
            refs[ref] = refs.get(ref, 0) + 1
        self.s3.put_object(
            Bucket=self.bucket,
            Key=self._day_key(day),
            Body=json.dumps(data).encode(),
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )
        return True

    def recent_days(self, n: int = 14, now: datetime | None = None) -> list[dict]:
        today = (now or datetime.now(UTC)).date()
        days = []
        for i in range(n):
            d = (today - timedelta(days=i)).isoformat()
            days.append({"day": d, **self.day(d)})
        return days

    def add_feedback(self, message: str, page: str | None, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        day = now.date().isoformat()
        if self.day(day)["events"].get("feedback", 0) >= MAX_FEEDBACK_PER_DAY:
            return False
        key = f"{self.prefix}/ops/feedback/{day}/{now:%H%M%S}-{secrets.token_hex(4)}.json"
        body = {"at": now.isoformat(timespec="seconds"), "page": page, "message": message}
        self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(body).encode(),
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )
        self.add("feedback", now=now)
        return True

    def recent_feedback(self, limit: int = 30) -> list[dict]:
        keys: list[str] = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=f"{self.prefix}/ops/feedback/"
        ):
            keys += [o["Key"] for o in page.get("Contents", [])]
        out = []
        for key in sorted(keys, reverse=True)[:limit]:
            out.append(json.loads(self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()))
        return out


def usage_from_environment() -> UsageLog | None:
    """None (nothing recorded) when no bucket is set, e.g. running locally."""
    bucket = os.environ.get("JOBRADAR_S3_BUCKET")
    if not bucket:
        return None
    import boto3

    return UsageLog(
        s3=boto3.client("s3"), bucket=bucket, prefix=os.environ.get("JOBRADAR_S3_PREFIX", "prod")
    )
