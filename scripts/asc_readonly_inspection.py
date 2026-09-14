#!/usr/bin/env python3
"""Read-only App Store Connect + public storefront inspection.

This script performs GET requests only. It never calls a mutating App Store
Connect endpoint (no pricing, IAP, privacy, metadata, screenshot, submission or
release operation).

It records, for the configured app, the raw non-sensitive App Store Connect
responses needed to explain the difference between the reported
`appStoreState` and actual public storefront availability:

- app record (id, name, sku, primaryLocale)
- every App Store version with its `appStoreState`, `releaseType` and dates
- the linked build of the target version (number + processingState)
- app info localizations (name, subtitle, privacyPolicyUrl per locale)
- price schedule (read-only)
- availability / territory availability (read-only, both modern and legacy shape)
- the public iTunes lookup API and the public App Store web page, as seen from
  a runner outside the restricted Paperclip egress

Output: out/asc-inspection.json (also printed as a compact summary).
"""

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
BODY_LIMIT = 12000


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
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"{signing_input}.{b64url(signature)}"


def asc_get(connection, jwt, path):
    """Single read-only GET. Returns (http_status, parsed_body_or_text)."""
    try:
        connection.request("GET", path, headers={"Authorization": f"Bearer {jwt}"})
        response = connection.getresponse()
        raw = response.read().decode("utf-8", "replace")
        status = response.status
    except Exception as exc:  # transport failure must not abort the inspection
        return 0, f"transport error: {exc.__class__.__name__}: {exc}"
    try:
        body = json.loads(raw)
        text = json.dumps(body)
        if len(text) > BODY_LIMIT:
            body = {"_truncated": True, "_head": raw[:BODY_LIMIT]}
    except ValueError:
        body = raw[:BODY_LIMIT]
    return status, body


def public_fetch(url, headers=None, timeout=30):
    request = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            return response.status, raw
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:
        return 0, f"{exc.__class__.__name__}: {exc}"


