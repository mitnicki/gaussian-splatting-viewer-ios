#!/usr/bin/env python3
"""Submit build for App Store review — creates version, uploads metadata + screenshots, links build, submits.

Handles the full flow via ASC API:
1. Get app
2. Get latest valid build
3. Find or create App Store version (handles version string mismatch)
4. Create or update localizations (de-DE, en-US) with metadata from fastlane/metadata/
5. Upload screenshots to ASC
6. Link build to version
7. Submit for review
"""
import json, time, sys, os, base64, pathlib, struct, zlib
import http.client, ssl, urllib.request

def make_jwt(key_id, issuer_id, key_content):
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    key_pem = key_content
    if "BEGIN PRIVATE KEY" not in key_pem:
        key_pem = "[REDACTED PRIVATE KEY]\n"
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

def read_meta(locale, field):
    p = pathlib.Path("fastlane/metadata") / locale / f"{field}.txt"
    if p.exists():
        return p.read_text().strip()
    return ""

def png_dimensions(path):
    with open(path, "rb") as f:
        data = f.read(24)
        if data[:8] != b'\x89PNG\r\n\x1a\n':
            return None, None
        w, h = struct.unpack('>II', data[16:24])
        return w, h

def upload_screenshot(conn, jwt, localization_id, screenshot_path, display_type="APP_IPHONE_67"):
    """Upload a single screenshot to ASC. Returns True on success."""
    # Check if screenshot set already exists for this locale + display type
    status, data = asc(conn, jwt, "GET",
        f"/v1/appStoreVersionLocalizations/{localization_id}/appScreenshotSets?limit=10")
    existing_set_id = None
    if status == 200:
        for ss in data.get("data", []):
            if ss.get("attributes", {}).get("screenshotDisplayType") == display_type:
                existing_set_id = ss["id"]
                break

    # Create screenshot set if needed
    if not existing_set_id:
        status, data = asc(conn, jwt, "POST", "/v1/appScreenshotSets", {
            "data": {
                "type": "appScreenshotSets",
                "attributes": {"screenshotDisplayType": display_type},
                "relationships": {
                    "appStoreVersionLocalization": {
                        "data": {"type": "appStoreVersionLocalizations", "id": localization_id}
                    }
                }
            }
        })
        if status not in (200, 201):
            print(f"    ERROR creating screenshot set: {status} {json.dumps(data)[:300]}")
            return False
        existing_set_id = data["data"]["id"]
        print(f"    Created screenshot set: {existing_set_id}")
    else:
        print(f"    Using existing screenshot set: {existing_set_id}")

    # Check if screenshots already exist in the set AND have valid image assets
    status, data = asc(conn, jwt, "GET",
        f"/v1/appScreenshotSets/{existing_set_id}/appScreenshots?limit=10")
    if status == 200 and data.get("data"):
        valid_count = 0
        for ss in data["data"]:
            if ss.get("attributes", {}).get("imageAsset"):
                valid_count += 1
        if valid_count > 0:
            print(f"    Screenshots already exist ({valid_count} valid) — skipping upload")
            return True
        else:
            print(f"    Screenshot entries exist but no valid images — re-uploading")

    # Create appScreenshot — this returns uploadOperation with upload URL
    file_size = os.path.getsize(screenshot_path)
    status, data = asc(conn, jwt, "POST", "/v1/appScreenshots", {
        "data": {
            "type": "appScreenshots",
            "attributes": {
                "fileSize": file_size,
                "fileName": os.path.basename(screenshot_path)
            },
            "relationships": {
                "appScreenshotSet": {
                    "data": {"type": "appScreenshotSets", "id": existing_set_id}
                }
            }
        }
    })
    if status not in (200, 201):
        print(f"    ERROR creating screenshot: {status} {json.dumps(data)[:300]}")
        return False

    screenshot_id = data["data"]["id"]
    # ASC API returns uploadOperations directly in attributes
    upload_ops = data["data"].get("attributes", {}).get("uploadOperations", [])

    if not upload_ops:
        print(f"    ERROR: No upload operations returned. Response: {json.dumps(data)[:500]}")
        return False

    # Upload each chunk (usually single chunk for screenshots)
    with open(screenshot_path, "rb") as f:
        file_data = f.read()

    for op in upload_ops:
        upload_url = op.get("url", "")
        if not upload_url:
            print(f"    ERROR: No upload URL in operation: {json.dumps(op)[:200]}")
            return False

        req = urllib.request.Request(upload_url, data=file_data, method=op.get("method", "PUT"))
        req.add_header("Content-Type", "application/octet-stream")
        try:
            resp = urllib.request.urlopen(req)
            if resp.status not in (200, 204):
                print(f"    ERROR uploading image: HTTP {resp.status}")
                return False
        except Exception as e:
            print(f"    ERROR uploading image: {e}")
            return False

    # Commit the upload
    status, data = asc(conn, jwt, "PATCH", f"/v1/appScreenshots/{screenshot_id}", {
        "data": {
            "type": "appScreenshots",
            "id": screenshot_id,
            "attributes": {"uploaded": True}
        }
    })
    if status not in (200, 201):
        print(f"    ERROR committing screenshot: {status} {json.dumps(data)[:300]}")
        return False

    print(f"    Uploaded: {os.path.basename(screenshot_path)} ({file_size} bytes)")
    return True

