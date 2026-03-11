#!/usr/bin/env python3
"""Create OpenSearch alerting monitors for the OpenTelemetry Demo application.

This script runs as an init container when the otel-demo compose file is enabled.
It creates monitors targeting demo service traces and logs in OpenSearch.

Monitors are idempotent — existing monitors are skipped on re-run.
"""

import os
import time
import requests

OPENSEARCH_URL = "https://opensearch:9200"
USERNAME = os.getenv("OPENSEARCH_USER", "admin")
PASSWORD = os.getenv("OPENSEARCH_PASSWORD", "My_password_123!@#")


def wait_for_opensearch():
    """Wait for OpenSearch to be ready"""
    print("Waiting for OpenSearch...")
    while True:
        try:
            response = requests.get(
                f"{OPENSEARCH_URL}/_cluster/health",
                auth=(USERNAME, PASSWORD),
                verify=False,
                timeout=5,
            )
            if response.status_code == 200:
                break
        except requests.exceptions.RequestException:
            pass
        time.sleep(5)
    print("OpenSearch is ready")


def get_existing_monitor(monitor_name):
    """Check if an alerting monitor with the given name already exists"""
    try:
        response = requests.post(
            f"{OPENSEARCH_URL}/_plugins/_alerting/monitors/_search",
            auth=(USERNAME, PASSWORD),
            headers={"Content-Type": "application/json"},
            json={
                "size": 1,
                "query": {"term": {"monitor.name.keyword": monitor_name}}
            },
            verify=False,
            timeout=10,
        )
        if response.status_code == 200:
            hits = response.json().get("hits", {}).get("hits", [])
            if hits:
                return hits[0].get("_id")
        return None
    except requests.exceptions.RequestException as e:
        print(f"  Error checking monitor '{monitor_name}': {e}")
        return None


