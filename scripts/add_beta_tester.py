#!/usr/bin/env python3
"""Add a beta tester to App Store Connect — creates an external group if needed."""
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
    data = json.loads(raw) if raw else {}
    return resp.status, data

def main():
    key_id = os.environ.get("ASC_API_KEY_ID", "")
    issuer_id = os.environ.get("ASC_ISSUER_ID", "")
    key_content = os.environ.get("ASC_API_KEY_CONTENT", "")
    email = os.environ.get("BETA_TESTER_EMAIL", "")
    first_name = os.environ.get("BETA_TESTER_FIRST_NAME", "")
    last_name = os.environ.get("BETA_TESTER_LAST_NAME", "")

    if not all([key_id, issuer_id, key_content, email]):
        print("Missing required env vars")
        sys.exit(1)

    jwt = make_jwt(key_id, issuer_id, key_content)
    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection("api.appstoreconnect.apple.com", context=ctx)

    bundle_id = "cloud.dkroeker.GaussianSplattingViewer"

    # Get app
    status, data = asc(conn, jwt, "GET", f"/v1/apps?filter[bundleId]={bundle_id}")
    if status != 200 or not data.get("data"):
        print(f"App not found: {status} {data}")
        sys.exit(1)
    app_id = data["data"][0]["id"]
    print(f"App: {app_id}")

    # Get beta groups
    status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/betaGroups")
    groups = data.get("data", [])

    # Find or create an EXTERNAL beta group
    ext_group = None
    for g in groups:
        if not g.get("attributes", {}).get("isInternalGroup", True):
            ext_group = g
            break

    if ext_group:
        group_id = ext_group["id"]
        print(f"Using existing external group: {ext_group['attributes']['name']} ({group_id})")
    else:
        # Create external group
        print("Creating external beta group 'External Testers'...")
        status, data = asc(conn, jwt, "POST", "/v1/betaGroups", {
            "data": {
                "type": "betaGroups",
                "attributes": {
                    "name": "External Testers",
                    "hasAccessToAllBuilds": True
                },
                "relationships": {
                    "app": {"data": {"type": "apps", "id": app_id}}
                }
            }
        })
        if status == 201:
            group_id = data["data"]["id"]
            print(f"Created external group: {group_id}")
        else:
            print(f"Failed to create external group: {status} {json.dumps(data, indent=2)}")
            sys.exit(1)

    # Get builds for this app
    status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/builds?limit=5")
    builds = data.get("data", [])
    if not builds:
        print("No builds found!")
        sys.exit(1)

    # Find the latest valid build
    build_id = None
    for b in builds:
        if b["attributes"].get("processingState") == "VALID" and not b["attributes"].get("expired", False):
            build_id = b["id"]
            ver = b["attributes"].get("version", "")
            print(f"Using build: v{ver} ({build_id})")
            break

    if not build_id:
        build_id = builds[0]["id"]
        print(f"Using build (fallback): {build_id}")

    # Assign build to the external group
    status, data = asc(conn, jwt, "POST",
        f"/v1/betaGroups/{group_id}/relationships/builds",
        {"data": [{"type": "builds", "id": build_id}]})
    if status in (200, 201, 204):
        print(f"Build assigned to external group")
    else:
        print(f"Build assignment result: {status} (may already be assigned)")

    # Check if tester already exists (in any group)
    status, data = asc(conn, jwt, "GET", f"/v1/betaTesters?filter[email]={email}")
    if status == 200 and data.get("data"):
        tester_id = data["data"][0]["id"]
        print(f"Tester already exists: {tester_id}")
        # Add to external group
        status, data = asc(conn, jwt, "POST",
            f"/v1/betaGroups/{group_id}/relationships/betaTesters",
            {"data": [{"type": "betaTesters", "id": tester_id}]})
        if status in (200, 201, 204):
            print(f"Added existing tester to external group")
        else:
            print(f"Add to group: {status} {json.dumps(data)[:200]}")
        conn.close()
        return

    # Create beta tester in the external group
    attrs = {"email": email}
    if first_name: attrs["firstName"] = first_name
    if last_name: attrs["lastName"] = last_name

    status, data = asc(conn, jwt, "POST", "/v1/betaTesters", {
        "data": {
            "type": "betaTesters",
            "attributes": attrs,
            "relationships": {
                "betaGroups": {"data": [{"type": "betaGroups", "id": group_id}]}
            }
        }
    })

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
