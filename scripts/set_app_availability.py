#!/usr/bin/env python3
"""Guarded, idempotent App Availability setup for the approved v1.0 release.

Why this exists
---------------
The approved v1.0 version reports `appStoreState = READY_FOR_SALE`, but the app
is listed in no App Store storefront. Diagnosis (read-only run 34859073198):

    GET /v1/apps/6787153621/appAvailabilityV2
    404 NOT_FOUND "There is no resource of type 'appAvailabilities' with id
    '6787153621'"

App Availability is not part of the review submission, so a release can reach
READY_FOR_SALE with availability never created — the app then never appears in
any storefront. This script creates it once, exactly like the App Store Connect
UI default ("Set Up Availability" -> "All Countries or Regions"), and does
nothing if availability already exists.

Scope guarantees
----------------
* Touches ONLY app availability. No pricing, IAP, privacy, metadata, screenshot,
  submission or release-request endpoint is called.
* Requires the target app to resolve to the expected App Store ID.
* Idempotent: 200 from the availability read means "already set -> no-op".
* Verification re-reads the created availability and counts available
  territories.
"""

import argparse
import base64
import http.client
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request

APP_BUNDLE_ID = "cloud.dkroeker.GaussianSplattingViewer"
APP_STORE_ID = "6787153621"
HOST = "api.appstoreconnect.apple.com"
PAGE_LIMIT = 50


def make_jwt(key_id, issuer_id, key_content):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    private_key = serialization.load_pem_private_key(key_content.encode(), password=None)
    header = {"alg": "ES256", "kid": key_id, "typ": "JWT"}
    now = int(time.time())
    payload = {"iss": issuer_id, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"}

    def b64url(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    signing_input = f"{b64url(json.dumps(header).encode())}.{b64url(json.dumps(payload).encode())}"
    der_signature = private_key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_signature)
    return f"{signing_input}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


class Asc:
    def __init__(self, jwt):
        self.jwt = jwt
        self.connection = http.client.HTTPSConnection(HOST, context=ssl.create_default_context())

    def request(self, method, path, body=None):
        headers = {"Authorization": f"Bearer {self.jwt}"}
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body)
        self.connection.request(method, path, body=payload, headers=headers)
        response = self.connection.getresponse()
        raw = response.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except ValueError:
            parsed = {"_raw": raw[:2000]}
        return response.status, parsed

    def get_all(self, path):
        """Follow pagination and return every data element."""
        items, guard = [], 0
        while path and guard < 20:
            status, body = self.request("GET", path)
            if status != 200:
                return status, items, body
            items.extend(body.get("data", []))
            next_link = (body.get("links") or {}).get("next")
            path = next_link.replace(f"https://{HOST}", "") if next_link else None
            guard += 1
        return 200, items, {}


def public_fetch(url, timeout=30):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:
        return 0, f"{exc.__class__.__name__}: {exc}"


