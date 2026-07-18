#!/usr/bin/env python3
"""Submit build for App Store review — creates App Store version, links build, submits.

Adapted from submit_beta_review.py. Uses the App Store versioning API (not beta).
Requires: a VALID, processed TestFlight build exists for this app.
"""
import json, time, sys, os, base64
import http.client, ssl

def make_jwt(key_id, issuer_id, key_content):
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    key_pem = key_content
    if "BEGIN PRIVATE KEY" not in key_pem:
        key_pem = "-----BEGIN PRIVATE KEY-----\n" + key_content + "\n-----END PRIVATE KEY-----"
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
app_version = os.environ.get("APP_VERSION", "1.0.0")
price_tier = int(os.environ.get("PRICE_TIER", "3"))

if not all([key_id, issuer_id, key_content]):
    print("ERROR: ASC_API_KEY_ID, ASC_ISSUER_ID, ASC_API_KEY_CONTENT must be set")
    sys.exit(1)

jwt = make_jwt(key_id, issuer_id, key_content)
ctx = ssl.create_default_context()
conn = http.client.HTTPSConnection("api.appstoreconnect.apple.com", context=ctx)

bundle_id = "cloud.dkroeker.GaussianSplattingViewer"

# 1. Get app
status, data = asc(conn, jwt, "GET", f"/v1/apps?filter[bundleId]={bundle_id}")
if status != 200 or not data.get("data"):
    print(f"ERROR: App not found (status={status}): {json.dumps(data)[:300]}")
    sys.exit(1)
app_id = data["data"][0]["id"]
print(f"App: {app_id} ({bundle_id})")

# 2. Get latest VALID build
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/builds?limit=20")
if status != 200:
    print(f"ERROR: Could not fetch builds (status={status}): {json.dumps(data)[:300]}")
    sys.exit(1)

valid_builds = []
for b in data.get("data", []):
    attrs = b["attributes"]
    if attrs.get("processingState") == "VALID" and not attrs.get("expired", False):
        valid_builds.append(b)

if not valid_builds:
    print("ERROR: No valid (processed, non-expired) builds found.")
    print("Upload a build to TestFlight first, then run this script.")
    sys.exit(1)

valid_builds.sort(key=lambda b: int(b["attributes"].get("version", "0")), reverse=True)
build = valid_builds[0]
build_id = build["id"]
build_version = build["attributes"]["version"]
print(f"Latest valid build: {build_id} (version {build_version})")

# 3. Check if App Store version already exists
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/appStoreVersions?filter[versionString]={app_version}")
existing_version = None
app_store_version_id = None
if status == 200 and data.get("data"):
    existing_version = data["data"][0]
    app_store_version_id = existing_version["id"]
    version_state = existing_version["attributes"].get("appStoreState", "")
    print(f"App Store version {app_version} already exists: {app_store_version_id} (state={version_state})")
    if version_state in ("WAITING_FOR_REVIEW", "IN_REVIEW", "PENDING_DEVELOPER_RELEASE", "READY_FOR_SALE"):
        print("Already submitted or live — nothing to do.")
        sys.exit(0)
else:
    # 4. Create App Store version
    print(f"\nCreating App Store version {app_version}...")
    status, data = asc(conn, jwt, "POST", "/v1/appStoreVersions", {
        "data": {
            "type": "appStoreVersions",
            "attributes": {
                "platform": "IOS",
                "versionString": app_version,
                "copyright": "2026 Dennis Kroeker",
                "releaseType": "MANUAL",
                "usesIdfa": False
            },
            "relationships": {
                "app": {"data": {"type": "apps", "id": app_id}}
            }
        }
    })
    if status == 201:
        app_store_version_id = data["data"]["id"]
        print(f"Created App Store version: {app_store_version_id}")
    elif status == 409:
        print(f"Version {app_version} already exists (409), fetching...")
        status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/appStoreVersions")
        for v in data.get("data", []):
            if v["attributes"].get("versionString") == app_version:
                app_store_version_id = v["id"]
                break
        if not app_store_version_id:
            print(f"ERROR: Could not find existing version: {json.dumps(data)[:300]}")
            sys.exit(1)
        print(f"Using existing version: {app_store_version_id}")
    else:
        print(f"ERROR creating version (status={status}): {json.dumps(data)[:300]}")
        sys.exit(1)

# 5. Link build to App Store version
print(f"\nLinking build {build_id} to App Store version {app_store_version_id}...")
status, data = asc(conn, jwt, "PATCH", f"/v1/appStoreVersions/{app_store_version_id}/relationships/build", {
    "data": {"type": "builds", "id": build_id}
})
if status in (200, 204):
    print("Build linked successfully.")
else:
    print(f"WARNING: Link build returned {status}: {json.dumps(data)[:300]}")

# 6. Submit for review
print(f"\nSubmitting App Store version {app_version} for review...")
time.sleep(5)

for attempt in range(3):
    status, data = asc(conn, jwt, "POST", "/v1/submissions", {
        "data": {
            "type": "submissions",
            "relationships": {
                "appStoreVersion": {
                    "data": {"type": "appStoreVersions", "id": app_store_version_id}
                }
            }
        }
    })
    if status == 201:
        sub_id = data["data"]["id"]
        state = data["data"]["attributes"].get("state", "")
        print(f"SUCCESS — Submission created: {sub_id} state={state}")
        print(f"App Store version {app_version} (build {build_version}) submitted for review.")
        print("Review typically takes 24-48 hours.")
        break
    elif status == 422:
        err_detail = ""
        if data.get("errors"):
            err_detail = data["errors"][0].get("detail", "")
        print(f"Attempt {attempt+1}: 422 — {err_detail}")
        if attempt < 2:
            print("Waiting 15s...")
            time.sleep(15)
    elif status == 409:
        print(f"Already submitted: {json.dumps(data)[:200]}")
        break
    else:
        print(f"Attempt {attempt+1}: {status} {json.dumps(data)[:300]}")
        if attempt < 2:
            time.sleep(10)

conn.close()
print("\nDone.")
