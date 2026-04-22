#!/usr/bin/env python3
"""Create Alertmanager silences for the OpenTelemetry Demo application.

This script runs as an init container when the otel-demo compose file is enabled.
Its purpose is to validate the Alertmanager silence API end-to-end at startup —
it creates a small set of silences via POST /api/v2/silences and verifies they
can be read back via GET /api/v2/silences.

Silences are idempotent: the `comment` field is used as a stable key; if an
active silence with the same comment already exists it is left alone.

Silences auto-expire at `endsAt`; this script does not refresh them.
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

ALERTMANAGER_URL = os.getenv("ALERTMANAGER_URL", "http://alertmanager:9093")


def wait_for_alertmanager():
    """Wait for Alertmanager to report ready."""
    print("Waiting for Alertmanager...")
    while True:
        try:
            r = requests.get(f"{ALERTMANAGER_URL}/-/ready", timeout=5)
            if r.status_code == 200:
                print("Alertmanager is ready")
                return
        except requests.exceptions.RequestException:
            pass
        time.sleep(2)


def get_active_silences():
    """Return the list of currently active silences."""
    try:
        r = requests.get(f"{ALERTMANAGER_URL}/api/v2/silences", timeout=10)
        r.raise_for_status()
        return [s for s in r.json() if s.get("status", {}).get("state") == "active"]
    except requests.exceptions.RequestException as e:
        print(f"  Failed to list silences: {e}")
        return []


def silence_exists(comment, existing):
    """Idempotency check — match by comment field."""
    return any(s.get("comment") == comment for s in existing)


def create_silence(payload):
    """POST a silence definition to Alertmanager."""
    comment = payload["comment"]
    try:
        r = requests.post(
            f"{ALERTMANAGER_URL}/api/v2/silences",
            json=payload,
            timeout=10,
        )
        if r.status_code in (200, 201):
            silence_id = r.json().get("silenceID")
            print(f"  Created silence '{comment}' (id={silence_id})")
            return silence_id
        print(f"  Silence creation failed ({r.status_code}): {r.text[:200]}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"  Error creating silence '{comment}': {e}")
        return None


def build_silences():
    """Return the list of silences to create.

    Two silences are defined to exercise different matcher styles:
      1. Exact alertname match — silences one specific warning alert.
      2. Regex matcher on a label — silences all warnings for a subset of
         demo services.
    """
    starts_at = datetime.now(timezone.utc)
    ends_at = starts_at + timedelta(hours=2)
    starts = starts_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    ends = ends_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    return [
        {
            "matchers": [
                {"name": "alertname", "value": "OtelDemoFrontendProxyErrors",
                 "isRegex": False, "isEqual": True},
            ],
            "startsAt": starts,
            "endsAt": ends,
            "createdBy": "otel-demo-silences-init",
            "comment": "otel-demo-init: silence frontend-proxy traffic alert",
        },
        {
            "matchers": [
                {"name": "component", "value": "otel-demo",
                 "isRegex": False, "isEqual": True},
                {"name": "severity", "value": "warning",
                 "isRegex": False, "isEqual": True},
                {"name": "service_name", "value": "ad|cart",
                 "isRegex": True, "isEqual": True},
            ],
            "startsAt": starts,
            "endsAt": ends,
            "createdBy": "otel-demo-silences-init",
            "comment": "otel-demo-init: silence ad/cart warnings",
        },
    ]


def main():
    wait_for_alertmanager()

    existing = get_active_silences()
    print(f"Found {len(existing)} active silence(s) already present")

    created = 0
    skipped = 0
    for payload in build_silences():
        if silence_exists(payload["comment"], existing):
            print(f"  Skipping '{payload['comment']}' — already active")
            skipped += 1
            continue
        if create_silence(payload):
            created += 1

    # Read-back verification — proves the POSTs landed and the API is queryable
    final = get_active_silences()
    init_silences = [s for s in final if s.get("createdBy") == "otel-demo-silences-init"]
    print(
        f"\nDone — created {created}, skipped {skipped}, "
        f"{len(init_silences)} otel-demo silence(s) active"
    )

    if created + skipped == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