def write_evidence(result):
    os.makedirs("out", exist_ok=True)
    with open("out/asc-inspection.json", "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)


def fail(result, message):
    result["result"] = "failed"
    result["error"] = message
    write_evidence(result)
    print(json.dumps(result, indent=2))
    raise SystemExit(1)


def public_state():
    state = {}
    for country in ("de", "us", "gb"):
        status, raw = public_fetch(
            f"https://itunes.apple.com/lookup?id={APP_STORE_ID}&country={country}")
        try:
            state[f"lookup_id_{country}"] = {"http": status,
                                             "resultCount": json.loads(raw).get("resultCount")}
        except Exception:
            state[f"lookup_id_{country}"] = {"http": status}
        status, _ = public_fetch(f"https://apps.apple.com/{country}/app/id{APP_STORE_ID}")
        state[f"store_page_{country}"] = {"http": status}
    return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", required=True,
                        help="must be exactly 'enable-availability'")
    args = parser.parse_args()
    if args.confirm != "enable-availability":
        print("refusing to run without --confirm enable-availability", file=sys.stderr)
        return 1

    result = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "target": {"bundle_id": APP_BUNDLE_ID, "app_store_id": APP_STORE_ID},
              "public_before": public_state(), "steps": {}}
    key_id = os.environ.get("ASC_API_KEY_ID", "")
    issuer_id = os.environ.get("ASC_ISSUER_ID", "")
    key_content = os.environ.get("ASC_API_KEY_CONTENT", "")
    if not (key_id and issuer_id and key_content):
        fail(result, "ASC credentials are not available to this workflow")

    asc = Asc(make_jwt(key_id, issuer_id, key_content))

    status, body = asc.request(
        "GET", f"/v1/apps?filter[bundleId]={urllib.parse.quote(APP_BUNDLE_ID)}")
    apps = body.get("data", []) if isinstance(body, dict) else []
    if status != 200 or len(apps) != 1:
        fail(result, f"app lookup failed (HTTP {status}, count={len(apps)})")
    app_id = apps[0].get("id")
    result["steps"]["app_id"] = app_id
    if app_id != APP_STORE_ID:
        fail(result, f"unexpected App Store ID {app_id!r}")

    status, body = asc.request("GET", f"/v1/apps/{app_id}/appAvailabilityV2")
    result["steps"]["availability_before"] = {"http": status, "body": body}
    if status == 200:
        result["result"] = "noop-availability-already-set"
        _, territories, _ = asc.get_all(
            f"/v2/appAvailabilities/{app_id}/territoryAvailabilities"
            f"?limit={PAGE_LIMIT}&fields[territoryAvailabilities]=available")
        available = [t for t in territories if t.get("attributes", {}).get("available")]
        result["steps"]["available_territories_after"] = len(available)
        result["public_after"] = public_state()
        write_evidence(result)
        print(json.dumps({"result": result["result"],
                          "available_territories": len(available)}, indent=2))
        return 0
    if status != 404:
        fail(result, f"unexpected availability read HTTP {status}")

    status, territories_body = asc.get_all("/v1/territories?limit=200")
    territory_codes = sorted(item["id"] for item in territories_body if item.get("id"))
    result["steps"]["territory_count_from_catalog"] = len(territory_codes)
    if len(territory_codes) < 50:
        fail(result, f"territory catalog looks wrong ({len(territory_codes)} entries)")

    payload = {
        "data": {
            "type": "appAvailabilities",
            "attributes": {"availableInNewTerritories": True},
            "relationships": {
                "app": {"data": {"type": "apps", "id": app_id}},
                "territoryAvailabilities": {
                    "data": [{"type": "territoryAvailabilities", "id": "${%s}" % code}
                             for code in territory_codes]
                },
            },
        },
        "included": [
            {
                "type": "territoryAvailabilities",
                "id": "${%s}" % code,
                "attributes": {"available": True},
                "relationships": {
                    "territory": {"data": {"type": "territories", "id": code}}
                },
            }
            for code in territory_codes
        ],
    }
    status, body = asc.request("POST", "/v2/appAvailabilities", payload)
    result["steps"]["availability_create"] = {"http": status,
                                              "body": body if status >= 400 else "ok"}
    if status not in (200, 201):
        fail(result, f"availability creation failed (HTTP {status})")

    status, body = asc.request("GET", f"/v1/apps/{app_id}/appAvailabilityV2")
    result["steps"]["availability_after"] = {"http": status,
                                             "attributes": (body.get("data") or {}).get("attributes")}
    _, territories, _ = asc.get_all(
        f"/v2/appAvailabilities/{app_id}/territoryAvailabilities"
        f"?limit={PAGE_LIMIT}&fields[territoryAvailabilities]=available")
    available = [t for t in territories if t.get("attributes", {}).get("available")]
    result["steps"]["available_territories_after"] = len(available)
    result["public_after"] = public_state()
    result["result"] = "availability-created" if available else "availability-created-but-unverified"
    write_evidence(result)
    print(json.dumps({"result": result["result"],
                      "available_territories": len(available),
                      "public_after": result["public_after"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
