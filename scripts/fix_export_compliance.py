#!/usr/bin/env python3
"""Fix betaAppReviewDetails + betaAppLocalization + submit for beta review."""
import json, time, sys, os, base64
import http.client, ssl

def make_jwt(key_id, issuer_id, key_content):
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    key_pem = key_content
    if "BEGIN PRIVATE KEY" not in key_pem:
        key_pem = "-----BEGIN PRIVATE KEY-----\n" + key_pem + "\n-----END PRIVATE KEY-----"
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

jwt = make_jwt(key_id, issuer_id, key_content)
ctx = ssl.create_default_context()
conn = http.client.HTTPSConnection("api.appstoreconnect.apple.com", context=ctx)

bundle_id = "cloud.dkroeker.GaussianSplattingViewer"

# Get app
status, data = asc(conn, jwt, "GET", f"/v1/apps?filter[bundleId]={bundle_id}")
app_id = data["data"][0]["id"]
primary_locale = data["data"][0]["attributes"].get("primaryLocale", "en-US")
print(f"App: {app_id} (primaryLocale={primary_locale})")

# 1. Fix betaAppReviewDetails (exists but has null fields — PATCH with contact info)
print(f"\n=== Fix Beta App Review Details ===")
# Use the filter endpoint (which worked)
status, data = asc(conn, jwt, "GET", f"/v1/betaAppReviewDetails?filter[app]={app_id}")
print(f"GET: status={status}")
if status == 200 and data.get("data"):
    rad_id = data["data"][0]["id"]
    print(f"  Found: {rad_id}")
    print(f"  Current: {json.dumps(data['data'][0]['attributes'])[:200]}")
    status, data = asc(conn, jwt, "PATCH", f"/v1/betaAppReviewDetails/{rad_id}", {
        "data": {
            "type": "betaAppReviewDetails",
            "id": rad_id,
            "attributes": {
                "contactEmail": "dennis@kroeker.cloud",
                "contactFirstName": "Dennis",
                "contactLastName": "Kröker",
                "demoAccountRequired": False
            }
        }
    })
    print(f"  PATCH: {status}")
    if status == 200:
        print(f"  Updated: {json.dumps(data['data']['attributes'])[:200]}")
    else:
        print(f"  Error: {json.dumps(data)[:300]}")

# 2. Fix betaAppLocalizations — ensure primary locale exists
print(f"\n=== Fix Beta App Localizations ===")
desc_en = "Gaussian Splatting Viewer — view 3D Gaussian Splat scenes on iOS. Connect to Nextcloud WebDAV, browse and render .spz files with Metal."
desc_de = "Gaussian Splatting Viewer — 3D Gaussian Splat Szenen auf iOS anzeigen. Nextcloud WebDAV-Verbindung, .spz-Dateien mit Metal rendern."

status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/betaAppLocalizations")
print(f"GET: status={status} count={len(data.get('data', []))}")
existing_locales = set()
if status == 200:
    for loc in data.get("data", []):
        loc_id = loc["id"]
        locale = loc["attributes"].get("locale", "")
        existing_locales.add(locale)
        print(f"  {locale}: {loc_id} (feedbackEmail={loc['attributes'].get('feedbackEmail','')})")

# Ensure primary locale localization exists
if primary_locale not in existing_locales:
    print(f"  Creating {primary_locale} localization...")
    desc = desc_de if primary_locale == "de-DE" else desc_en
    status, data = asc(conn, jwt, "POST", "/v1/betaAppLocalizations", {
        "data": {
            "type": "betaAppLocalizations",
            "attributes": {
                "locale": primary_locale,
                "description": desc,
                "feedbackEmail": "dennis@kroeker.cloud"
            },
            "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}
        }
    })
    print(f"  Created: {status} {json.dumps(data)[:200]}")
else:
    # Update existing primary locale localization
    for loc in data.get("data", []):
        if loc["attributes"].get("locale") == primary_locale:
            loc_id = loc["id"]
            desc = desc_de if primary_locale == "de-DE" else desc_en
            status, data = asc(conn, jwt, "PATCH", f"/v1/betaAppLocalizations/{loc_id}", {
                "data": {
                    "type": "betaAppLocalizations",
                    "id": loc_id,
                    "attributes": {
                        "description": desc,
                        "feedbackEmail": "dennis@kroeker.cloud"
                    }
                }
            })
            print(f"  Updated {primary_locale}: {status}")

# Also ensure en-US exists
if "en-US" not in existing_locales and primary_locale != "en-US":
    print(f"  Creating en-US localization...")
    status, data = asc(conn, jwt, "POST", "/v1/betaAppLocalizations", {
        "data": {
            "type": "betaAppLocalizations",
            "attributes": {
                "locale": "en-US",
                "description": desc_en,
                "feedbackEmail": "dennis@kroeker.cloud"
            },
            "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}
        }
    })
    print(f"  Created: {status}")

# 3. Fix export compliance + submit for review
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/builds?limit=10")
builds = data.get("data", [])
print(f"\n=== Builds: {len(builds)} ===")

whats_new = "Initial beta release. Browse and render 3D Gaussian Splat scenes from Nextcloud via WebDAV."

for b in builds:
    build_id = b["id"]
    version = b["attributes"]["version"]
    expired = b["attributes"].get("expired", False)
    processing = b["attributes"].get("processingState", "")
    non_exempt = b["attributes"].get("usesNonExemptEncryption", None)
    print(f"\nv{version} ({build_id}): expired={expired} state={processing}")

    if expired or processing != "VALID":
        continue

    # Fix export compliance
    if non_exempt is None:
        status, data = asc(conn, jwt, "PATCH", f"/v1/builds/{build_id}", {
            "data": {"type": "builds", "id": build_id, "attributes": {"usesNonExemptEncryption": False}}
        })
        print(f"  Export compliance: {status}")

    # Submit for beta review
    status, data = asc(conn, jwt, "POST", "/v1/betaAppReviewSubmissions", {
        "data": {
            "type": "betaAppReviewSubmissions",
            "relationships": {"build": {"data": {"type": "builds", "id": build_id}}}
        }
    })
    if status == 201:
        state = data["data"]["attributes"].get("betaReviewState", "")
        print(f"  REVIEW SUBMITTED! state={state}")
    elif status == 422:
        err = data.get("errors", [{}])[0]
        print(f"  422: {err.get('title','')} — {err.get('detail','')}")
    elif status == 409:
        print(f"  409: Already submitted")
    else:
        print(f"  {status}: {json.dumps(data)[:300]}")

# 4. List beta testers
print("\n=== Beta Testers ===")
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/betaGroups?include=betaTesters")
groups = data.get("data", [])
included = data.get("included", [])
for g in groups:
    name = g["attributes"]["name"]
    internal = g["attributes"].get("isInternalGroup", False)
    tester_ids = [r["id"] for r in g.get("relationships", {}).get("betaTesters", {}).get("data", [])]
    print(f"\nGroup: {name} internal={internal}")
    for tid in tester_ids:
        for inc in included:
            if inc["id"] == tid and inc["type"] == "betaTesters":
                attrs = inc["attributes"]
                print(f"  {attrs.get('email','')} state={attrs.get('state','')}")

conn.close()
