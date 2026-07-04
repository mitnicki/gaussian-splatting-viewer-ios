#!/usr/bin/env python3
"""Fix export compliance on builds, then submit for beta review."""
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
print(f"App: {app_id}")

# Get all builds
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/builds?limit=10")
builds = data.get("data", [])
print(f"\nBuilds: {len(builds)}")

# Get the latest valid, non-expired build
latest_build = None
for b in builds:
    build_id = b["id"]
    version = b["attributes"]["version"]
    expired = b["attributes"].get("expired", False)
    processing = b["attributes"].get("processingState", "")
    print(f"  v{version} ({build_id}): expired={expired} state={processing}")
    if not expired and processing == "VALID":
        latest_build = b

if not latest_build:
    print("No valid build found!")
    sys.exit(1)

build_id = latest_build["id"]
version = latest_build["attributes"]["version"]
print(f"\nUsing build v{version} ({build_id})")

# 1. Try to set export compliance via exportCompliances endpoint
print("\n--- Setting export compliance ---")
status, data = asc(conn, jwt, "POST", "/v1/exportCompliances", {
    "data": {
        "type": "exportCompliances",
        "attributes": {
            "usesEncryption": False,
            "doesnTUseEncryption": True
        },
        "relationships": {
            "build": {"data": {"type": "builds", "id": build_id}}
        }
    }
})
print(f"POST exportCompliances: {status}")
if status == 201:
    print("Export compliance created!")
elif status == 409:
    # Maybe already exists, try GET
    print(f"409: {json.dumps(data)[:300]}")
    # Try PATCH on build's exportCompliance relationship
    status2, data2 = asc(conn, jwt, "GET", f"/v1/builds/{build_id}/exportCompliance")
    print(f"GET exportCompliance: {status2} {json.dumps(data2)[:300]}")
else:
    print(f"Error: {json.dumps(data)[:400]}")

# 2. Also try PATCH on build directly with exportCompliance attribute
print("\n--- PATCH build with exportCompliance ---")
status, data = asc(conn, jwt, "PATCH", f"/v1/builds/{build_id}", {
    "data": {
        "type": "builds",
        "id": build_id,
        "attributes": {
            "exportCompliance": {
                "usesEncryption": False,
                "doesnTUseEncryption": True
            }
        }
    }
})
print(f"PATCH build: {status}")
if status == 200:
    print("Export compliance set via build PATCH!")
    ec = data.get("data", {}).get("attributes", {}).get("exportCompliance", {})
    print(f"  exportCompliance: {ec}")
else:
    print(f"Error: {json.dumps(data)[:400]}")
    # Try alternative: PATCH with relationship
    status2, data2 = asc(conn, jwt, "PATCH", f"/v1/builds/{build_id}/relationships/exportCompliance", {
        "data": {"type": "exportCompliances", "id": "current"}
    })
    print(f"PATCH relationship: {status2} {json.dumps(data2)[:300]}")

# 3. Check existing beta review submissions
print("\n--- Beta review submissions ---")
status, data = asc(conn, jwt, "GET", f"/v1/builds/{build_id}/betaAppReviewSubmissions")
print(f"Existing: {status} {json.dumps(data)[:300]}")

# 4. Submit for beta review
print("\n--- Submitting for beta review ---")
status, data = asc(conn, jwt, "POST", "/v1/betaAppReviewSubmissions", {
    "data": {
        "type": "betaAppReviewSubmissions",
        "relationships": {"build": {"data": {"type": "builds", "id": build_id}}}
    }
})
print(f"Submit: {status}")
if status == 201:
    state = data["data"]["attributes"].get("betaReviewState", "")
    print(f"SUCCESS! state={state}")
elif status == 422:
    err = data.get("errors", [{}])[0].get("detail", "")
    print(f"422: {err}")
elif status == 409:
    print(f"409: Already submitted")
else:
    print(f"Error: {json.dumps(data)[:400]}")

# 5. List beta testers
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
