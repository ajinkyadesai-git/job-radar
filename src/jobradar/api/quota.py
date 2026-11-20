"""A daily cap on /ask, so a public web page cannot run up the Claude API bill.

The count lives in one small S3 object per UTC day (<prefix>/ops/ask_usage/<day>.json). Two
requests at the same instant can both pass the check; at this traffic that is acceptable,
and the Anthropic account limit is the hard backstop.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class DailyQuota:
    s3: object
    bucket: str
    prefix: str = "prod"
    cap: int = 20

    def _key(self, day: str) -> str:
        return f"{self.prefix}/ops/ask_usage/{day}.json"

    def used(self, day: str) -> int:
        try:
            body = self.s3.get_object(Bucket=self.bucket, Key=self._key(day))["Body"].read()
            return int(json.loads(body).get("count", 0))
        except Exception as e:  # no object yet today
            if type(e).__name__ in ("NoSuchKey", "ClientError"):
                return 0
            raise

    def take(self, now: datetime | None = None) -> tuple[bool, int]:
        """Use one question if any are left today. Returns (allowed, remaining)."""
        day = (now or datetime.now(UTC)).date().isoformat()
        used = self.used(day)
        if used >= self.cap:
            return False, 0
        self.s3.put_object(
            Bucket=self.bucket,
            Key=self._key(day),
            Body=json.dumps({"count": used + 1}).encode(),
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )
        return True, self.cap - used - 1


def quota_from_environment() -> DailyQuota | None:
    """None (no cap) when no bucket is set, e.g. running locally."""
    bucket = os.environ.get("JOBRADAR_S3_BUCKET")
    if not bucket:
        return None
    import boto3

    return DailyQuota(
        s3=boto3.client("s3"),
        bucket=bucket,
        prefix=os.environ.get("JOBRADAR_S3_PREFIX", "prod"),
        cap=int(os.environ.get("JOBRADAR_ASK_DAILY_CAP", "20")),
    )
