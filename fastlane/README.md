# Fastlane — M3 Deployment Configuration

This directory contains Fastlane configuration for building and distributing
the Gaussian Splatting Viewer via TestFlight and the App Store.

## Prerequisites

1. **Apple Developer Account** (~99 EUR/yr) — Dennis needs to create this.
2. **XcodeGen** — `brew install xcodegen`
3. **Fastlane** — `brew install fastlane`

## Setup (one-time)

After creating the Apple Developer Account:

```sh
# 1. Fill in your Apple ID + team ID in fastlane/Appfile
#    (Find team ID at https://developer.apple.com/account)

# 2. Create a private git repo for code signing certs
#    (or use fastlane's storage backend)

# 3. Fill in the match git URL in fastlane/Matchfile

# 4. Generate the Xcode project
xcodegen generate

# 5. Set up code signing
fastlane match development
fastlane match appstore
```

## Usage

```sh
# Upload to TestFlight (beta testing)
fastlane beta

# Upload to App Store
fastlane release

# Generate screenshots
fastlane screenshots
```

## CI Integration

The GitHub Actions workflow (`.github/workflows/ios-build.yml`) currently
builds for the iOS Simulator (no signing required). For CI-based TestFlight
uploads, add a `fastlane beta` step to the workflow with App Store Connect
API key stored as a GitHub secret.
