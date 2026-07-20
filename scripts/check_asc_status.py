#!/usr/bin/env python3
"""Check App Store Connect agreement, app, version, localization, and build status."""
import json, time, sys, os, base64
import http.client, ssl

def make_jwt(key_id, issuer_id, key_content):
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    key_pem = key_content
    if "BEGIN PRIVATE KEY" not in key_pem:
        key_pem = "-----BEGIN PRIVATE KEY-----\n" + key_pem + "\n-----END PRIVATE KEY-----\n"
    private_key = serialization.load_pem_private_key(key_pem.encode(), password=None)
    header = {"alg": "ES256", "kid": key_id, "typ": "JWT"}
    now = int(time.time())
    payload = {"iss": issuer_id, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"}
    def b64url(data):
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode()
    header_b64 = b64url(json.dumps(header).encode())
    payload_b64 = b64url(json.dumps(payload).encode())
    signing_input = f"{header_b64}.{payload_b64}"
    der_sig = private_key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_sig)
    raw_sig = r.to_bytes(32, 'big') + s.to_bytes(32, 'big')
    return f"{header_b64}.{payload_b64}.{b64url(raw_sig)}"

def asc(conn, jwt, method, path, body=None):
    headers = {"Authorization": f"Bearer {jwt}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=json.dumps(body) if body else None, headers=headers)
    resp = conn.getresponse()
    raw = resp.read().decode()
    data = json.loads(raw) if raw.strip() else {}
    return resp.status, data

key_id = os.environ.get("ASC_API_KEY_ID", "")
issuer_id = os.environ.get("ASC_ISSUER_ID", "")
key_content = os.environ.get("ASC_API_KEY_CONTENT", "")

if not all([key_id, issuer_id, key_content]):
    print("ERROR: ASC_API_KEY_ID, ASC_ISSUER_ID, ASC_API_KEY_CONTENT must be set")
    sys.exit(1)

jwt = make_jwt(key_id, issuer_id, key_content)
ctx = ssl.create_default_context()
conn = http.client.HTTPSConnection("api.appstoreconnect.apple.com", context=ctx)

bundle_id = "cloud.dkroeker.GaussianSplattingViewer"

# 1. Get app
status, data = asc(conn, jwt, "GET", f"/v1/apps?filter[bundleId]={bundle_id}")
print(f"=== App (status={status}) ===")
if status == 200 and data.get("data"):
    app = data["data"][0]
    app_id = app["id"]
    print(f"App ID: {app_id}, Name: {app['attributes'].get('name')}, Locale: {app['attributes'].get('primaryLocale')}")
else:
    print(f"ERROR: {json.dumps(data)[:500]}")
    sys.exit(1)

# 2. Check App Store versions + localizations
print(f"\n=== App Store Versions ===")
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/appStoreVersions")
if status == 200:
    for v in data.get("data", []):
        attrs = v.get("attributes", {})
        vid = v["id"]
        print(f"  Version {attrs.get('versionString')} — state={attrs.get('appStoreState')} — build={attrs.get('build')}")
        # Check for existing submission
        sub_status, sub_data = asc(conn, jwt, "GET", f"/v1/appStoreVersions/{vid}/appStoreVersionSubmission")
        if sub_status == 200 and sub_data.get("data"):
            sub_state = sub_data["data"].get("attributes", {}).get("state", "UNKNOWN")
            print(f"    Submission: EXISTS (state={sub_state})")
        elif sub_status == 404:
            print(f"    Submission: none")
        else:
            print(f"    Submission: check returned {sub_status}")
        # Check localizations for this version
        status2, loc_data = asc(conn, jwt, "GET", f"/v1/appStoreVersions/{vid}/appStoreVersionLocalizations?limit=20")
        if status2 == 200:
            for loc in loc_data.get("data", []):
                la = loc.get("attributes", {})
                print(f"    Locale: {la.get('locale')} — desc={'YES' if la.get('description') else 'NO'} — promo={'YES' if la.get('promotionalText') else 'NO'} — keywords={'YES' if la.get('keywords') else 'NO'}")
        else:
            print(f"    Localizations: status={status2} {json.dumps(loc_data)[:200]}")
        # Check screenshots per localization
        if loc_data.get("data"):
            for loc in loc_data["data"]:
                loc_id = loc["id"]
                loc_locale = loc.get("attributes", {}).get("locale", "")
                status3, ss_data = asc(conn, jwt, "GET", f"/v1/appStoreVersionLocalizations/{loc_id}/appScreenshotSets?limit=10")
                if status3 == 200 and ss_data.get("data"):
                    for ss in ss_data["data"]:
                        ss_count = len(ss.get("relationships", {}).get("appScreenshots", {}).get("data", []))
                        print(f"    Screenshots [{loc_locale}]: {ss.get('attributes',{}).get('screenshotDisplayType')} — {ss_count} screenshots")
                else:
                    print(f"    Screenshots [{loc_locale}]: none")
else:
    print(f"  ERROR: status={status} {json.dumps(data)[:300]}")

# 3. Check builds
print(f"\n=== Builds ===")
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/builds?limit=10")
if status == 200:
    for b in data.get("data", []):
        attrs = b.get("attributes", {})
        print(f"  Build {attrs.get('version')} — processing={attrs.get('processingState')} — expired={attrs.get('expired')} — uploaded={attrs.get('uploadedDate','')[:10]}")
else:
    print(f"  ERROR: status={status}")

conn.close()
print("\nDone.")