def main():
    key_id = os.environ.get("ASC_API_KEY_ID", "")
    issuer_id = os.environ.get("ASC_ISSUER_ID", "")
    key_content = os.environ.get("ASC_API_KEY_CONTENT", "")
    result = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "target": {"bundle_id": APP_BUNDLE_ID, "app_store_id": APP_STORE_ID,
                         "version": TARGET_VERSION},
              "asc": {}, "public": {}, "summary": {}}
    if not (key_id and issuer_id and key_content):
        result["fatal"] = "ASC credentials are not available to this workflow"
        write(result)
        print(json.dumps(result, indent=2))
        return 0

    jwt = make_jwt(key_id, issuer_id, key_content)
    connection = http.client.HTTPSConnection("api.appstoreconnect.apple.com",
                                             context=ssl.create_default_context())

    def record(key, path):
        status, body = asc_get(connection, jwt, path)
        result["asc"][key] = {"path": path, "http": status, "body": body}
        return status, body

    status, body = record("apps_by_bundle_id",
                          f"/v1/apps?filter[bundleId]={urllib.parse.quote(APP_BUNDLE_ID)}")
    apps = body.get("data", []) if isinstance(body, dict) else []
    summary = result["summary"]
    summary["apps_by_bundle_id_count"] = len(apps)
    if status == 200 and apps:
        app_id = apps[0].get("id")
        summary["asc_app_id"] = app_id
        summary["asc_matches_ticket_id"] = (app_id == APP_STORE_ID)
        record("app", f"/v1/apps/{app_id}")

        record("app_store_versions", f"/v1/apps/{app_id}/appStoreVersions?limit=50")
        versions_raw = (result["asc"].get("app_store_versions") or {}).get("body")
        versions = []
        if isinstance(versions_raw, dict):
            for item in versions_raw.get("data", []):
                attributes = item.get("attributes", {})
                versions.append({
                    "id": item.get("id"),
                    "versionString": attributes.get("versionString"),
                    "appStoreState": attributes.get("appStoreState"),
                    "releaseType": attributes.get("releaseType"),
                    "createdDate": attributes.get("createdDate"),
                    "earliestReleaseDate": attributes.get("earliestReleaseDate"),
                    "platform": attributes.get("platform"),
                })
        summary["versions"] = versions
        target = next((version for version in versions
                       if str(version.get("versionString")) == TARGET_VERSION), None)
        if target:
            summary["target_version"] = target
            version_id = target["id"]
            record("target_version", f"/v1/appStoreVersions/{version_id}")
            record("target_version_build", f"/v1/appStoreVersions/{version_id}/build")

        status, infos = record("app_infos", f"/v1/apps/{app_id}/appInfos?limit=50")
        info_items = infos.get("data", []) if isinstance(infos, dict) else []
        localizations = []
        for info in info_items:
            info_id = info.get("id")
            record(f"app_info_{info_id}", f"/v1/appInfos/{info_id}")
            _, locs = record(f"app_info_localizations_{info_id}",
                             f"/v1/appInfos/{info_id}/appInfoLocalizations?limit=50")
            if isinstance(locs, dict):
                for entry in locs.get("data", []):
                    attributes = entry.get("attributes", {})
                    localizations.append({
                        "appInfoId": info_id,
                        "locale": attributes.get("locale"),
                        "name": attributes.get("name"),
                        "subtitle": attributes.get("subtitle"),
                        "privacyPolicyUrl": attributes.get("privacyPolicyUrl"),
                    })
        summary["localizations"] = localizations
    else:
        summary["apps_by_bundle_id_error"] = {"http": status}

    for key, path in (
        ("app_price_schedule", f"/v1/apps/{APP_STORE_ID}/appPriceSchedule"),
        ("app_availability_v2", f"/v1/apps/{APP_STORE_ID}/appAvailabilityV2"),
        ("app_availability_legacy", f"/v1/apps/{APP_STORE_ID}/appAvailability"),
        ("app_availability_v2_territories",
         f"/v1/apps/{APP_STORE_ID}/appAvailabilityV2/territoryAvailabilities?limit=200"),
    ):
        record(key, path)

    # Summarise availability/territory signals if Apple returned them.
    for key in ("app_availability_v2_territories", "app_availability_v2", "app_availability_legacy"):
        payload = (result["asc"].get(key) or {}).get("body")
        if isinstance(payload, dict) and payload.get("data") is not None:
            data = payload.get("data")
            if isinstance(data, list):
                summary.setdefault("availability", {})[key] = {"http": status, "count": len(data)}
            else:
                availability = (data or {}).get("attributes", {})
                summary.setdefault("availability", {})[key] = {
                    "http": result["asc"][key]["http"],
                    "attributes": availability,
                }

    # Public storefront as seen from the runner.
    for country in ("de", "us", "gb"):
        status, raw = public_fetch(
            f"https://itunes.apple.com/lookup?id={APP_STORE_ID}&country={country}")
        try:
            payload = json.loads(raw)
            result["public"][f"lookup_id_{country}"] = {
                "http": status, "resultCount": payload.get("resultCount")}
        except Exception:
            result["public"][f"lookup_id_{country}"] = {"http": status, "raw": raw[:200]}
        status, raw = public_fetch(
            "https://itunes.apple.com/lookup?bundleId="
            f"{urllib.parse.quote(APP_BUNDLE_ID)}&country={country}")
        try:
            payload = json.loads(raw)
            result["public"][f"lookup_bundle_{country}"] = {
                "http": status, "resultCount": payload.get("resultCount")}
        except Exception:
            result["public"][f"lookup_bundle_{country}"] = {"http": status, "raw": raw[:200]}
        status, _ = public_fetch(f"https://apps.apple.com/{country}/app/id{APP_STORE_ID}")
        result["public"][f"store_page_{country}"] = {"http": status}

    write(result)
    print(json.dumps({"summary": result["summary"], "public": result["public"]}, indent=2))
    return 0


def write(result):
    os.makedirs("out", exist_ok=True)
    with open("out/asc-inspection.json", "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)


if __name__ == "__main__":
    sys.exit(main())
