#!/usr/bin/env python3
"""Check ASC API key permissions and beta app review details."""
import json, time, os, base64
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
print(f"App: {app_id}")

# Check app attributes
print(f"\n=== App Attributes ===")
for k in sorted(data["data"][0].get("attributes", {}).keys()):
    print(f"  {k}: {data['data'][0]['attributes'][k]}")

# Check betaAppReviewDetails (different endpoints)
print(f"\n=== Beta App Review Details ===")
# Method 1: via app relationship
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/betaAppReviewDetails")
print(f"Via app/betaAppReviewDetails: {status} {json.dumps(data)[:300]}")

# Method 2: direct filter
status, data = asc(conn, jwt, "GET", f"/v1/betaAppReviewDetails?filter[app]={app_id}")
print(f"Via filter: {status} {json.dumps(data)[:300]}")

# Check betaAppReviewSubmissions
print(f"\n=== Beta App Review Submissions (global) ===")
status, data = asc(conn, jwt, "GET", "/v1/betaAppReviewSubmissions?limit=5")
print(f"GET all: {status} {json.dumps(data)[:500]}")

# Check what the actual full error is when submitting
print(f"\n=== Attempt Submission with Full Error ===")
# Get latest build
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/builds?limit=1")
build_id = data["data"][0]["id"]
version = data["data"][0]["attributes"]["version"]
print(f"Build: v{version} ({build_id})")

status, data = asc(conn, jwt, "POST", "/v1/betaAppReviewSubmissions", {
    "data": {
        "type": "betaAppReviewSubmissions",
        "relationships": {"build": {"data": {"type": "builds", "id": build_id}}}
    }
})
print(f"POST result: {status}")
print(json.dumps(data, indent=2)[:1000])

conn.close()
