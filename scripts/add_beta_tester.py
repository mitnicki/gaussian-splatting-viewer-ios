#!/usr/bin/env python3
"""Add a beta tester to the App Store Connect beta group via the API."""
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
    sig_b64 = b64url(raw_sig)

    return f"{header_b64}.{payload_b64}.{sig_b64}"

def asc_request(conn, jwt, method, path, body=None):
    headers = {"Authorization": f"Bearer {jwt}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=json.dumps(body) if body else None, headers=headers)
    resp = conn.getresponse()
    data = json.loads(resp.read().decode())
    return resp.status, data

def main():
    key_id = os.environ.get("ASC_API_KEY_ID", "")
    issuer_id = os.environ.get("ASC_ISSUER_ID", "")
    key_content = os.environ.get("ASC_API_KEY_CONTENT", "")
    email = os.environ.get("BETA_TESTER_EMAIL", "")
    first_name = os.environ.get("BETA_TESTER_FIRST_NAME", "")
    last_name = os.environ.get("BETA_TESTER_LAST_NAME", "")

    if not all([key_id, issuer_id, key_content]):
        print("Missing ASC env vars")
        sys.exit(1)
    if not email:
        print("Missing BETA_TESTER_EMAIL")
        sys.exit(1)

    jwt = make_jwt(key_id, issuer_id, key_content)
    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection("api.appstoreconnect.apple.com", context=ctx)

    # Find the app
    bundle_id = "cloud.dkroeker.GaussianSplattingViewer"
    status, data = asc_request(conn, jwt, "GET", f"/v1/apps?filter[bundleId]={bundle_id}")
    if status != 200 or not data.get("data"):
        print(f"App not found: {status} {data}")
        sys.exit(1)
    app_id = data["data"][0]["id"]
    print(f"App: {app_id}")

    # Find beta groups for this app
    status, data = asc_request(conn, jwt, "GET", f"/v1/apps/{app_id}/betaGroups")
    if status != 200:
        print(f"Failed to list beta groups: {status} {data}")
        sys.exit(1)

    groups = data.get("data", [])
    if not groups:
        print("No beta groups found")
        sys.exit(1)

    # Find the "Internal Testers" group
    group_id = None
    for g in groups:
        if "Internal" in g.get("attributes", {}).get("name", ""):
            group_id = g["id"]
            print(f"Beta group: {g['attributes']['name']} ({group_id})")
            break
    if not group_id:
        group_id = groups[0]["id"]
        print(f"Using first beta group: {groups[0]['attributes']['name']} ({group_id})")

    # Check if tester already exists
    status, data = asc_request(conn, jwt, "GET", f"/v1/betaTesters?filter[email]={email}")
    if status == 200 and data.get("data"):
        tester_id = data["data"][0]["id"]
        print(f"Tester already exists: {tester_id}")

        # Add to group if not already
        status, data = asc_request(conn, jwt, "POST", "/v1/betaGroupsRelationships/betaTesters",
            {"data": [{"type": "betaTesters", "id": tester_id}]})
        # This might fail if already in group, that's ok
        if status in (200, 201, 204):
            print(f"Added existing tester to group")
        else:
            print(f"Add to group result: {status} (may already be member)")
        conn.close()
        return

    # Create new beta tester
    attrs = {"email": email}
    if first_name: attrs["firstName"] = first_name
    if last_name: attrs["lastName"] = last_name

    create_body = {
        "data": {
            "type": "betaTesters",
            "attributes": attrs,
            "relationships": {
                "betaGroups": {
                    "data": [{"type": "betaGroups", "id": group_id}]
                }
            }
        }
    }

    status, data = asc_request(conn, jwt, "POST", "/v1/betaTesters", create_body)
    if status == 201:
        tester_id = data["data"]["id"]
        print(f"Created beta tester: {tester_id} ({email})")
        print(f"Invitation sent to {email}")
    else:
        print(f"Error creating tester: {status} {json.dumps(data, indent=2)}")
        sys.exit(1)

    conn.close()

if __name__ == "__main__":
    main()
