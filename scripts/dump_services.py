"""Print services (courts) of a Reservio business as YAML for venues.yaml.

Usage: uv run python scripts/dump_services.py <subdomain>
"""

import json
import re
import sys

import httpx


def main(subdomain: str) -> None:
    html = httpx.get(
        f"https://{subdomain}.reservio.com/services",
        headers={"User-Agent": "Mozilla/5.0"},
        follow_redirects=True,
        timeout=30,
    ).text
    m = re.search(r'id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        sys.exit("__NEXT_DATA__ not found")
    props = json.loads(m.group(1))["props"]["pageProps"]
    state = props["initialApolloState"]
    print(f"# business_id: {props['businessId']}")
    print(f"# timezone: {props['businessSettings']['timezone']}")
    services = sorted(
        (v for k, v in state.items() if k.startswith("Service:")), key=lambda s: s["position"]
    )
    for s in services:
        price = s["price"]
        print(f"  - name: {s['name']!r}")
        print(f"    service_id: {s['id']}")
        print(f"    price: {price['amount']}  # {price['currency']}, {s['duration']} s")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "padel-port-batumi2")
