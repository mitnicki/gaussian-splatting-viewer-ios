#!/usr/bin/env python3
"""Read-only App Store Connect availability/metadata probe.

GET requests only. No mutating App Store Connect endpoint is called.

Purpose: explain why an App Store version reports `READY_FOR_SALE` while the
public storefront does not list the app. Records availability relationships,
price-schedule territories and version localizations, plus the public
storefront view of an unrestricted runner.
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
    return f"{signing_input}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def asc_get(connection, jwt, path):
    try:
        connection.request("GET", path, headers={"Authorization": f"Bearer {jwt}"})
        response = connection.getresponse()
        raw = response.read().decode("utf-8", "replace")
        status = response.status
    except Exception as exc:
        return 0, f"transport error: {exc.__class__.__name__}: {exc}"
    try:
        body = json.loads(raw)
        if len(json.dumps(body)) > BODY_LIMIT:
            body = {"_truncated": True, "_head": raw[:BODY_LIMIT]}
    except ValueError:
        body = raw[:BODY_LIMIT]
    return status, body


def asc_get_raw(connection, jwt, path):
    """Like asc_get, but keeps large JSON bodies intact for local aggregation."""
    try:
        connection.request("GET", path, headers={"Authorization": f"Bearer {jwt}"})
        response = connection.getresponse()
        raw = response.read().decode("utf-8", "replace")
        status = response.status
    except Exception as exc:
        return 0, {"transport_error": f"{exc.__class__.__name__}: {exc}"}
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, {"unparsed": raw[:BODY_LIMIT]}


def public_fetch(url, timeout=30):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:
        return 0, f"{exc.__class__.__name__}: {exc}"


def main():
    key_id = os.environ.get("ASC_API_KEY_ID", "")
    issuer_id = os.environ.get("ASC_ISSUER_ID", "")
    key_content = os.environ.get("ASC_API_KEY_CONTENT", "")
    result = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "probes": {}, "summary": {}, "public": {}}
    if not (key_id and issuer_id and key_content):
        result["fatal"] = "ASC credentials are not available to this workflow"
        write(result)
        print(json.dumps(result, indent=2))
        return 0

    jwt = make_jwt(key_id, issuer_id, key_content)
    connection = http.client.HTTPSConnection("api.appstoreconnect.apple.com",
                                             context=ssl.create_default_context())

    def probe(key, path):
        status, body = asc_get(connection, jwt, path)
        result["probes"][key] = {"path": path, "http": status, "body": body}
        return status, body

    # Core app + version ground truth.
    _, apps = probe("apps_by_bundle_id",
                    f"/v1/apps?filter[bundleId]={urllib.parse.quote(APP_BUNDLE_ID)}")
    app_id = None
    if isinstance(apps, dict) and apps.get("data"):
        app_id = apps["data"][0].get("id")
    result["summary"]["asc_app_id"] = app_id

    version_id = None
    for probe_key, path in (
        ("app_with_availability_include", f"/v1/apps/{APP_STORE_ID}?include=appAvailabilityV2"),
        ("app_relationships", f"/v1/apps/{APP_STORE_ID}/relationships/appAvailabilityV2"),
        ("availability_v2", f"/v1/apps/{APP_STORE_ID}/appAvailabilityV2"),
        ("app_infos", f"/v1/apps/{APP_STORE_ID}/appInfos"),
        ("availability_v2_resource", f"/v1/appAvailabilities/{APP_STORE_ID}"),
        ("price_schedule_manual", f"/v1/appPriceSchedules/{APP_STORE_ID}/manualPrices?limit=200"),
        ("price_schedule_automatic", f"/v1/appPriceSchedules/{APP_STORE_ID}/automaticPrices?limit=200"),
        ("builds", f"/v1/apps/{APP_STORE_ID}/builds?limit=5"),
        ("app_store_versions", f"/v1/apps/{APP_STORE_ID}/appStoreVersions?limit=50"),
    ):
        status, body = probe(probe_key, path)
        if probe_key == "app_store_versions" and isinstance(body, dict):
            for item in body.get("data", []):
                if str(item.get("attributes", {}).get("versionString")) == TARGET_VERSION:
                    version_id = item.get("id")
                    result["summary"]["target_version"] = {
                        "id": version_id,
                        "appStoreState": item["attributes"].get("appStoreState"),
                        "appVersionState": item["attributes"].get("appVersionState"),
                        "releaseType": item["attributes"].get("releaseType"),
                        "downloadable": item["attributes"].get("downloadable"),
                    }

    if version_id:
        for probe_key, path in (
            ("version_localizations",
             f"/v1/appStoreVersions/{version_id}/appStoreVersionLocalizations?limit=50"),
            ("version_submission", f"/v1/appStoreVersions/{version_id}/appStoreVersionSubmission"),
            ("version_release_request", f"/v1/appStoreVersions/{version_id}/appStoreVersionReleaseRequest"),
        ):
            probe(probe_key, path)

    # Territory-level availability (App Store Connect API v2). The v1
    # `include=territoryAvailabilities` form returns 400, and the full v2
    # response is far too large for the evidence file, so fetch it raw and
    # store an aggregate: per-contentStatus territory counts, which is what
    # explains a `READY_FOR_SALE` version that no storefront lists.
    territory_http, territory = asc_get_raw(
        connection, jwt,
        f"/v2/appAvailabilities/{APP_STORE_ID}/territoryAvailabilities"
        f"?limit=200&include=territory")
    if isinstance(territory, dict) and territory.get("data"):
        status_territories = {}
        available_true = 0
        not_available = []
        for item in territory["data"]:
            attributes = item.get("attributes", {})
            relation = (item.get("relationships") or {}).get("territory") or {}
            territory_id = ((relation.get("data") or {}).get("id")
                            or item.get("id"))
            if attributes.get("available") is True:
                available_true += 1
            else:
                not_available.append(territory_id)
            for code in attributes.get("contentStatuses") or []:
                status_territories.setdefault(code, []).append(territory_id)
        result["summary"]["territory_availability"] = {
            "http": territory_http,
            "territory_count": len(territory["data"]),
            "available_true": available_true,
            "not_available": not_available[:60],
            "content_status_counts": {code: len(ids)
                                      for code, ids in sorted(status_territories.items())},
            "content_status_territories": {
                code: sorted(ids)[:120] for code, ids in sorted(status_territories.items())},
            "release_dates": sorted({
                str(item.get("attributes", {}).get("releaseDate"))
                for item in territory["data"]}),
        }
    else:
        result["summary"]["territory_availability"] = {
            "http": territory_http,
            "error": str(territory)[:400],
        }

    # Territory coverage from the price schedule when Apple returns it.
    manual = (result["probes"].get("price_schedule_manual") or {}).get("body")
    if isinstance(manual, dict) and manual.get("data"):
        territories = []
        for item in manual["data"]:
            attributes = item.get("attributes", {})
            territories.append({
                "id": item.get("id"),
                "startDate": attributes.get("startDate"),
                "endDate": attributes.get("endDate"),
            })
        result["summary"]["manual_price_entries"] = territories
        result["summary"]["manual_price_count"] = len(territories)

    # Public storefront from an unrestricted runner.
    for country in ("de", "us", "gb", "at", "ch", "fr", "nl"):
        status, raw = public_fetch(
            f"https://itunes.apple.com/lookup?id={APP_STORE_ID}&country={country}")
        try:
            result["public"][f"lookup_id_{country}"] = {
                "http": status, "resultCount": json.loads(raw).get("resultCount")}
        except Exception:
            result["public"][f"lookup_id_{country}"] = {"http": status, "raw": raw[:120]}
    for url in ("https://apps.apple.com/de/app/id6787153621",
                "https://apps.apple.com/app/id6787153621",
                "https://apps.apple.com/us/app/gaussian-splatting-viewer/id6787153621"):
        status, _ = public_fetch(url)
        result["public"][url] = {"http": status}

    write(result)
    print(json.dumps({"summary": result["summary"],
                      "probe_http": {key: value["http"] for key, value in result["probes"].items()},
                      "public": result["public"]}, indent=2))
    return 0


def write(result):
    os.makedirs("out", exist_ok=True)
    with open("out/asc-inspection.json", "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)


if __name__ == "__main__":
    sys.exit(main())