def create_monitor(monitor_payload):
    """Create an alerting monitor in OpenSearch (idempotent)"""
    monitor_name = monitor_payload.get("name", "unknown")

    existing_id = get_existing_monitor(monitor_name)
    if existing_id:
        print(f"  Monitor already exists: {monitor_name}")
        return existing_id

    try:
        response = requests.post(
            f"{OPENSEARCH_URL}/_plugins/_alerting/monitors",
            auth=(USERNAME, PASSWORD),
            headers={"Content-Type": "application/json"},
            json=monitor_payload,
            verify=False,
            timeout=10,
        )
        if response.status_code in (200, 201):
            monitor_id = response.json().get("_id")
            print(f"  Created monitor: {monitor_name}")
            return monitor_id
        else:
            print(f"  Monitor creation failed ({response.status_code}): {response.text[:200]}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"  Error creating monitor '{monitor_name}': {e}")
        return None


def create_otel_demo_monitors():
    """Create alerting monitors for the OpenTelemetry Demo services.

    These monitors target traces and logs produced by the demo's microservices.
    They detect issues in the checkout flow, payment processing, and general
    service health. All monitors are safe to keep even if demo services restart.
    """
    print("Creating OTel Demo alerting monitors...")

    monitors = [
        # Checkout flow errors — critical business path
        {
            "type": "monitor",
            "name": "OTel Demo - Checkout Errors",
            "monitor_type": "query_level_monitor",
            "enabled": True,
            "schedule": {"period": {"interval": 5, "unit": "MINUTES"}},
            "inputs": [{
                "search": {
                    "indices": ["otel-v1-apm-span*"],
                    "query": {
                        "size": 0,
                        "query": {
                            "bool": {
                                "filter": [
                                    {"range": {"endTime": {"gte": "now-5m"}}},
                                    {"term": {"serviceName": "checkout"}},
                                    {"term": {"status.code": 2}}
                                ]
                            }
                        }
                    }
                }
            }],
            "triggers": [{
                "query_level_trigger": {
                    "name": "Checkout error traces detected",
                    "severity": "1",
                    "condition": {
                        "script": {
                            "source": "ctx.results[0].hits.total.value > 10",
                            "lang": "painless"
                        }
                    },
                    "actions": []
                }
            }]
        },
        # Payment service failures — detects paymentFailure feature flag scenarios
        {
            "type": "monitor",
            "name": "OTel Demo - Payment Failures",
            "monitor_type": "query_level_monitor",
            "enabled": True,
            "schedule": {"period": {"interval": 5, "unit": "MINUTES"}},
            "inputs": [{
                "search": {
                    "indices": ["otel-v1-apm-span*"],
                    "query": {
                        "size": 0,
                        "query": {
                            "bool": {
                                "filter": [
                                    {"range": {"endTime": {"gte": "now-5m"}}},
                                    {"term": {"serviceName": "payment"}},
                                    {"term": {"status.code": 2}}
                                ]
                            }
                        }
                    }
                }
            }],
            "triggers": [{
                "query_level_trigger": {
                    "name": "Payment error traces detected",
                    "severity": "1",
                    "condition": {
                        "script": {
                            "source": "ctx.results[0].hits.total.value > 5",
                            "lang": "painless"
                        }
                    },
                    "actions": []
                }
            }]
        },
        # Frontend error logs — detects user-facing issues
        {
            "type": "monitor",
            "name": "OTel Demo - Frontend Error Logs",
            "monitor_type": "query_level_monitor",
            "enabled": True,
            "schedule": {"period": {"interval": 5, "unit": "MINUTES"}},
            "inputs": [{
                "search": {
                    "indices": ["logs-otel-v1*"],
                    "query": {
                        "size": 0,
                        "query": {
                            "bool": {
                                "filter": [
                                    {"range": {"time": {"gte": "now-5m"}}},
                                    {"terms": {"resource.attributes.service.name": [
                                        "frontend", "frontend-proxy"
                                    ]}},
                                    {"terms": {"severityText": ["ERROR", "FATAL"]}}
                                ]
                            }
                        }
                    }
                }
            }],
            "triggers": [{
                "query_level_trigger": {
                    "name": "Frontend error log count exceeds threshold",
                    "severity": "2",
                    "condition": {
                        "script": {
                            "source": "ctx.results[0].hits.total.value > 20",
                            "lang": "painless"
                        }
                    },
                    "actions": []
                }
            }]
        },
        # Slow API responses — high trace duration from frontend
        {
            "type": "monitor",
            "name": "OTel Demo - Slow Frontend Responses",
            "monitor_type": "query_level_monitor",
            "enabled": True,
            "schedule": {"period": {"interval": 5, "unit": "MINUTES"}},
            "inputs": [{
                "search": {
                    "indices": ["otel-v1-apm-span*"],
                    "query": {
                        "size": 0,
                        "query": {
                            "bool": {
                                "filter": [
                                    {"range": {"endTime": {"gte": "now-5m"}}},
                                    {"term": {"serviceName": "frontend"}},
                                    {"term": {"kind": "SERVER"}},
                                    {"range": {"durationInNanos": {"gte": 3000000000}}}
                                ]
                            }
                        }
                    }
                }
            }],
            "triggers": [{
                "query_level_trigger": {
                    "name": "Slow frontend requests detected",
                    "severity": "3",
                    "condition": {
                        "script": {
                            "source": "ctx.results[0].hits.total.value > 10",
                            "lang": "painless"
                        }
                    },
                    "actions": []
                }
            }]
        },
        # Cart service errors — detects cartFailure feature flag scenarios
        {
            "type": "monitor",
            "name": "OTel Demo - Cart Service Errors",
            "monitor_type": "query_level_monitor",
            "enabled": True,
            "schedule": {"period": {"interval": 5, "unit": "MINUTES"}},
            "inputs": [{
                "search": {
                    "indices": ["otel-v1-apm-span*"],
                    "query": {
                        "size": 0,
                        "query": {
                            "bool": {
                                "filter": [
                                    {"range": {"endTime": {"gte": "now-5m"}}},
                                    {"term": {"serviceName": "cart"}},
                                    {"term": {"status.code": 2}}
                                ]
                            }
                        }
                    }
                }
            }],
            "triggers": [{
                "query_level_trigger": {
                    "name": "Cart error traces detected",
                    "severity": "2",
                    "condition": {
                        "script": {
                            "source": "ctx.results[0].hits.total.value > 10",
                            "lang": "painless"
                        }
                    },
                    "actions": []
                }
            }]
        },
    ]

    created = 0
    for monitor_payload in monitors:
        result = create_monitor(monitor_payload)
        if result:
            created += 1

    print(f"Processed {created}/{len(monitors)} OTel Demo monitors")
    return created


def main():
    wait_for_opensearch()
    create_otel_demo_monitors()
    print("OTel Demo monitors initialization complete")


if __name__ == "__main__":
    main()
