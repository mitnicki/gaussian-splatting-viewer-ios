#!/usr/bin/env python3
"""Submit the current App Store version for review."""
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

key_id = os.environ["ASC_API_KEY_ID"]
issuer_id = os.environ["ASC_ISSUER_ID"]
key_content = os.environ["ASC_API_KEY_CONTENT"]
jwt = make_jwt(key_id, issuer_id, key_content)

ctx = ssl.create_default_context()
conn = http.client.HTTPSConnection("api.appstoreconnect.apple.com", context=ctx)

bundle_id = "cloud.dkroeker.GaussianSplattingViewer"
status, data = asc(conn, jwt, "GET", f"/v1/apps?filter[bundleId]={bundle_id}")
app_id = data["data"][0]["id"]
print(f"App: {app_id}")

status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/appStoreVersions?filter[appStoreState]=PREPARE_FOR_SUBMISSION")
if not data.get("data"):
    # Try READY_FOR_REVIEW
    status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/appStoreVersions")
    version = None
    for v in data.get("data", []):
        state = v["attributes"].get("appStoreState", "")
        if state in ("PREPARE_FOR_SUBMISSION", "READY_FOR_REVIEW"):
            version = v
            break
    if not version and data.get("data"):
        version = data["data"][0]
    if not version:
        print("No App Store version found")
        conn.close()
        sys.exit(1)
else:
    version = data["data"][0]

version_id = version["id"]
version_string = version["attributes"]["versionString"]
state = version["attributes"]["appStoreState"]
print(f"Version: {version_string} state={state} (id={version_id})")

# Create submission
sub_body = {
    "data": {
        "type": "appStoreVersionSubmissions",
        "relationships": {
            "appStoreVersion": {
                "data": {"type": "appStoreVersions", "id": version_id}
            }
        }
    }
}
status, data = asc(conn, jwt, "POST", "/v1/appStoreVersionSubmissions", sub_body)
if status in (200, 201):
    print(f"Submitted for review! Submission ID: {data['data']['id']}")
elif status == 409:
    print("Already submitted for review")
else:
    print(f"Submission failed: {status} {json.dumps(data)[:500]}")
    conn.close()
    sys.exit(1)

conn.close()
