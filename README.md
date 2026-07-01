# Gaussian Splatting Viewer (iOS) — M1 PoC

Native iOS app that renders Gaussian Splatting scenes (`.ply` / `.splat` / `.spz`)
using [MetalSplatter](https://github.com/scier/MetalSplatter) and Apple's Metal
framework. Built for the kroeker homelab to view `rc390_alte_muehle` and other
splats on iPhone/iPad where iOS Safari's 384 MB WebGL cap makes the web viewer
 unusable (see DKR-97 / DKR-179).

> **Status:** M1 (Proof of Concept). The app loads a local splat file and renders
> it with Metal. M2 will add a Nextcloud WebDAV browser so splats can be streamed
> directly from `files.dkroeker.de` without side-loading.

---

## Why native?

iOS Safari caps a single WebGL tab at ~384 MB. The source `rc340_alte_muehle.ply`
is 1.1 GB (4.48 M splats, SH3) — physically unrenderable in-browser. Native Metal
on an iPhone 15/16 Pro has access to ~5–6 GB, so the 113 MB `.spz` (9.4×
compression, all splats + SH3 preserved) loads at full fidelity, 60 FPS.

---

## Architecture

```
Nextcloud CT134  ←(WebDAV, M2)→  iOS App
                                  ├─ SwiftUI UI
                                  │   ├─ TabView: Local | Nextcloud | Settings
                                  │   ├─ LocalFilePickerView (M1: .ply/.splat/.spz from Files app)
                                  │   ├─ WebDAVBrowseView (M2: folder navigation, download+cache)
                                  │   └─ SettingsView (M2: Nextcloud server/credentials, Keychain)
                                  ├─ SplatIO: AutodetectSceneReader (.ply/.splat/.spz)
                                  └─ MetalSplatter: SplatRenderer (Metal compute shaders)
```

The app depends on **MetalSplatter** and **SplatIO** via Swift Package Manager
(resolved from the upstream GitHub repo). The rendering path is adapted from
MetalSplatter's MIT-licensed SampleApp, simplified to splat-file loading.

**M2 additions:**
- `WebDAVClient.swift` — Nextcloud WebDAV PROPFIND/GET client (URLSession, no third-party deps)
- `SplatCacheManager.swift` — LRU on-device cache (2 GB max, Caches directory)
- `WebDAVBrowseView.swift` — SwiftUI folder browser with download progress
- `SettingsView.swift` — Nextcloud server config with Keychain storage

## Project structure

| Path | Purpose |
|---|---|
| `project.yml` | XcodeGen spec → generates `GaussianSplattingViewer.xcodeproj` |
| `App/` | SwiftUI app entry, ContentView (file picker), Constants |
| `Scene/` | MetalKit SwiftUI bridge + MTKViewDelegate renderer |
| `Model/` | ModelRenderer protocol, SplatSource, SplatRenderer conformance |
| `Util/` | Matrix math (vendored from Apple sample code) |
| `.github/workflows/ios-build.yml` | CI: build for iOS Simulator on macOS runner |

## Rendering credits

`MetalKitSceneView`, `MetalKitSceneRenderer`, `MatrixMathUtil`, and the
`SplatRenderer` conformance are adapted from the [MetalSplatter
SampleApp](https://github.com/scier/MetalSplatter/tree/main/SampleApp) (MIT
License). See `LICENSE-MetalSplatter.txt`.

---

## Hybrid development workflow (no Mac required)

This repo is designed for the **Linux-author → macOS-CI → TestFlight** loop:

1. **Code is authored on Linux** (agent or human) and pushed to GitHub.
2. **GitHub Actions** runs on a `macos-15` runner: installs XcodeGen, generates
   the `.xcodeproj`, resolves the MetalSplatter SPM dependency, and builds for
   the iOS Simulator — **no code signing needed for a simulator build**.
3. **(M3)** A signed archive is uploaded to TestFlight so Dennis can install it
   on his iPhone. This step needs an Apple Developer account + signing secrets.

> macOS runner minutes are **free for public repos**. Keep this repo public (the
> app is MIT-licensed, matching MetalSplatter) to avoid CI costs.

---

## Getting the first CI build

You need a GitHub repository. Two options:

### Option A — Dennis creates the repo, agent pushes
1. Create a **public** GitHub repo (e.g. `HenkDz/gaussian-splatting-viewer-ios`).
2. Grant the agent a fine-grained PAT with `Contents: read/write` on that repo,
   set as the `GITHUB_TOKEN` / repo secret.
3. The agent pushes this scaffold → CI builds automatically.

### Option B — Push the bundle yourself
1. Create a public repo.
2. Unpack the provided artifact tarball and push:
   ```sh
   tar xzf gaussian-splatting-viewer-ios-m1.tar.gz
   cd gaussian-splatting-viewer-ios
   git init && git add -A && git commit -m "M1 PoC scaffold"
   git branch -M main
   git remote add origin git@github.com:<you>/gaussian-splatting-viewer-ios.git
   git push -u origin main
   ```
3. GitHub Actions builds on push. Watch the **Actions** tab for a green check.

### Local build (if you have a Mac)
```sh
brew install xcodegen
xcodegen generate
open GaussianSplattingViewer.xcodeproj
# In Xcode: pick an iPhone 16 Pro simulator, Cmd+R
```

---

## Milestones

| Phase | Status | Scope |
|---|---|---|
| **M1: PoC** | ✅ scaffold ready | MetalSplatter + `.spz` load + render, CI build |
| **M2: WebDAV** | ▶ code complete, untested | Nextcloud file browser, download + on-device cache |
| **M3: Distribution** | ⏳ | TestFlight (needs Apple Developer Account, ~€99/yr) |

## M2 status

Code is complete and committed. Needs CI build verification (requires GitHub repo).
What M2 adds:

1. **WebDAVClient** — PROPFIND to list directories, GET to download files. Uses URLSession + Basic auth with Nextcloud app password. No third-party dependencies.
2. **SplatCacheManager** — Downloads are cached in the app's Caches directory. LRU eviction at 2 GB max. Cache hits skip re-download.
3. **WebDAVBrowseView** — SwiftUI folder browser. Tap a .spz/.ply/.splat file to download (with progress bar) and render. Folders are navigable.
4. **SettingsView** — Configure Nextcloud server URL, username, and app password. Password stored in iOS Keychain. "Test Connection" button validates credentials.
5. **ContentView** — Now a TabView with Local / Nextcloud / Settings tabs.

## What's needed to proceed past M1

1. **GitHub repo** (public) — to run CI and iterate on builds.
2. **Apple Developer Account** (~€99/yr) — only for M3 (TestFlight distribution).
   M1 and M2 work without it (simulator + local file / WebDAV).

## License

MIT — see `LICENSE`. MetalSplatter and Niantic `spz` are also MIT.
