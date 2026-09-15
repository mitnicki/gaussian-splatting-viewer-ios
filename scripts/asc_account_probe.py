#!/usr/bin/env python3
"""Read-only App Store Connect account scope probe (GET requests only).

Lists every app of the account and checks publicly which of them are listed and
priced, to tell an account level sellability block apart from a release that was
stranded on the Apple side. A live priced sibling app refutes the former.
"""

import base64
import http.client
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

APP_STORE_ID = "6787153621"
TARGET_VERSION = "1.0"
CONTROL_APP_ID = "310633997"
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
        return 0, {"transport_error": f"{exc.__class__.__name__}: {exc}"}
    try:
        body = json.loads(raw)
        if len(json.dumps(body)) > BODY_LIMIT:
            body = {"_truncated": True, "_head": raw[:BODY_LIMIT]}
    except ValueError:
        body = raw[:BODY_LIMIT]
    return status, body

def public_lookup(app_id, country):
    url = ("https://itunes.apple.com/lookup?"
           + urllib.parse.urlencode({"id": app_id, "country": country, "entity": "software"}))
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
            body = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return {"http": exc.code, "resultCount": None, "results": []}
    except Exception as exc:
        return {"http": 0, "error": f"{exc.__class__.__name__}: {exc}", "results": []}
    results = body.get("results") or []
    trimmed = []
    for item in results:
        trimmed.append({
            "trackId": item.get("trackId"),
            "trackName": item.get("trackName"),
            "version": item.get("version"),
            "sellerName": item.get("sellerName"),
            "artistId": item.get("artistId"),
            "bundleId": item.get("bundleId"),
            "price": item.get("price"),
            "currency": item.get("currency"),
            "formattedPrice": item.get("formattedPrice"),
            "trackViewUrl": item.get("trackViewUrl"),
            "currentVersionReleaseDate": item.get("currentVersionReleaseDate"),
        })
    return {"http": status, "resultCount": body.get("resultCount"), "results": trimmed}

def write(result):
    os.makedirs("out", exist_ok=True)
    with open("out/asc-inspection.json", "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)

def main():
    key_id = os.environ.get("ASC_API_KEY_ID", "")
    issuer_id = os.environ.get("ASC_ISSUER_ID", "")
    key_content = os.environ.get("ASC_API_KEY_CONTENT", "")
    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "action": "account_probe",
        "probes": {},
        "account_apps": [],
        "public": {},
        "summary": {},
    }
    if not (key_id and issuer_id and key_content):
        result["fatal"] = "ASC credentials are not available to this workflow"
        write(result)
        return 0

    jwt = make_jwt(key_id, issuer_id, key_content)
    connection = http.client.HTTPSConnection("api.appstoreconnect.apple.com",
                                             context=ssl.create_default_context())

    def probe(key, path):
        status, body = asc_get(connection, jwt, path)
        result["probes"][key] = {"path": path, "http": status, "body": body}
        return status, body

    fields = ("name,bundleId,primaryLocale,sku,contentRightsDeclaration")
    status, apps_body = probe("account_apps",
                              "/v1/apps?limit=200&fields[apps]=" + fields)
    apps = []
    if status == 200 and isinstance(apps_body, dict):
        apps = apps_body.get("data") or []
    result["summary"]["account_app_count"] = len(apps)

    for app in apps:
        app_id = app.get("id")
        attributes = app.get("attributes") or {}
        entry = {
            "id": app_id,
            "name": attributes.get("name"),
            "bundleId": attributes.get("bundleId"),
            "primaryLocale": attributes.get("primaryLocale"),
            "sku": attributes.get("sku"),
            "is_target": app_id == APP_STORE_ID,
            "versions": [],
            "availability": None,
            "public": {},
        }
        version_fields = ("versionString,appStoreState,appVersionState,"
                          "releaseType,earliestReleaseDate,createdDate,downloadable")
        _, versions_body = probe(f"versions_{app_id}",
                                 f"/v1/apps/{app_id}/appStoreVersions?limit=10"
                                 f"&fields[appStoreVersions]={version_fields}")
        if isinstance(versions_body, dict):
            for version in versions_body.get("data") or []:
                vattributes = version.get("attributes") or {}
                entry["versions"].append({
                    "versionString": vattributes.get("versionString"),
                    "appStoreState": vattributes.get("appStoreState"),
                    "appVersionState": vattributes.get("appVersionState"),
                    "releaseType": vattributes.get("releaseType"),
                    "earliestReleaseDate": vattributes.get("earliestReleaseDate"),
                    "downloadable": vattributes.get("downloadable"),
                })
        availability_status, availability_body = asc_get(
            connection, jwt, f"/v1/apps/{app_id}/appAvailabilityV2")
        result["probes"][f"availability_{app_id}"] = {"http": availability_status,
                                                     "body": availability_body}
        if isinstance(availability_body, dict):
            entry["availability"] = (availability_body.get("data") or {}).get("attributes")

        for country in ("de", "us"):
            entry["public"][country] = public_lookup(app_id, country)
        result["account_apps"].append(entry)

    result["public"]["control_310633997_de"] = public_lookup(CONTROL_APP_ID, "de")
    result["public"]["target_6787153621_de"] = public_lookup(APP_STORE_ID, "de")
    result["public"]["target_6787153621_us"] = public_lookup(APP_STORE_ID, "us")

    listed = []
    paid = []
    for entry in result["account_apps"]:
        for country, payload in (entry.get("public") or {}).items():
            if (payload or {}).get("resultCount"):
                if entry["id"] not in listed:
                    listed.append(entry["id"])
                for item in payload.get("results") or []:
                    if item.get("price") not in (None, 0, "0", 0.0):
                        if entry["id"] not in paid:
                            paid.append(entry["id"])
    result["summary"]["account_listed_app_ids"] = listed
    result["summary"]["account_listed_paid_app_ids"] = paid
    result["summary"]["h1_refuted_by_live_paid_sibling"] = bool(paid)
    result["summary"]["target_listed"] = bool(
        (result["public"].get("target_6787153621_de") or {}).get("resultCount"))
    result["summary"]["control_ok"] = bool(
        (result["public"].get("control_310633997_de") or {}).get("resultCount"))

    write(result)
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    import traceback
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:
        os.makedirs("out", exist_ok=True)
        detail = traceback.format_exc()
        with open("out/asc-inspection.json", "w", encoding="utf-8") as handle:
            json.dump({"action": "account_probe", "fatal_exception": detail},
                      handle, indent=2, sort_keys=True)
        raise SystemExit(1)
