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

# 1. Ensure beta app localization exists
desc = "Gaussian Splatting Viewer — view 3D Gaussian Splat scenes on iOS. Connect to Nextcloud WebDAV, browse and render .spz files with Metal."
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/betaAppLocalizations")
print(f"Beta localizations: status={status} count={len(data.get('data', []))}")
if status == 200:
    locs = data.get("data", [])
    if locs:
        loc_id = locs[0]["id"]
        print(f"  Existing: {loc_id}")
        status, data = asc(conn, jwt, "PATCH", f"/v1/betaAppLocalizations/{loc_id}", {
            "data": {"type": "betaAppLocalizations", "id": loc_id, "attributes": {"description": desc}}
        })
        print(f"  Updated: {status}")
    else:
        status, data = asc(conn, jwt, "POST", "/v1/betaAppLocalizations", {
            "data": {
                "type": "betaAppLocalizations",
                "attributes": {"locale": "en-US", "description": desc},
                "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}
            }
        })
        print(f"  Created: {status} {json.dumps(data)[:200]}")

# 2. Ensure beta app review details exist
# Get via app relationship (not filter)
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/betaAppReviewDetails")
print(f"\nBeta review details (via relationship): status={status}")
if status == 200:
    if data.get("data"):
        rad_id = data["data"][0]["id"]
        print(f"  Exists: {rad_id}")
        status, data = asc(conn, jwt, "PATCH", f"/v1/betaAppReviewDetails/{rad_id}", {
            "data": {
                "type": "betaAppReviewDetails", "id": rad_id,
                "attributes": {
                    "contactEmail": "dennis@kroeker.cloud",
                    "contactFirstName": "Dennis",
                    "contactLastName": "Kröker",
                    "demoAccountRequired": False
                }
            }
        })
        print(f"  Updated: {status}")
    else:
        print("  No data returned")
else:
    # Create
    print("  Creating...")
    status, data = asc(conn, jwt, "POST", "/v1/betaAppReviewDetails", {
        "data": {
            "type": "betaAppReviewDetails",
            "attributes": {
                "contactEmail": "dennis@kroeker.cloud",
                "contactFirstName": "Dennis",
                "contactLastName": "Kröker",
                "demoAccountRequired": False
            },
            "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}
        }
    })
    print(f"  Created: {status} {json.dumps(data)[:300]}")

# 3. Check existing beta review submissions for this build
status, data = asc(conn, jwt, "GET", f"/v1/builds/{build_id}/betaAppReviewSubmissions")
print(f"\nExisting submissions: status={status}")
if status == 200 and data.get("data"):
    for s in data["data"]:
        state = s["attributes"].get("betaReviewState", "")
        print(f"  Submission: {s['id']} state={state}")
        if state in ("WAITING_FOR_REVIEW", "IN_REVIEW", "APPROVED"):
            print("  Already submitted — skipping")
            conn.close()
            sys.exit(0)

# Wait for propagation
print("\nWaiting 10s for ASC propagation...")
time.sleep(10)

# 4. Submit for beta app review
print("\nSubmitting build for beta app review...")
for attempt in range(3):
    status, data = asc(conn, jwt, "POST", "/v1/betaAppReviewSubmissions", {
        "data": {
            "type": "betaAppReviewSubmissions",
            "relationships": {"build": {"data": {"type": "builds", "id": build_id}}}
        }
    })
    if status == 201:
        sub_id = data["data"]["id"]
        state = data["data"]["attributes"].get("betaReviewState", "")
        print(f"Submitted: {sub_id} state={state}")
        print("SUCCESS — Beta app review submitted.")
        print("External testers will be invited automatically once approved (~24h).")
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
        break

conn.close()
