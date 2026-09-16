#!/usr/bin/env python3
"""Read-only App Store Connect price/localization availability probe.

GET requests only. No mutating App Store Connect endpoint is called.

Purpose (DKR-7041): the approved v1.0 version reports
`appStoreState = READY_FOR_SALE` / `appVersionState = READY_FOR_DISTRIBUTION`
while no App Store storefront lists the app, and the v2 territory availability
aggregate reports `CANNOT_SELL` for all 175 territories plus
`TRADER_STATUS_NOT_PROVIDED` for the 27 EU states.

This probe answers the two questions that remain open from an unrestricted
runner:

  1. Is a sellable price actually in effect (the authorized 2,99 EUR), or is
     the price schedule empty/unscheduled - which would explain CANNOT_SELL?
  2. What do the app-level (appInfos) localizations carry for the published
     store page (name, privacy policy URL) and which locales are configured?

Everything is read with GET. Large collections are aggregated so the evidence
file stays small.
"""

import base64
import http.client
import json
import os
import ssl
import sys
import time

APP_BUNDLE_ID = "cloud.dkroeker.GaussianSplattingViewer"
APP_STORE_ID = "6787153621"
BODY_LIMIT = 6000
EU_TRADER_STATUS_COUNT = 27


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
    """GET only. Returns (http_status, parsed_body)."""
    try:
        connection.request("GET", path, headers={"Authorization": f"Bearer {jwt}"})
        response = connection.getresponse()
        raw = response.read().decode("utf-8", "replace")
        status = response.status
    except Exception as exc:  # noqa: BLE001
        return 0, {"transport_error": f"{exc.__class__.__name__}: {exc}"}
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, {"unparsed": raw[:BODY_LIMIT]}


def err_codes(body):
    if isinstance(body, dict) and isinstance(body.get("errors"), list):
        return [e.get("code") for e in body["errors"]]
    return None


def price_summary(body):
    """Aggregate a manualPrices/automaticPrices response."""
    if not isinstance(body, dict):
        return {"error": "no dict body"}
    data = body.get("data") or []
    prices = {}
    territories = set()
    for entry in data:
        attributes = entry.get("attributes") or {}
        relation = (entry.get("relationships") or {})
        territory = ((relation.get("territory") or {}).get("data") or {}).get("id")
        if territory:
            territories.add(territory)
        customer = None
        currency = None
        point_rel = ((relation.get("appPricePoint") or {}).get("data") or {}).get("id")
        for included in body.get("included") or []:
            if included.get("type") != "appPricePoints":
                continue
            if point_rel and included.get("id") != point_rel:
                continue
            included_attributes = included.get("attributes") or {}
            customer = included_attributes.get("customerPrice")
            currency = included_attributes.get("currency")
        key = f"{customer} {currency}".strip() or "unresolved"
        prices.setdefault(key, 0)
        prices[key] += 1
    return {
        "entry_count": len(data),
        "territory_count": len(territories),
        "price_counts": prices,
        "sample_entry_ids": [entry.get("id") for entry in data[:2]],
        "sample_attributes": [entry.get("attributes") for entry in data[:3]],
        "included_types": sorted({item.get("type") for item in (body.get("included") or [])}),
    }


