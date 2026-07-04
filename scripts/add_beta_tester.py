#!/usr/bin/env python3
"""Add a beta tester to App Store Connect — tries internal group first."""
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

    status, data = asc(conn, jwt, "GET", f"/v1/apps?filter[bundleId]={bundle_id}")
    app_id = data["data"][0]["id"]
    print(f"App: {app_id}")

    # Get all beta groups
    status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/betaGroups")
    groups = data.get("data", [])
    for g in groups:
        print(f"  Group: {g['attributes']['name']} internal={g['attributes'].get('isInternalGroup',False)} ({g['id']})")

    # Try INTERNAL group first (no beta review needed)
    internal_group = None
    external_group = None
    for g in groups:
        if g.get("attributes", {}).get("isInternalGroup"):
            internal_group = g
        else:
            external_group = g

    # Try adding to internal group
    if internal_group:
        group_id = internal_group["id"]
        print(f"\nTrying INTERNAL group: {internal_group['attributes']['name']}")

        # Check if tester already exists
        status, data = asc(conn, jwt, "GET", f"/v1/betaTesters?filter[email]={email}")
        if status == 200 and data.get("data"):
            tester_id = data["data"][0]["id"]
            state = data["data"][0]["attributes"].get("state", "")
            print(f"Tester exists: {tester_id} state={state}")
            # Add to internal group
            status, data = asc(conn, jwt, "POST",
                f"/v1/betaGroups/{group_id}/relationships/betaTesters",
                {"data": [{"type": "betaTesters", "id": tester_id}]})
            if status in (200, 201, 204):
                print(f"Added to internal group — SUCCESS")
                print(f"TestFlight invite will be sent to {email}")
                conn.close()
                return
            else:
                print(f"Add to internal failed: {status} {json.dumps(data)[:200]}")
        else:
            # Create tester in internal group
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
                print(f"Created tester in internal group: {data['data']['id']}")
                print(f"TestFlight invite sent to {email}")
                conn.close()
                return
            else:
                print(f"Create in internal failed: {status} {json.dumps(data)[:300]}")

    # If internal didn't work, try external (may need beta review)
    if external_group:
        group_id = external_group["id"]
        print(f"\nTrying EXTERNAL group: {external_group['attributes']['name']}")

        status, data = asc(conn, jwt, "GET", f"/v1/betaTesters?filter[email]={email}")
        if status == 200 and data.get("data"):
            tester_id = data["data"][0]["id"]
            state = data["data"][0]["attributes"].get("state", "")
            print(f"Tester exists: {tester_id} state={state}")
            status, data = asc(conn, jwt, "POST",
                f"/v1/betaGroups/{group_id}/relationships/betaTesters",
                {"data": [{"type": "betaTesters", "id": tester_id}]})
            if status in (200, 201, 204):
                print(f"Added to external group")
                print(f"Tester will be invited once beta app review approves")
                conn.close()
                return
            else:
                print(f"Add to external failed: {status} {json.dumps(data)[:200]}")
        else:
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
                print(f"Created tester in external group: {data['data']['id']}")
                conn.close()
                return
            else:
                print(f"Create in external failed: {status} {json.dumps(data)[:300]}")

    print(f"\nCould not add {email} to any group")
    print("Note: external testers require beta app review approval first.")
    print("The tester may already be in a group with state=NOT_INVITED (pending review).")
    conn.close()

if __name__ == "__main__":
    main()
