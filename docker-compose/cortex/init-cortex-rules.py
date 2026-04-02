#!/usr/bin/env python3
"""Load Prometheus alerting/recording rules into Cortex via the Ruler API.

This script runs as an init container. It scans /rules/ for subdirectories,
treating each subdirectory name as a Cortex ruler namespace. Every *.yml file
in the subdirectory is parsed and each rule group is POSTed individually.

Directory layout expected:
  /rules/
    stack/                      ← namespace "stack"
      alerts.yml                ← contains groups: stack_health, otel_collector_health, …
    otel_demo/                  ← namespace "otel_demo" (mounted by otel-demo compose)
      otel-demo-alerts.yml      ← contains groups: otel_demo_frontend, otel_demo_checkout, …

The main docker-compose.yml mounts only /rules/stack/.
The otel-demo compose override adds /rules/otel_demo/.
"""

import glob
import os
import sys
import time

import requests
import yaml

CORTEX_URL = os.getenv("CORTEX_URL", "http://prometheus:9090")


def wait_for_cortex():
    """Wait for Cortex to report ready."""
    print("⏳ Waiting for Cortex...")
    while True:
        try:
            r = requests.get(f"{CORTEX_URL}/ready", timeout=5)
            if r.status_code == 200:
                print("✅ Cortex is ready")
                return
        except requests.exceptions.RequestException:
            pass
        time.sleep(2)


def get_existing_groups(namespace):
    """Fetch rule groups already present in a namespace (returns set of group names)."""
    try:
        r = requests.get(f"{CORTEX_URL}/api/v1/rules/{namespace}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            return {
                g["name"]
                for g in data.get("data", {}).get("groups", [])
            }
    except Exception:
        pass
    return set()


def load_rules_file(filepath, namespace):
    """Load all rule groups from a YAML file into Cortex under the given namespace."""
    print(f"\n📂 {filepath} → namespace '{namespace}'")

    with open(filepath) as f:
        data = yaml.safe_load(f)

    if not data or "groups" not in data:
        print("   (no groups found — skipping)")
        return 0

    existing = get_existing_groups(namespace)
    loaded = 0

    for group in data["groups"]:
        group_name = group.get("name", "unknown")
        rule_count = len(group.get("rules", []))

        if group_name in existing:
            print(f"   ✅ {group_name} ({rule_count} rules) — already exists, skipping")
            loaded += 1
            continue

        group_yaml = yaml.dump(group, default_flow_style=False)

        try:
            r = requests.post(
                f"{CORTEX_URL}/api/v1/rules/{namespace}",
                headers={"Content-Type": "application/yaml"},
                data=group_yaml,
                timeout=10,
            )
            if r.status_code == 202:
                print(f"   ✅ {group_name} ({rule_count} rules) — loaded")
                loaded += 1
            else:
                print(f"   ⚠️  {group_name}: HTTP {r.status_code} — {r.text[:200]}")
        except requests.exceptions.RequestException as e:
            print(f"   ❌ {group_name}: {e}")

    return loaded


def main():
    wait_for_cortex()

    rules_root = "/rules"
    if not os.path.isdir(rules_root):
        print(f"No rules directory at {rules_root}")
        sys.exit(0)

    total = 0
    for namespace_dir in sorted(glob.glob(f"{rules_root}/*")):
        if not os.path.isdir(namespace_dir):
            continue
        namespace = os.path.basename(namespace_dir)

        for rules_file in sorted(glob.glob(f"{namespace_dir}/*.yml")):
            total += load_rules_file(rules_file, namespace)

    if total == 0:
        print("\n⚠️  No rule groups loaded")
    else:
        print(f"\n🎉 Done — loaded {total} rule group(s) into Cortex")


if __name__ == "__main__":
    main()
