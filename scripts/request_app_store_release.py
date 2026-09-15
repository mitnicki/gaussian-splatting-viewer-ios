#!/usr/bin/env python3
"""Guarded release request for the approved, unpublished App Store version.

Context: app 6787153621 / version 1.0 (approved 2026-08-01) reports
`appStoreState = READY_FOR_SALE` and `downloadable = true`, but Apple never
emitted a release event (`earliestReleaseDate = null`, `releaseDate = null` in
all 175 territories) and no storefront lists the app. The automatic
(AFTER_APPROVAL) release never fired -- plausibly because App Availability was
only created on 2026-09-14, long after approval.

This script exercises Apple's documented release path, nothing else:

  1. read the target version (read-only),
  2. POST /v1/appStoreVersionReleaseRequests for that version,
  3. if Apple rejects it because the version is not PENDING_DEVELOPER_RELEASE,
     switch only the *release timing* attribute to MANUAL and retry once,
  4. if the release still cannot be requested, restore the original release
     timing so the version is left exactly as found,
  5. re-read version state, territory sellability and the public storefront.

It never touches price, IAPs, privacy, metadata or app content. Requires the
explicit confirm token so it cannot run by accident.
"""

import base64
import http.client
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

APP_BUNDLE_ID = "cloud.dkroeker.GaussianSplattingViewer"
APP_STORE_ID = "6787153621"
TARGET_VERSION = "1.0"
CONFIRM_TOKEN = "request-approved-release"
BODY_LIMIT = 20000


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