def main():
    key_id = os.environ.get("ASC_API_KEY_ID", "")
    issuer_id = os.environ.get("ASC_ISSUER_ID", "")
    key_content = os.environ.get("ASC_API_KEY_CONTENT", "")
    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "action": "price_check",
        "probes": {},
        "summary": {},
    }
    if not (key_id and issuer_id and key_content):
        result["fatal"] = "ASC credentials are not available to this workflow"
        write(result)
        print(json.dumps(result, indent=2))
        return 0

    jwt = make_jwt(key_id, issuer_id, key_content)
    connection = http.client.HTTPSConnection(
        "api.appstoreconnect.apple.com", context=ssl.create_default_context())

    def probe(key, path):
        status, body = asc_get(connection, jwt, path)
        codes = err_codes(body)
        result["probes"][key] = {"path": path, "http": status, "error_codes": codes}
        if status != 200:
            result["probes"][key]["body_head"] = json.dumps(body)[:600]
        return status, body

    # 1. Price schedule root + explicit price-point include so the authorized
    #    price can be read in a single call (no /v2/appPrices follow-up).
    schedule_http, schedule_body = probe("price_schedule", f"/v1/appPriceSchedules/{APP_STORE_ID}")
    if schedule_http == 200 and isinstance(schedule_body, dict):
        result["summary"]["price_schedule_root"] = schedule_body.get("data")

    manual_path = (f"/v1/appPriceSchedules/{APP_STORE_ID}/manualPrices?limit=200"
                   "&include=appPricePoint,territory"
                   "&fields[appPricePoints]=customerPrice,proceeds")
    automatic_path = (f"/v1/appPriceSchedules/{APP_STORE_ID}/automaticPrices?limit=200"
                      "&include=appPricePoint,territory"
                      "&fields[appPricePoints]=customerPrice,proceeds")

    manual_http, manual_body = probe("manual_prices", manual_path)
    if manual_http == 200:
        result["summary"]["manual_prices"] = price_summary(manual_body)
    else:
        result["summary"]["manual_prices"] = {"http": manual_http, "error": err_codes(manual_body)}

    automatic_http, automatic_body = probe("automatic_prices", automatic_path)
    if automatic_http == 200:
        result["summary"]["automatic_prices"] = price_summary(automatic_body)
    else:
        result["summary"]["automatic_prices"] = {"http": automatic_http,
                                                 "error": err_codes(automatic_body)}

    # 2. App-level localizations: published name + privacy policy URL.
    info_http, infos = probe(
        "app_infos",
        f"/v1/apps/{APP_STORE_ID}/appInfos"
        "?include=appInfoLocalizations"
        "&fields[appInfoLocalizations]=locale,name,subtitle,privacyPolicyUrl,privacyPolicyText")
    if info_http == 200 and isinstance(infos, dict):
        localizations = []
        for included in infos.get("included") or []:
            if included.get("type") != "appInfoLocalizations":
                continue
            attributes = included.get("attributes") or {}
            localizations.append({
                "locale": attributes.get("locale"),
                "name": attributes.get("name"),
                "subtitle": attributes.get("subtitle"),
                "privacyPolicyUrl": attributes.get("privacyPolicyUrl"),
                "privacyPolicyTextPresent": bool(attributes.get("privacyPolicyText")),
            })
        result["summary"]["app_info_localizations"] = localizations

    # 3. Version localizations (DE/EN store copy + support URL).
    _, versions = probe(
        "app_store_versions",
        f"/v1/apps/{APP_STORE_ID}/appStoreVersions?limit=10"
        "&fields[appStoreVersions]=versionString,appStoreState,appVersionState,releaseType,"
        "earliestReleaseDate,downloadable,createdDate")
    version_id = None
    if isinstance(versions, dict) and versions.get("data"):
        for item in versions["data"]:
            if str((item.get("attributes") or {}).get("versionString")) == "1.0":
                version_id = item.get("id")
        result["summary"]["versions"] = [
            {
                "id": item.get("id"),
                "versionString": (item.get("attributes") or {}).get("versionString"),
                "appStoreState": (item.get("attributes") or {}).get("appStoreState"),
                "appVersionState": (item.get("attributes") or {}).get("appVersionState"),
                "releaseType": (item.get("attributes") or {}).get("releaseType"),
                "earliestReleaseDate": (item.get("attributes") or {}).get("earliestReleaseDate"),
                "downloadable": (item.get("attributes") or {}).get("downloadable"),
            }
            for item in versions["data"]
        ]

    if version_id:
        localization_http, localizations = probe(
            "version_localizations",
            f"/v1/appStoreVersions/{version_id}/appStoreVersionLocalizations?limit=50"
            "&fields[appStoreVersionLocalizations]=locale,description,keywords,supportUrl,"
            "marketingUrl,whatsNew")
        if localization_http == 200 and isinstance(localizations, dict):
            result["summary"]["version_localizations"] = [
                {
                    "locale": (item.get("attributes") or {}).get("locale"),
                    "hasDescription": bool((item.get("attributes") or {}).get("description")),
                    "hasKeywords": bool((item.get("attributes") or {}).get("keywords")),
                    "supportUrl": (item.get("attributes") or {}).get("supportUrl"),
                    "marketingUrl": (item.get("attributes") or {}).get("marketingUrl"),
                    "hasWhatsNew": bool((item.get("attributes") or {}).get("whatsNew")),
                }
                for item in (localizations.get("data") or [])
            ]

    # 4. Per-territory detail for the two markets that matter (DEU primary, USA
    #    control): available flag, release date, content statuses.
    territory_http, territory = probe(
        "territory_availabilities",
        f"/v2/appAvailabilities/{APP_STORE_ID}/territoryAvailabilities"
        "?limit=200&include=territory")
    if territory_http == 200 and isinstance(territory, dict):
        detail = {}
        for item in territory.get("data") or []:
            attributes = item.get("attributes") or {}
            relation = (item.get("relationships") or {}).get("territory") or {}
            code = ((relation.get("data") or {}).get("id") or item.get("id"))
            if code in ("DEU", "USA", "GBR", "AUT"):
                detail[code] = {
                    "available": attributes.get("available"),
                    "releaseDate": attributes.get("releaseDate"),
                    "preOrderEnabled": attributes.get("preOrderEnabled"),
                    "contentStatuses": attributes.get("contentStatuses"),
                    "attributes": attributes,
                }
        counts = {}
        release_dates = set()
        for item in territory.get("data") or []:
            attributes = item.get("attributes") or {}
            release_dates.add(str(attributes.get("releaseDate")))
            for code in attributes.get("contentStatuses") or []:
                counts[code] = counts.get(code, 0) + 1
        result["summary"]["territory_detail"] = detail
        result["summary"]["territory_status_counts"] = counts
        result["summary"]["territory_release_dates"] = sorted(release_dates)
        result["summary"]["territory_count"] = len(territory.get("data") or [])
        result["summary"]["eu_trader_status_missing_count"] = counts.get(
            "TRADER_STATUS_NOT_PROVIDED", 0)

    write(result)
    print(json.dumps({"summary": result["summary"],
                      "probe_http": {k: v["http"] for k, v in result["probes"].items()}},
                     indent=2))
    return 0


def write(result):
    os.makedirs("out", exist_ok=True)
    with open("out/asc-inspection.json", "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)


if __name__ == "__main__":
    sys.exit(main())
