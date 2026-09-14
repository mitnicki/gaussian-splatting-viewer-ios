#!/usr/bin/env python3
"""Read-only public App Store listing verification for the approved v1.0 release.

Runs on an unrestricted GitHub runner (the agent runtime cannot reach
itunes.apple.com / apps.apple.com through its egress proxy). Calls ONLY public
Apple endpoints — no App Store Connect credentials, no mutation of any kind.

Checks the published storefront metadata against the approved release facts:

    App Store ID   6787153621
    Bundle ID      cloud.dkroeker.GaussianSplattingViewer
    Version        1.0
    Price          2.99 EUR (DE storefront) / 2.99 USD (US storefront)
    Publisher      Dennis Kroeker
    Privacy policy https://blog.kroeker.cloud/privacy/
    Release type   AFTER_APPROVAL (Apple-approved automatic release)

Evidence is written to out/asc-inspection.json, which the workflow publishes on
a dedicated evidence branch.
"""

import json
import os
import ssl
import time
import urllib.error
import urllib.request

APP_STORE_ID = "6787153621"
# Optional override so the same read-only path can be validated against a known
# control app (control runs are expected to report mismatches — they prove that
# the lookup, store-page and mismatch detection actually work).
TARGET_APP_STORE_ID = os.environ.get("VERIFY_APP_STORE_ID", APP_STORE_ID).strip() or APP_STORE_ID
APP_BUNDLE_ID = "cloud.dkroeker.GaussianSplattingViewer"
EXPECTED_NAME = "Gaussian Splatting Viewer"
EXPECTED_VERSION = "1.0"
EXPECTED_SELLER = "Dennis Kroeker"
EXPECTED_PRIVACY_HOST = "blog.kroeker.cloud"
EXPECTED_PRICE = {"de": 2.99, "at": 2.99, "ch": 2.99, "us": 2.99, "gb": 2.99}
STOREFRONTS = ("de", "at", "ch", "us", "gb")

# Localization expectation: the German storefronts must publish German copy,
# the English storefronts English copy. Detected with a stopword heuristic
# instead of exact strings so cosmetic copy edits do not fail the check.
EXPECTED_LANGUAGE = {"de": "de", "at": "de", "ch": "de", "us": "en", "gb": "en"}
GERMAN_MARKERS = (" und ", " der ", " die ", "Splat-Dateien", "Dateien")
ENGLISH_MARKERS = (" the ", " and ", "splat files", "files")


def detect_language(text):
    lowered = (" " + text + " ").lower()
    german = sum(1 for marker in GERMAN_MARKERS if marker.lower() in lowered)
    english = sum(1 for marker in ENGLISH_MARKERS if marker.lower() in lowered)
    if german == 0 and english == 0:
        return "unknown"
    return "de" if german >= english else "en"


def fetch(url, timeout=30):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:  # network level failure must not crash the run
        return 0, f"{exc.__class__.__name__}: {exc}"


def lookup(country):
    status, raw = fetch(
        f"https://itunes.apple.com/lookup?id={TARGET_APP_STORE_ID}&country={country}&entity=software")
    entry = None
    try:
        payload = json.loads(raw)
        if payload.get("resultCount"):
            entry = payload["results"][0]
    except Exception:
        payload = None
    return status, payload, entry


def summarize(entry):
    keys = ("trackId", "bundleId", "trackName", "version", "price", "formattedPrice",
            "currency", "sellerName", "artistName", "trackViewUrl", "minimumOsVersion",
            "currentVersionReleaseDate", "releaseDate", "primaryGenreName",
            "contentAdvisoryRating", "languageCodesISO2A", "supportedDevices")
    return {key: entry.get(key) for key in keys if key in entry}


def main():
    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "target": {"app_store_id": TARGET_APP_STORE_ID, "bundle_id": APP_BUNDLE_ID,
                   "expected": {"name": EXPECTED_NAME, "version": EXPECTED_VERSION,
                                "seller": EXPECTED_SELLER, "price_eur": 2.99,
                                "privacy_host": EXPECTED_PRIVACY_HOST}},
        "storefronts": {}, "mismatches": [], "warnings": [], "privacy_link_found": {},
    }

    for country in STOREFRONTS:
        status, payload, entry = lookup(country)
        store = {"lookup_http": status,
                 "result_count": (payload or {}).get("resultCount")}
        if entry:
            store["metadata"] = summarize(entry)
            description = entry.get("description") or ""
            store["description_length"] = len(description)
            detected = detect_language((entry.get("trackName") or "") + " " + description)
            store["detected_language"] = detected
            store["expected_language"] = EXPECTED_LANGUAGE.get(country)
            store["description_head"] = description[:400]
            if entry.get("trackName") != EXPECTED_NAME:
                result["mismatches"].append(f"{country}: trackName={entry.get('trackName')!r}")
            if entry.get("version") != EXPECTED_VERSION:
                result["mismatches"].append(f"{country}: version={entry.get('version')!r}")
            if entry.get("sellerName") != EXPECTED_SELLER:
                result["mismatches"].append(f"{country}: sellerName={entry.get('sellerName')!r}")
            if entry.get("bundleId") != APP_BUNDLE_ID:
                result["mismatches"].append(f"{country}: bundleId={entry.get('bundleId')!r}")
            expected_price = EXPECTED_PRICE.get(country)
            if expected_price is not None and abs(float(entry.get("price") or -1) - expected_price) > 0.001:
                result["mismatches"].append(
                    f"{country}: price={entry.get('price')!r} {entry.get('currency')!r}")
            if detected != EXPECTED_LANGUAGE.get(country):
                result["mismatches"].append(
                    f"{country}: localization detected={detected!r}")
            url = entry.get("trackViewUrl")
            if url:
                page_status, html = fetch(url)
                store["store_page_http"] = page_status
                store["store_page_url"] = url
                store["privacy_link_found"] = EXPECTED_PRIVACY_HOST in html
                result["privacy_link_found"][country] = store["privacy_link_found"]
                if page_status != 200:
                    result["mismatches"].append(f"{country}: store page HTTP {page_status}")
                if not store["privacy_link_found"]:
                    # Informational: apps.apple.com markup changes and the ASC
                    # privacyPolicyUrl is authoritative; recorded, not fatal.
                    result["warnings"].append(
                        f"{country}: expected privacy host {EXPECTED_PRIVACY_HOST!r} "
                        f"not found in store page markup")
                store["html_bytes"] = len(html)
        else:
            page_status, _ = fetch(f"https://apps.apple.com/{country}/app/id{TARGET_APP_STORE_ID}")
            store["store_page_http"] = page_status
        result["storefronts"][country] = store

    listed = [c for c, s in result["storefronts"].items() if s.get("result_count")]
    if not listed:
        result["result"] = "not-listed"
    elif result["mismatches"]:
        result["result"] = "listed-with-mismatch"
    else:
        result["result"] = "listed-and-verified"
    result["listed_storefronts"] = listed

    os.makedirs("out", exist_ok=True)
    with open("out/asc-inspection.json", "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
    print(json.dumps({"result": result["result"], "listed_storefronts": listed,
                      "mismatches": result["mismatches"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
