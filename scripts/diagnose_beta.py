#!/usr/bin/env python3
"""Submit build for beta app review to enable external testers."""
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

key_id = os.environ.get("ASC_API_KEY_ID", "")
issuer_id = os.environ.get("ASC_ISSUER_ID", "")
key_content = os.environ.get("ASC_API_KEY_CONTENT", "")

jwt = make_jwt(key_id, issuer_id, key_content)
ctx = ssl.create_default_context()
conn = http.client.HTTPSConnection("api.appstoreconnect.apple.com", context=ctx)

bundle_id = "cloud.dkroeker.GaussianSplattingViewer"

# Get app
conn.request("GET", f"/v1/apps?filter[bundleId]={bundle_id}",
             headers={"Authorization": f"Bearer {jwt}"})
resp = conn.getresponse()
data = json.loads(resp.read().decode())
app_id = data["data"][0]["id"]
print(f"App: {app_id}")

# Get builds
conn.request("GET", f"/v1/apps/{app_id}/builds?limit=5",
             headers={"Authorization": f"Bearer {jwt}"})
resp = conn.getresponse()
data = json.loads(resp.read().decode())
for b in data.get("data", []):
    bid = b["id"]
    ver = b["attributes"].get("version", "")
    expired = b["attributes"].get("expired", False)
    processing = b["attributes"].get("processingState", "")
    print(f"Build v{ver} ({bid}): expired={expired} processing={processing}")
    
    # Check beta review status
    conn.request("GET", f"/v1/builds/{bid}/betaBuildUsagesV1",
                 headers={"Authorization": f"Bearer {jwt}"})
    resp2 = conn.getresponse()
    raw = resp2.read().decode()
    if raw.strip():
        review_data = json.loads(raw)
        print(f"  Beta review: {json.dumps(review_data)[:300]}")
    
    # Check if build has beta app review submission
    conn.request("GET", f"/v1/builds/{bid}/betaBuildReviewSubmissions",
                 headers={"Authorization": f"Bearer {jwt}"})
    resp3 = conn.getresponse()
    raw3 = resp3.read().decode()
    if raw3.strip():
        sub_data = json.loads(raw3)
        print(f"  Review submissions: {json.dumps(sub_data)[:300]}")
    else:
        print(f"  Review submissions: (empty)")

# Also check the beta group details
conn.request("GET", f"/v1/apps/{app_id}/betaGroups",
             headers={"Authorization": f"Bearer {jwt}"})
resp = conn.getresponse()
data = json.loads(resp.read().decode())
for g in data.get("data", []):
    gid = g["id"]
    name = g["attributes"].get("name", "")
    is_internal = g["attributes"].get("isInternalGroup", False)
    has_access = g["attributes"].get("hasAccessToAllBuilds", False)
    print(f"\nGroup: {name} ({gid}) internal={is_internal} hasAccessToAllBuilds={has_access}")
    
    # Get builds for this group
    conn.request("GET", f"/v1/betaGroups/{gid}/relationships/builds",
                 headers={"Authorization": f"Bearer {jwt}"})
    resp2 = conn.getresponse()
    raw2 = resp2.read().decode()
    if raw2.strip():
        builds_data = json.loads(raw2)
        print(f"  Builds: {json.dumps(builds_data)[:300]}")

conn.close()