def asc_call(connection, jwt, method, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": f"Bearer {jwt}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8", "replace")
        status = response.status
    except Exception as exc:  # noqa: BLE001
        return 0, {"transport_error": f"{exc.__class__.__name__}: {exc}"}
    try:
        parsed = json.loads(raw)
    except ValueError:
        parsed = {"unparsed": raw[:400]}
    if isinstance(parsed, dict) and len(json.dumps(parsed)) > BODY_LIMIT:
        parsed = {"_truncated": True, "_head": json.dumps(parsed)[:BODY_LIMIT]}
    return status, parsed


def error_codes(body):
    if isinstance(body, dict) and isinstance(body.get("errors"), list):
        return [{"code": e.get("code"), "title": e.get("title"), "detail": e.get("detail")}
                for e in body["errors"]]
    return []


def public_json(url, timeout=30):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return exc.code, {"http_error": exc.code}
    except Exception as exc:  # noqa: BLE001
        return 0, {"transport_error": f"{exc.__class__.__name__}: {exc}"}


def main():
    key_id = os.environ.get("ASC_API_KEY_ID", "")
    issuer_id = os.environ.get("ASC_ISSUER_ID", "")
    key_content = os.environ.get("ASC_API_KEY_CONTENT", "")
    confirm = os.environ.get("CONFIRM_TOKEN", "")
    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "request_release",
        "steps": [],
        "public": {},
    }

    def step(name, status, detail):
        result["steps"].append({"step": name, "http": status, "detail": detail})
        print(f"[{name}] http={status} {json.dumps(detail)[:600]}", flush=True)

    if confirm != CONFIRM_TOKEN:
        result["fatal"] = "confirmation token missing"
        write(result)
        return 2
    if not (key_id and issuer_id and key_content):
        result["fatal"] = "ASC credentials are not available to this workflow"
        write(result)
        return 0

    jwt = make_jwt(key_id, issuer_id, key_content)
    connection = http.client.HTTPSConnection(
        "api.appstoreconnect.apple.com", context=ssl.create_default_context())

    def version_state():
        status, body = asc_call(
            connection, jwt, "GET",
            f"/v1/apps/{APP_STORE_ID}/appStoreVersions?limit=50"
            "&fields[appStoreVersions]=versionString,appStoreState,appVersionState,"
            "releaseType,earliestReleaseDate,downloadable,createdDate&include=build")
        if isinstance(body, dict):
            for item in body.get("data") or []:
                if str(item.get("attributes", {}).get("versionString")) == TARGET_VERSION:
                    attributes = item["attributes"]
                    return item.get("id"), {
                        "appStoreState": attributes.get("appStoreState"),
                        "appVersionState": attributes.get("appVersionState"),
                        "releaseType": attributes.get("releaseType"),
                        "earliestReleaseDate": attributes.get("earliestReleaseDate"),
                        "releaseDate": attributes.get("releaseDate"),
                        "downloadable": attributes.get("downloadable"),
                    }
        return None, {"http": status, "errors": error_codes(body)}

    version_id, before = version_state()
    step("read_version_before", 200 if version_id else 0,
         {"version_id": version_id, "state": before})
    if not version_id:
        result["fatal"] = "target version 1.0 not found"
        write(result)
        return 1

    release_payload = {
        "data": {
            "type": "appStoreVersionReleaseRequests",
            "relationships": {
                "appStoreVersion": {"data": {"type": "appStoreVersions", "id": version_id}}
            },
        }
    }

    status, body = asc_call(connection, jwt, "POST",
                            "/v1/appStoreVersionReleaseRequests", release_payload)
    first = {"http": status, "errors": error_codes(body),
             "data_id": ((body.get("data") or {}).get("id")
                         if isinstance(body, dict) and isinstance(body.get("data"), dict) else None)}
    step("release_request_attempt_1", status, first)

    if status not in (200, 201):
        # Apple only accepts a release request for a version that is explicitly
        # waiting for the developer. Switch the *release timing* attribute only
        # (no metadata/price/privacy/content change) and retry exactly once.
        patch_status, patch_body = asc_call(
            connection, jwt, "PATCH", f"/v1/appStoreVersions/{version_id}",
            {"data": {"type": "appStoreVersions", "id": version_id,
                      "attributes": {"releaseType": "MANUAL"}}})
        step("patch_release_type_manual", patch_status,
             {"errors": error_codes(patch_body)})

        mid_id, mid_state = version_state()
        step("read_version_after_patch", 200 if mid_id else 0, mid_state)

        status2, body2 = asc_call(connection, jwt, "POST",
                                  "/v1/appStoreVersionReleaseRequests", release_payload)
        step("release_request_attempt_2", status2,
             {"errors": error_codes(body2),
              "data_id": ((body2.get("data") or {}).get("id")
                          if isinstance(body2, dict) and isinstance(body2.get("data"), dict)
                          else None)})

        if status2 not in (200, 201) and patch_status in (200, 201):
            # Leave the version exactly as found: restore the original release
            # timing instead of parking it in PENDING_DEVELOPER_RELEASE.
            restore_status, restore_body = asc_call(
                connection, jwt, "PATCH", f"/v1/appStoreVersions/{version_id}",
                {"data": {"type": "appStoreVersions", "id": version_id,
                          "attributes": {"releaseType": "AFTER_APPROVAL"}}})
            step("restore_release_type", restore_status,
                 {"errors": error_codes(restore_body)})

    after_id, after = version_state()
    step("read_version_after", 200 if after_id else 0, after)
    result["release_requested"] = status in (200, 201) or any(
        s["step"] == "release_request_attempt_2" and s["http"] in (200, 201)
        for s in result["steps"])

    status, territory = asc_call(
        connection, jwt, "GET",
        f"/v2/appAvailabilities/{APP_STORE_ID}/territoryAvailabilities"
        "?limit=200&include=territory")
    if isinstance(territory, dict) and territory.get("data"):
        counts = {}
        release_dates = set()
        for item in territory["data"]:
            attributes = item.get("attributes", {})
            release_dates.add(str(attributes.get("releaseDate")))
            for code in attributes.get("contentStatuses") or []:
                counts[code] = counts.get(code, 0) + 1
        result["territory_after"] = {
            "territory_count": len(territory["data"]),
            "content_status_counts": counts,
            "release_dates": sorted(release_dates),
        }
    else:
        result["territory_after"] = {"http": status, "errors": error_codes(territory)}

    for country in ("de", "us", "gb", "at"):
        lookup_status, lookup = public_json(
            f"https://itunes.apple.com/lookup?id={APP_STORE_ID}&country={country}")
        result["public"][country] = {
            "http": lookup_status,
            "resultCount": lookup.get("resultCount") if isinstance(lookup, dict) else None,
        }

    write(result)
    print(json.dumps({"generated_at": result["generated_at"],
                      "release_requested": result.get("release_requested"),
                      "steps": result["steps"],
                      "territory_after": result.get("territory_after"),
                      "public": result["public"]}, indent=2)[:6000])
    return 0


def write(result):
    os.makedirs("out", exist_ok=True)
    with open("out/asc-inspection.json", "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)


if __name__ == "__main__":
    sys.exit(main())
