#!/usr/bin/env python3
"""Diagnose beta testing setup."""
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

# List beta groups
conn.request("GET", f"/v1/apps/{app_id}/betaGroups",
             headers={"Authorization": f"Bearer {jwt}"})
resp = conn.getresponse()
data = json.loads(resp.read().decode())
for g in data.get("data", []):
    gid = g["id"]
    name = g["attributes"].get("name", "")
    is_internal = g["attributes"].get("isInternalGroup", False)
    print(f"\nGroup: {name} ({gid}) internal={is_internal}")
    
    # List testers in this group
    conn.request("GET", f"/v1/betaGroups/{gid}/betaTesters",
                 headers={"Authorization": f"Bearer {jwt}"})
    resp2 = conn.getresponse()
    data2 = json.loads(resp2.read().decode())
    for t in data2.get("data", []):
        email = t["attributes"].get("email", "")
        state = t["attributes"].get("state", "")
        first = t["attributes"].get("firstName", "")
        last = t["attributes"].get("lastName", "")
        print(f"  Tester: {first} {last} <{email}> state={state}")

    # List builds in this group
    conn.request("GET", f"/v1/betaGroups/{gid}/builds",
                 headers={"Authorization": f"Bearer {jwt}"})
    resp3 = conn.getresponse()
    data3 = json.loads(resp3.read().decode())
    for b in data3.get("data", []):
        ver = b["attributes"].get("version", "")
        expired = b["attributes"].get("expired", False)
        processing = b["attributes"].get("processingState", "")
        print(f"  Build: v{ver} expired={expired} processing={processing}")

# Try creating tester with dennis@kroeker.cloud and print full error
print("\n--- Attempting to create tester dennis@kroeker.cloud ---")
create_body = {
    "data": {
        "type": "betaTesters",
        "attributes": {"email": "dennis@kroeker.cloud", "firstName": "Dennis", "lastName": "Kröker"},
        "relationships": {
            "betaGroups": {"data": [{"type": "betaGroups", "id": data["data"][0]["id"]}]}
        }
    }
}
conn.request("POST", "/v1/betaTesters",
             body=json.dumps(create_body),
             headers={"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"})
resp = conn.getresponse()
body = resp.read().decode()
print(f"Status: {resp.status}")
print(f"Response: {body[:1000]}")

# Also try without group
print("\n--- Without group ---")
create_body["data"]["relationships"] = {}
conn.request("POST", "/v1/betaTesters",
             body=json.dumps(create_body),
             headers={"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"})
resp = conn.getresponse()
body = resp.read().decode()
print(f"Status: {resp.status}")
print(f"Response: {body[:1000]}")

conn.close()
