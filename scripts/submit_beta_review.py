#!/usr/bin/env python3
"""Submit build for beta app review — creates required metadata first."""
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
        print(f"Build: v{b['attributes']['version']} ({build_id})")
        break

# Check existing beta app localizations
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/betaAppLocalizations")
if status == 200:
    locs = data.get("data", [])
    if locs:
        loc_id = locs[0]["id"]
        print(f"Beta localization exists: {loc_id}")
        # Update with description
        status, data = asc(conn, jwt, "PATCH", f"/v1/betaAppLocalizations/{loc_id}", {
            "data": {
                "type": "betaAppLocalizations",
                "id": loc_id,
                "attributes": {
                    "description": "Gaussian Splatting Viewer — view 3D Gaussian Splat scenes on iOS. Connect to Nextcloud WebDAV, browse and render .spz files with Metal."
                }
            }
        })
        print(f"Updated description: {status}")
    else:
        print("Creating beta app localization...")
        status, data = asc(conn, jwt, "POST", "/v1/betaAppLocalizations", {
            "data": {
                "type": "betaAppLocalizations",
                "attributes": {
                    "locale": "en-US",
                    "description": "Gaussian Splatting Viewer — view 3D Gaussian Splat scenes on iOS. Connect to Nextcloud WebDAV, browse and render .spz files with Metal."
                },
                "relationships": {
                    "app": {"data": {"type": "apps", "id": app_id}}
                }
            }
        })
        print(f"Created localization: {status} {json.dumps(data)[:200]}")

# Create beta app review detail
print("\nCreating beta app review details...")
status, data = asc(conn, jwt, "GET", f"/v1/betaAppReviewDetails?filter[app]={app_id}")
if status == 200 and data.get("data"):
    print(f"Review details exist: {data['data'][0]['id']}")
else:
    status, data = asc(conn, jwt, "POST", "/v1/betaAppReviewDetails", {
        "data": {
            "type": "betaAppReviewDetails",
            "attributes": {
                "contactEmail": "dennis@kroeker.cloud",
                "contactFirstName": "Dennis",
                "contactLastName": "Kröker",
                "demoAccountRequired": False
            },
            "relationships": {
                "app": {"data": {"type": "apps", "id": app_id}}
            }
        }
    })
    print(f"Created review details: {status} {json.dumps(data)[:200]}")

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
if status == 201:
    sub_id = data["data"]["id"]
    state = data["data"]["attributes"].get("betaReviewState", "")
    print(f"Submitted for review: {sub_id} state={state}")
    print("Beta app review submitted. External testers will be invited once approved.")
else:
    print(f"Submission: {status} {json.dumps(data, indent=2)[:500]}")

conn.close()
