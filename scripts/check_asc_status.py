#!/usr/bin/env python3
"""Check App Store Connect agreement and app status."""
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
    print(f"App ID: {app['id']}")
    print(f"Name: {app['attributes'].get('name')}")
    print(f"Bundle ID: {app['attributes'].get('bundleId')}")
    print(f"Primary locale: {app['attributes'].get('primaryLocale')}")
    app_id = app["id"]
else:
    print(f"ERROR: {json.dumps(data)[:500]}")
    sys.exit(1)

# 2. Check agreements/contracts
print(f"\n=== Agreements ===")
status, data = asc(conn, jwt, "GET", "/v1/contracts?limit=20")
print(f"Contracts endpoint: status={status}")
if status == 200:
    for c in data.get("data", []):
        attrs = c.get("attributes", {})
        print(f"  Contract: {attrs.get('type', 'unknown')} — status={attrs.get('status', 'unknown')}")
else:
    print(f"  Response: {json.dumps(data)[:500]}")

# 3. Check app Store versions
print(f"\n=== App Store Versions ===")
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/appStoreVersions")
print(f"Status: {status}")
if status == 200:
    for v in data.get("data", []):
        attrs = v.get("attributes", {})
        print(f"  Version {attrs.get('versionString')} — state={attrs.get('appStoreState')} — build={attrs.get('build')}")
else:
    print(f"  Response: {json.dumps(data)[:500]}")

# 4. Check builds
print(f"\n=== Builds ===")
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/builds?limit=5")
print(f"Status: {status}")
if status == 200:
    for b in data.get("data", []):
        attrs = b.get("attributes", {})
        print(f"  Build {attrs.get('version')} — processing={attrs.get('processingState')} — expired={attrs.get('expired')}")
else:
    print(f"  Response: {json.dumps(data)[:500]}")

# 5. Check app availability
print(f"\n=== App Availability ===")
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/appAvailability")
print(f"Status: {status}")
if status == 200:
    attrs = data.get("data", {}).get("attributes", {})
    print(f"  Available: {attrs}")
else:
    print(f"  Response: {json.dumps(data)[:500]}")

conn.close()
print("\nDone.")