key_id = os.environ.get("ASC_API_KEY_ID", "")
issuer_id = os.environ.get("ASC_ISSUER_ID", "")
key_content = os.environ.get("ASC_API_KEY_CONTENT", "")
app_version_raw = os.environ.get("APP_VERSION", "1.0.0")
app_version = app_version_raw.lstrip("v")
price_tier = int(os.environ.get("PRICE_TIER", "3"))

if not all([key_id, issuer_id, key_content]):
    print("ERROR: ASC_API_KEY_ID, ASC_ISSUER_ID, ASC_API_KEY_CONTENT must be set")
    sys.exit(1)

jwt = make_jwt(key_id, issuer_id, key_content)
ctx = ssl.create_default_context()
conn = http.client.HTTPSConnection("api.appstoreconnect.apple.com", context=ctx)

bundle_id = "cloud.dkroeker.GaussianSplattingViewer"

# 1. Get app
status, data = asc(conn, jwt, "GET", f"/v1/apps?filter[bundleId]={bundle_id}")
if status != 200 or not data.get("data"):
    print(f"ERROR: App not found (status={status}): {json.dumps(data)[:300]}")
    sys.exit(1)
app_id = data["data"][0]["id"]
print(f"App: {app_id} ({bundle_id})")

# 2. Get latest VALID build
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/builds?limit=20")
if status != 200:
    print(f"ERROR: Could not fetch builds (status={status}): {json.dumps(data)[:300]}")
    sys.exit(1)

valid_builds = []
for b in data.get("data", []):
    attrs = b["attributes"]
    if attrs.get("processingState") == "VALID" and not attrs.get("expired", False):
        valid_builds.append(b)

if not valid_builds:
    print("ERROR: No valid (processed, non-expired) builds found.")
    sys.exit(1)

valid_builds.sort(key=lambda b: int(b["attributes"].get("version", "0")), reverse=True)
build = valid_builds[0]
build_id = build["id"]
build_version = build["attributes"]["version"]
print(f"Latest valid build: {build_id} (version {build_version})")

# 3. Find or create App Store version
# First, look for ANY version in PREPARE_FOR_SUBMISSION state (handles version string mismatch)
status, data = asc(conn, jwt, "GET", f"/v1/apps/{app_id}/appStoreVersions")
app_store_version_id = None
if status == 200:
    for v in data.get("data", []):
        state = v["attributes"].get("appStoreState", "")
        vstr = v["attributes"].get("versionString", "")
        if state == "PREPARE_FOR_SUBMISSION":
            app_store_version_id = v["id"]
            app_version = vstr  # use the actual ASC version string
            print(f"Found existing version {vstr} in PREPARE_FOR_SUBMISSION: {app_store_version_id}")
            break
        elif state in ("WAITING_FOR_REVIEW", "IN_REVIEW", "PENDING_DEVELOPER_RELEASE", "READY_FOR_SALE"):
            print(f"Version {vstr} already in state {state} — nothing to do.")
            sys.exit(0)

if not app_store_version_id:
    print(f"Creating App Store version {app_version}...")
    status, data = asc(conn, jwt, "POST", "/v1/appStoreVersions", {
        "data": {
            "type": "appStoreVersions",
            "attributes": {
                "platform": "IOS",
                "versionString": app_version,
                "copyright": "2026 Dennis Kroeker",
                "releaseType": "MANUAL",
                "usesIdfa": False
            },
            "relationships": {
                "app": {"data": {"type": "apps", "id": app_id}}
            }
        }
    })
    if status == 201:
        app_store_version_id = data["data"]["id"]
        print(f"Created App Store version: {app_store_version_id}")
    else:
        print(f"ERROR creating version (status={status}): {json.dumps(data)[:500]}")
        sys.exit(1)

# 4. Upload metadata (create or update localizations)
print(f"\nUploading metadata for version {app_version}...")

