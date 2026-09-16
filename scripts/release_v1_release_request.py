#!/usr/bin/env python3
"""Guarded App Store release request for the exact approved target (DKR-7041).

Why this exists
---------------
Apple reports App Store version 1.0 of app `6787153621` as
`appStoreState = READY_FOR_SALE` / `appVersionState = READY_FOR_DISTRIBUTION`
with `downloadable = true`, yet the app appears in NO storefront: every
`itunes.apple.com/lookup?id=6787153621` returns resultCount 0 and the public
store pages return 404. The v2 territory availability aggregate reports
`AVAILABLE_FOR_SALE_UNRELEASED_APP` for all 175 territories, i.e. Apple's own
data says the app is still unreleased.

This script performs the single remaining in-product action that can publish an
already approved version - the App Store Connect release request - and records
Apple's authoritative answer.

Guard rails
-----------
* Resolves the app through the bundle id and refuses to continue unless the app
  id is exactly 6787153621.
* Refuses unless there is exactly one version "1.0" and its linked build is
  exactly 187 and VALID.
* Refuses unless the caller passes --confirm release-v1.0 explicitly.
* Records the pre-state, the exact POST response (HTTP status and Apple error
  codes), the post-state, and the public storefront view afterwards.
* Touches no metadata, price, IAP, privacy, screenshot or submission endpoint.
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
TARGET_VERSION = "1.0"
TARGET_BUILD = "187"
CONFIRM_TOKEN = "release-v1.0"


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


def asc(connection, jwt, method, path, body=None):
    headers = {"Authorization": f"Bearer {jwt}"}
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body)
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    raw = response.read().decode("utf-8", "replace")
    try:
        parsed = json.loads(raw) if raw.strip() else {}
    except ValueError:
        parsed = {"unparsed": raw[:800]}
    return response.status, parsed


def error_codes(body):
    if isinstance(body, dict) and isinstance(body.get("errors"), list):
        return [{"code": e.get("code"), "title": e.get("title"), "detail": e.get("detail")}
                for e in body["errors"]]
    return None


def public_lookup():
    url = f"https://itunes.apple.com/lookup?id={APP_STORE_ID}&country=de"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8", "replace"))
            results = body.get("results") or []
            return {"http": response.status, "resultCount": body.get("resultCount"),
                    "first": results[0] if results else None}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{exc.__class__.__name__}: {exc}"}


def resolve_target(connection, jwt, evidence):
    status, data = asc(connection, jwt, "GET",
                       f"/v1/apps?filter[bundleId]={urllib.parse.quote(APP_BUNDLE_ID)}")
    evidence["probes"]["apps_by_bundle_id"] = {"http": status, "error_codes": error_codes(data)}
    apps = data.get("data") if isinstance(data, dict) else None
    if status != 200 or not apps or len(apps) != 1:
        raise SystemExit(f"ABORT: app lookup failed (HTTP {status}, count={len(apps or [])})")
    app_id = apps[0].get("id")
    if app_id != APP_STORE_ID:
        raise SystemExit(f"ABORT: unexpected app id {app_id!r}, expected {APP_STORE_ID!r}")

    status, data = asc(connection, jwt, "GET",
                       f"/v1/apps/{APP_STORE_ID}/appStoreVersions?limit=200")
    evidence["probes"]["app_store_versions"] = {"http": status, "error_codes": error_codes(data)}
    matches = [v for v in (data.get("data") or [])
               if str((v.get("attributes") or {}).get("versionString")) == TARGET_VERSION]
    if status != 200 or len(matches) != 1:
        raise SystemExit(f"ABORT: expected exactly one version {TARGET_VERSION}, found {len(matches)}")
    version = matches[0]
    version_id = version["id"]
    attributes = version.get("attributes") or {}

    status, data = asc(connection, jwt, "GET", f"/v1/appStoreVersions/{version_id}/build")
    build = (data.get("data") or {}) if isinstance(data, dict) else {}
    build_attributes = (build.get("attributes") or {}) if isinstance(build, dict) else {}
    build_number = str(build_attributes.get("version", ""))
    build_state = build_attributes.get("processingState", "UNKNOWN")
    evidence["probes"]["version_build"] = {"http": status, "build": build_number,
                                           "processingState": build_state,
                                           "expired": build_attributes.get("expired")}
    if build_number != TARGET_BUILD:
        raise SystemExit(f"ABORT: linked build is {build_number!r}, expected {TARGET_BUILD!r}")
    if build_state != "VALID":
        raise SystemExit(f"ABORT: linked build {build_number} is {build_state}, not VALID")

    return {
        "version_id": version_id,
        "version": attributes.get("versionString"),
        "appStoreState": attributes.get("appStoreState"),
        "appVersionState": attributes.get("appVersionState"),
        "releaseType": attributes.get("releaseType"),
        "earliestReleaseDate": attributes.get("earliestReleaseDate"),
        "downloadable": attributes.get("downloadable"),
        "build": build_number,
        "build_processing": build_state,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", required=True,
                        help="must be exactly 'release-v1.0' to actually send the release request")
    parser.add_argument("--dry-run", action="store_true",
                        help="read the state and record it without sending the release request")
    args = parser.parse_args()

    if args.confirm != CONFIRM_TOKEN:
        raise SystemExit(f"ABORT: --confirm must be {CONFIRM_TOKEN!r}")

    key_id = os.environ.get("ASC_API_KEY_ID", "")
    issuer_id = os.environ.get("ASC_ISSUER_ID", "")
    key_content = os.environ.get("ASC_API_KEY_CONTENT", "")
    evidence = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "action": "release_v1",
        "probes": {},
        "summary": {},
    }
    if not (key_id and issuer_id and key_content):
        evidence["fatal"] = "ASC credentials are not available to this workflow"
        write(evidence)
        print(json.dumps(evidence, indent=2))
        return 0

    jwt = make_jwt(key_id, issuer_id, key_content)
    connection = http.client.HTTPSConnection(
        "api.appstoreconnect.apple.com", context=ssl.create_default_context())
    try:
        before = resolve_target(connection, jwt, evidence)
        evidence["summary"]["pre_state"] = before
        evidence["summary"]["public_before"] = public_lookup()
        print("PRE  " + json.dumps(before))
        print("PUBLIC-BEFORE " + json.dumps(evidence["summary"]["public_before"]))

        action = "dry-run"
        if not args.dry_run:
            payload = {
                "data": {
                    "type": "appStoreVersionReleaseRequests",
                    "relationships": {
                        "appStoreVersion": {
                            "data": {"type": "appStoreVersions", "id": before["version_id"]}
                        }
                    },
                }
            }
            status, body = asc(connection, jwt, "POST",
                               "/v1/appStoreVersionReleaseRequests", payload)
            evidence["probes"]["release_request"] = {
                "http": status,
                "error_codes": error_codes(body),
                "data": (body.get("data") if isinstance(body, dict) else None),
            }
            action = "release-request-sent" if status in (200, 201) else "release-request-rejected"
            print("RELEASE-REQUEST http=" + str(status) + " body=" + json.dumps(body)[:800])

        # Re-read the authoritative state and the public catalog afterwards.
        evidence["summary"]["action"] = action
        after = resolve_target(connection, jwt, evidence)
        evidence["summary"]["post_state"] = after
        time.sleep(20)
        evidence["summary"]["public_after"] = public_lookup()
        print("POST " + json.dumps(after))
        print("PUBLIC-AFTER " + json.dumps(evidence["summary"]["public_after"]))
    finally:
        connection.close()

    write(evidence)
    return 0


def write(evidence):
    os.makedirs("out", exist_ok=True)
    with open("out/asc-inspection.json", "w", encoding="utf-8") as handle:
        json.dump(evidence, handle, indent=2, sort_keys=True)


if __name__ == "__main__":
    sys.exit(main())
