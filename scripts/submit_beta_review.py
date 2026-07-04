#!/usr/bin/env python3
"""Submit build for beta app review + add external tester."""
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
email = os.environ.get("BETA_TESTER_EMAIL", "dennis@kroeker.cloud")

jwt = make_jwt(key_id, issuer_id, key_content)
ctx = ssl.create_default_context()
conn = http.client.HTTPSConnection("api.appstoreconnect.apple.com", context=ctx)

bundle_id = "cloud.dkroeker.GaussianSplattingViewer"

# Get app
status, data = asc(conn, jwt, "GET", f"/v1/apps?filter[bundleId]={bundle_id}")
app_id = data["data"][0]["id"]
print(f"App: {app_id}")

# Get latest build
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/builds?limit=5")
build_id = None
for b in data.get("data", []):
    if b["attributes"].get("processingState") == "VALID" and not b["attributes"].get("expired", False):
        build_id = b["id"]
        ver = b["attributes"].get("version", "")
        print(f"Build: v{ver} ({build_id})")
        break

# Check beta app review details
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/betaAppReviewDetails")
if status == 200:
    if data.get("data"):
        detail_id = data["data"][0]["id"]
        print(f"Beta review details exist: {detail_id}")
    else:
        # Create beta app review details
        print("Creating beta app review details...")
        status2, data2 = asc(conn, jwt, "POST", "/v1/betaAppReviewDetails", {
            "data": {
                "type": "betaAppReviewDetails",
                "attributes": {
                    "contactEmail": "dennis@kroeker.cloud",
                    "contactFirstName": "Dennis",
                    "contactLastName": "Kröker",
                    "demoAccountName": "",
                    "demoAccountPassword": "",
                    "demoAccountRequired": False,
                    "notes": "Internal testing app for Gaussian Splatting visualization"
                },
                "relationships": {
                    "app": {"data": {"type": "apps", "id": app_id}}
                }
            }
        })
        print(f"Create details: {status2} {json.dumps(data2)[:300]}")
else:
    print(f"Beta review details check: {status} {json.dumps(data)[:300]}")

# Submit for beta app review
print("\nSubmitting build for beta app review...")
status, data = asc(conn, jwt, "POST", "/v1/betaAppReviewSubmissions", {
    "data": {
        "type": "betaAppReviewSubmissions",
        "relationships": {
            "build": {"data": {"type": "builds", "id": build_id}}
        }
    }
})
print(f"Beta review submission: {status} {json.dumps(data, indent=2)[:500]}")

conn.close()