status, loc_data = asc(conn, jwt, "GET", f"/v1/appStoreVersions/{app_store_version_id}/appStoreVersionLocalizations?limit=20")
existing_locales = {}
if status == 200:
    for loc in loc_data.get("data", []):
        existing_locales[loc["attributes"]["locale"]] = loc["id"]

locales_meta = {
    "de-DE": {
        "description": read_meta("de-DE", "description"),
        "keywords": read_meta("de-DE", "keywords"),
        "promotional_text": read_meta("de-DE", "promotional_text"),
    },
    "en-US": {
        "description": read_meta("en-US", "description"),
        "keywords": read_meta("en-US", "keywords"),
        "promotional_text": read_meta("en-US", "promotional_text"),
    }
}

for locale, meta in locales_meta.items():
    asc_attrs = {
        "description": meta["description"],
        "keywords": meta["keywords"],
        "promotionalText": meta["promotional_text"],
    }

    if locale in existing_locales:
        loc_id = existing_locales[locale]
        print(f"  Updating {locale} ({loc_id})...")
        status, data = asc(conn, jwt, "PATCH", f"/v1/appStoreVersionLocalizations/{loc_id}", {
            "data": {
                "type": "appStoreVersionLocalizations",
                "id": loc_id,
                "attributes": asc_attrs
            }
        })
        if status == 200:
            print(f"    OK — updated")
        else:
            print(f"    WARNING: status={status} {json.dumps(data)[:300]}")
    else:
        print(f"  Creating {locale}...")
        status, data = asc(conn, jwt, "POST", "/v1/appStoreVersionLocalizations", {
            "data": {
                "type": "appStoreVersionLocalizations",
                "attributes": {
                    "locale": locale,
                    **asc_attrs
                },
                "relationships": {
                    "appStoreVersion": {
                        "data": {"type": "appStoreVersions", "id": app_store_version_id}
                    }
                }
            }
        })
        if status == 201:
            loc_id = data["data"]["id"]
            existing_locales[locale] = loc_id
            print(f"    OK — created ({loc_id})")
        else:
            print(f"    WARNING: status={status} {json.dumps(data)[:300]}")

# 5. Upload screenshots
print(f"\nUploading screenshots...")
for locale in ["de-DE", "en-US"]:
    loc_id = existing_locales.get(locale)
    if not loc_id:
        print(f"  Skipping {locale} — no localization ID")
        continue
    print(f"  {locale}:")
    ss_dir = pathlib.Path(f"fastlane/metadata/{locale}/screenshots")
    if not ss_dir.exists():
        print(f"    No screenshots directory found")
        continue
    for ss_file in sorted(ss_dir.glob("*.png")):
        w, h = png_dimensions(str(ss_file))
        print(f"    {ss_file.name}: {w}x{h}")
        upload_screenshot(conn, jwt, loc_id, str(ss_file))

# 6. Link build to App Store version
print(f"\nLinking build {build_id} to App Store version {app_store_version_id}...")
status, data = asc(conn, jwt, "PATCH", f"/v1/appStoreVersions/{app_store_version_id}/relationships/build", {
    "data": {"type": "builds", "id": build_id}
})
if status in (200, 204):
    print("Build linked successfully.")
else:
    print(f"WARNING: Link build returned {status}: {json.dumps(data)[:300]}")

# 7. Submit for review
print(f"\nSubmitting App Store version {app_version} for review...")
time.sleep(5)

for attempt in range(3):
    status, data = asc(conn, jwt, "POST", f"/v1/appStoreVersions/{app_store_version_id}/submission", {
        "data": {
            "type": "appStoreVersionSubmissions",
            "relationships": {
                "appStoreVersion": {
                    "data": {"type": "appStoreVersions", "id": app_store_version_id}
                }
            }
        }
    })
    if status == 201:
        sub_id = data["data"]["id"]
        state = data["data"]["attributes"].get("state", "")
        print(f"SUCCESS — Submission created: {sub_id} state={state}")
        print(f"App Store version {app_version} (build {build_version}) submitted for review.")
        print("Review typically takes 24-48 hours.")
        break
    elif status == 422:
        err_detail = ""
        if data.get("errors"):
            for e in data["errors"]:
                err_detail += e.get("detail", "") + " "
        print(f"Attempt {attempt+1}: 422 — {err_detail.strip()}")
        if attempt < 2:
            print("Waiting 15s...")
            time.sleep(15)
    elif status == 409:
        print(f"Already submitted: {json.dumps(data)[:200]}")
        break
    else:
        print(f"Attempt {attempt+1}: {status} {json.dumps(data)[:500]}")
        if attempt < 2:
            time.sleep(10)

conn.close()
print("\nDone.")
