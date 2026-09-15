#!/usr/bin/env python3
"""Deep, read-only App Store Connect + public-storefront diagnosis.

GET requests only. No mutating App Store Connect endpoint is called.

Purpose: after availability was created and the approved v1.0 still appears in
no storefront, close the remaining *agent-visible* hypotheses that the earlier
inspection pass did not cover:

  1. App-level metadata completeness (App Information localizations, privacy
     policy URL, primary category, age rating) -- a missing required app-level
     field can keep an approved version out of every storefront.
  2. Export compliance on the exact release build.
  3. App Store version *experiments* / product page optimization, which block
     the automatic release of a version.
  4. Price schedule base territory + manual price validity window.
  5. Territory-level content statuses (authoritative Apple sellability signal).
  6. Public storefront: presence of the app itself, and of any other app by the
     same developer/seller (public evidence for/against an account-level
     paid-agreement problem, which no ASC API exposes).
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
RELEASE_BUILD_ID = "3d00875e-0cfa-4105-9a6c-6ead6af8f10e"
CONTROL_APP_ID = "310633997"  # WhatsApp: proves the public lookup channel works
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


def asc_get(connection, jwt, path, limit=BODY_LIMIT):
    try:
        connection.request("GET", path, headers={"Authorization": f"Bearer {jwt}"})
        response = connection.getresponse()
        raw = response.read().decode("utf-8", "replace")
        status = response.status
    except Exception as exc:  # noqa: BLE001
        return 0, {"transport_error": f"{exc.__class__.__name__}: {exc}"}
    try:
        body = json.loads(raw)
    except ValueError:
        return status, {"unparsed": raw[:400]}
    if limit and len(json.dumps(body)) > limit:
        return status, {"_truncated": True, "_head": raw[:limit]}
    return status, body


def public_json(url, timeout=30):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return exc.code, {"http_error": exc.code}
    except Exception as exc:  # noqa: BLE001
        return 0, {"transport_error": f"{exc.__class__.__name__}: {exc}"}


def public_status(url, timeout=30):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:  # noqa: BLE001
        return 0


def main():
    key_id = os.environ.get("ASC_API_KEY_ID", "")
    issuer_id = os.environ.get("ASC_ISSUER_ID", "")
    key_content = os.environ.get("ASC_API_KEY_CONTENT", "")
    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "asc_deep_diagnosis",
        "probes": {},
        "findings": {},
        "public": {},
    }

    def record(key, path, body, status):
        result["probes"][key] = {"path": path, "http": status, "body": body}
        return body

    if not (key_id and issuer_id and key_content):
        result["fatal"] = "ASC credentials are not available to this workflow"
        write(result)
        print(json.dumps(result, indent=2)[:4000])
        return 0

    jwt = make_jwt(key_id, issuer_id, key_content)
    connection = http.client.HTTPSConnection(
        "api.appstoreconnect.apple.com", context=ssl.create_default_context())

    def get(key, path, limit=BODY_LIMIT):
        status, body = asc_get(connection, jwt, path, limit)
        record(key, path, body, status)
        return status, body

    findings = result["findings"]

    # --- 1. app-level metadata completeness -------------------------------
    meta = {}
    status, infos = get("app_infos", f"/v1/apps/{APP_STORE_ID}/appInfos?limit=10")
    app_info_id = None
    if isinstance(infos, dict) and infos.get("data"):
        info = infos["data"][0]
        app_info_id = info.get("id")
        meta["app_info_state"] = info.get("attributes", {}).get("state")
        meta["app_store_age_rating"] = info.get("attributes", {}).get("appStoreAgeRating")
    if app_info_id:
        _, locs = get("app_info_localizations",
                      f"/v1/appInfos/{app_info_id}/appInfoLocalizations?limit=50")
        entries = []
        if isinstance(locs, dict):
            for item in locs.get("data") or []:
                attributes = item.get("attributes", {})
                entries.append({
                    "locale": attributes.get("locale"),
                    "name": attributes.get("name"),
                    "subtitle": attributes.get("subtitle"),
                    "privacyPolicyUrl": attributes.get("privacyPolicyUrl"),
                    "privacyChoicesUrl": attributes.get("privacyChoicesUrl"),
                    "privacyPolicyText_present": bool(attributes.get("privacyPolicyText")),
                })
        meta["app_info_localizations"] = entries
        _, category = get("app_info_primary_category",
                         f"/v1/appInfos/{app_info_id}/relationships/primaryCategory")
        if isinstance(category, dict):
            meta["primary_category_id"] = (category.get("data") or {}).get("id")
        _, age_rating = get("age_rating_declaration",
                            f"/v1/appInfos/{app_info_id}/ageRatingDeclaration")
        if isinstance(age_rating, dict) and age_rating.get("data"):
            attributes = age_rating["data"].get("attributes", {})
            non_false = {k: v for k, v in attributes.items()
                         if v not in (None, False, [], "NONE", "NOT_APPLICABLE")}
            meta["age_rating_non_default_flags"] = non_false
    findings["app_level_metadata"] = meta

    # --- 2. export compliance on the exact release build ------------------
    _, build = get("release_build",
                   f"/v1/builds/{RELEASE_BUILD_ID}?fields[builds]=version,processingState,"
                   "expired,usesNonExemptEncryption,buildAudienceType,expirationDate,"
                   "minOsVersion,uploadedDate,iconAssetToken")
    if isinstance(build, dict) and build.get("data"):
        attributes = build["data"].get("attributes", {})
        findings["release_build"] = {
            "version": attributes.get("version"),
            "processingState": attributes.get("processingState"),
            "expired": attributes.get("expired"),
            "usesNonExemptEncryption": attributes.get("usesNonExemptEncryption"),
            "buildAudienceType": attributes.get("buildAudienceType"),
            "expirationDate": attributes.get("expirationDate"),
            "minOsVersion": attributes.get("minOsVersion"),
        }

    # --- 3. experiments / product page optimization on the version --------
    version_id = None
    _, versions = get("app_store_versions_experiments_src",
                      f"/v1/apps/{APP_STORE_ID}/appStoreVersions?limit=50"
                      "&fields[appStoreVersions]=versionString,appStoreState,appVersionState,"
                      "releaseType,earliestReleaseDate,releaseDate,downloadable,createdDate,build")
    if isinstance(versions, dict):
        for item in versions.get("data") or []:
            if str(item.get("attributes", {}).get("versionString")) == TARGET_VERSION:
                version_id = item.get("id")
    findings["target_version_id"] = version_id
    experiments = {}
    if version_id:
        for key, path in (
            ("version_experiments_v1",
             f"/v1/appStoreVersions/{version_id}/appStoreVersionExperiments?limit=50"),
            ("version_experiments_v2",
             f"/v2/appStoreVersions/{version_id}/appStoreVersionExperiments?limit=50"),
        ):
            status, body = get(key, path)
            experiments[key] = {
                "http": status,
                "count": len(body.get("data") or []) if isinstance(body, dict) else None,
                "states": [i.get("attributes", {}).get("state")
                           for i in (body.get("data") or [])] if isinstance(body, dict) else None,
                "error": (body.get("errors") or [{}])[0].get("code")
                if isinstance(body, dict) and body.get("errors") else None,
            }
    findings["version_experiments"] = experiments

    # --- 4. price schedule: base territory + manual price window ----------
    price = {}
    status, schedule = get("price_schedule",
                           f"/v1/appPriceSchedules/{APP_STORE_ID}"
                           "?include=baseTerritory,manualPrices,automaticPrices")
    if isinstance(schedule, dict):
        data = schedule.get("data") or {}
        attributes = (data.get("attributes") or {}) if isinstance(data, dict) else {}
        price["schedule_attributes"] = attributes
        for included in schedule.get("included") or []:
            if included.get("type") == "territories":
                price["base_territory"] = included.get("id")
            if included.get("type") == "appPrices":
                price.setdefault("manual_prices", []).append({
                    "startDate": (included.get("attributes") or {}).get("startDate"),
                    "endDate": (included.get("attributes") or {}).get("endDate"),
                })
    findings["price_schedule"] = price

    # --- 5. territory-level sellability -----------------------------------
    status, territory = asc_get(
        connection, jwt,
        f"/v2/appAvailabilities/{APP_STORE_ID}/territoryAvailabilities"
        "?limit=200&include=territory", limit=0)
    record("territory_availabilities",
           f"/v2/appAvailabilities/{APP_STORE_ID}/territoryAvailabilities",
           {"_aggregated": True}, status)
    if isinstance(territory, dict) and territory.get("data"):
        counts = {}
        release_dates = set()
        unavailable = 0
        for item in territory["data"]:
            attributes = item.get("attributes", {})
            if attributes.get("available") is not True:
                unavailable += 1
            release_dates.add(str(attributes.get("releaseDate")))
            for code in attributes.get("contentStatuses") or []:
                counts[code] = counts.get(code, 0) + 1
        findings["territory_availability"] = {
            "territory_count": len(territory["data"]),
            "available_true": len(territory["data"]) - unavailable,
            "not_available_count": unavailable,
            "content_status_counts": counts,
            "release_dates": sorted(release_dates),
        }
    else:
        findings["territory_availability"] = {"http": status, "error": str(territory)[:300]}

    # --- 6. public storefront --------------------------------------------
    public = result["public"]
    for country in ("de", "us"):
        status, body = public_json(
            f"https://itunes.apple.com/lookup?id={APP_STORE_ID}&country={country}")
        public[f"lookup_self_{country}"] = {
            "http": status,
            "resultCount": body.get("resultCount") if isinstance(body, dict) else None,
        }
    control_status, control = public_json(
        f"https://itunes.apple.com/lookup?id={CONTROL_APP_ID}&country=de")
    public["lookup_control_de"] = {
        "http": control_status,
        "resultCount": control.get("resultCount") if isinstance(control, dict) else None,
        "control_ok": bool(isinstance(control, dict) and control.get("resultCount") == 1),
    }
    public["store_page_de"] = {
        "http": public_status(f"https://apps.apple.com/de/app/id{APP_STORE_ID}")}
    for country in ("de", "us"):
        status, body = public_json(
            "https://itunes.apple.com/search?term="
            + urllib.parse.quote("Gaussian Splatting Viewer")
            + f"&entity=software&limit=10&country={country}")
        entries = []
        if isinstance(body, dict):
            for item in body.get("results") or []:
                entries.append({
                    "trackId": item.get("trackId"),
                    "trackName": item.get("trackName"),
                    "sellerName": item.get("sellerName"),
                    "artistId": item.get("artistId"),
                    "price": item.get("price"),
                    "currency": item.get("currency"),
                })
        public[f"search_name_{country}"] = {"http": status, "count": len(entries),
                                            "results": entries}
    # Any other app by the same seller? Public evidence about the account's
    # ability to sell (Agreements/Tax/Banking is not exposed by any ASC API).
    for country in ("de", "us"):
        status, body = public_json(
            "https://itunes.apple.com/search?term="
            + urllib.parse.quote("Dennis Kroeker")
            + f"&entity=software&limit=20&country={country}")
        entries = []
        if isinstance(body, dict):
            for item in body.get("results") or []:
                entries.append({
                    "trackId": item.get("trackId"),
                    "trackName": item.get("trackName"),
                    "sellerName": item.get("sellerName"),
                    "artistId": item.get("artistId"),
                    "price": item.get("price"),
                    "currency": item.get("currency"),
                })
        public[f"search_seller_{country}"] = {"http": status, "count": len(entries),
                                              "results": entries}

    write(result)
    print(json.dumps({"generated_at": result["generated_at"],
                      "findings": findings,
                      "probe_http": {k: v["http"] for k, v in result["probes"].items()},
                      "public": public}, indent=2)[:8000])
    return 0


def write(result):
    os.makedirs("out", exist_ok=True)
    with open("out/asc-inspection.json", "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)


if __name__ == "__main__":
    sys.exit(main())
