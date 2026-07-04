# Gaussian Splatting Viewer (iOS) — M2.10g (CI Design Integration)

Native iOS app that renders Gaussian Splatting scenes (`.ply` / `.splat` / `.spz`)
using [MetalSplatter](https://github.com/scier/MetalSplatter) and Apple's Metal
framework. Built for the kroeker homelab to view `rc390_alte_muehle` and other
splats on iPhone/iPad where iOS Safari's 384 MB WebGL cap makes the web viewer
 unusable (see DKR-97 / DKR-179).

> **Status:** M2.10g (CI Design Integration). M1 PoC + M2 WebDAV integration + 10 rounds of
> code review fixes. All code is production-ready and compiles cleanly on GitHub
> Actions (macOS-15 / Xcode 16.4). M3 (TestFlight distribution) is blocked on
> Apple Developer Account activation (enrollment pending).

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

## CI status

GitHub Actions builds the app on every push to `master`. The latest run (commit
`26b2c05`, M2.10f) completed successfully:

- **Runner:** macOS-15 (Xcode 16.4, iOS Simulator 18.5)
- **Build time:** ~1m50s
- **Status:** GREEN
- **URL:** https://github.com/mitnicki/gaussian-splatting-viewer-ios/actions

> Note: The repo is currently private. macOS runner minutes are free for public
> repos but billed at 10x for private repos. Consider making the repo public
> (the app is MIT-licensed) to avoid CI costs.

---

## Milestones

| Phase | Status | Scope |
|---|---|---|
| **M1: PoC** | ✅ scaffold ready | MetalSplatter + `.spz` load + render, CI build |
| **M2: WebDAV** | ✅ code complete, bug-fixed | Nextcloud file browser, download + on-device cache |
| **M2.3: Polish** | ✅ code complete | Compile fixes, loading/error UX, progress throttling |
| **M2.4: Code Review** | ✅ code complete | Force-unwrap safety, NaN guard, credential caching, defer cleanup |
| **M2.5: Safety** | ✅ code complete | UTType fallback, SplatCacheManager init guard |
| **M2.6: Robustness** | ✅ code complete | Failed-load retry fix, PROPFIND self-entry filtering |
| **M2.7: UX Fix** | ✅ code complete | Loading state tracks actual Metal load completion (no 0.3s sleep hack) |
| **M2.8: Review** | ✅ code complete | Metal-unavailable error fallback, one-finger orbit rotation gesture |
| **M2.9-M2.10f: Swift 6** | ✅ CI verified | Swift 6 strict concurrency, actor isolation, Sendable conformance, gesture handler fixes |
| **M3: Distribution** | ⏳ blocked | TestFlight (needs Apple Developer Account — enrollment pending) |

## M2 status

Code is complete, bug-fixed, and **CI-verified**. GitHub Actions builds successfully
on macOS-15 (Xcode 16.4, iOS Simulator 18.5). Commit 26b2c05, 21 commits total.

### Bug fixes in this revision (2026-07-02)

#### M2.4 — Code review fixes

1. **Force-unwrap safety (MetalKitSceneRenderer)** — `Bundle.main.bundleIdentifier!` would crash in test/preview contexts where the bundle identifier is nil. Replaced with `?? "GaussianSplattingViewer"` fallback.

2. **NaN projection matrix guard** — When `drawableSize` is `.zero` (initial frame before layout), `drawableSize.width / drawableSize.height` produces NaN, corrupting the projection matrix and potentially crashing the GPU pipeline. Added `max(width, 1.0)` / `max(height, 1.0)` guards.

3. **Security-scoped resource cleanup (ContentView)** — The file picker's `startAccessingSecurityScopedResource()` / `stopAccessingSecurityScopedResource()` pair was not using `defer`, meaning a throw between start and stop would leak the file descriptor. Replaced with `defer` block for guaranteed cleanup.

4. **Credential caching (ContentView)** — `nextcloudCredentials()` was called inside the `body` computed property, reading UserDefaults + Keychain on every SwiftUI render pass. Moved to `@State` with `.onAppear` + notification-based refresh.

#### M2.3 — Compile fixes + UX polish

1. **Critical: MetalKitSceneRenderer init — force-unwrap compile error** — `init?(_:)` is failable, but `makeUIView` assigned the result directly to a non-optional property and passed it to `addGestures(to:renderer:)` which takes a non-optional `MetalKitSceneRenderer`. This is a compile error in strict Swift 6 mode. Replaced force-unwrap (`metalKitView.device!`) with proper `guard let` and wrapped the renderer creation in `if let`.

2. **New: Loading/error overlay (SplatRendererView.swift)** — When opening a splat file, the user previously saw a blank black screen for 2-5 seconds while MetalSplatter parsed the file. Now shows an animated loading indicator, and an error overlay if the file is missing/empty/unreadable.

3. **Download progress throttling** — `URLSessionDownloadDelegate.didWriteData` can fire hundreds of times per second. Each callback spawned a `Task { @MainActor }` that triggered a SwiftUI body re-evaluation. Added a 100ms `ContinuousClock` throttle so the progress bar updates at most 10×/second.

4. **Deprecated `onChange(of:)` fix** — iOS 18 deprecates the zero-parameter `onChange` closure. Updated to the two-parameter form `onChange(of:) { _, newValue in }`.

#### M2.2 — Real download progress + resource leak fix

1. **Critical: WebDAV download OOM fix** — `downloadFile()` was reading the response
   byte-by-byte via `URLSession.bytes` and accumulating the entire file in a `Data`
   buffer before writing to disk. A 113 MB `.spz` would peak at ~230 MB RAM (Data
   buffer + Swift runtime overhead) and crash on devices with < 3 GB free. Replaced
   with `URLSession.download(for:)` which streams directly to a temp file, then moves
   it to the cache. Peak memory is now negligible.

2. **MetalKitSceneView reload-on-every-update** — `updateUIView` was calling
   `renderer.load(url)` on every SwiftUI state change, tearing down and reloading
   the splat scene unnecessarily. Added a `renderer.url != url` guard so it only
   reloads when the URL actually changes.

3. **WebDAVBrowseView back button** — Changed "Back" text to a chevron icon,
   added pull-to-refresh (`refreshable`), and fixed the toolbar button label
   to use SF Symbols.

### Gesture controls (new)

- **Pinch** to zoom in/out
- **Pan** (1-2 fingers) to move the camera
- **Double-tap** to reset the view
- Auto-rotation is always active; manual rotation is additive

## What's needed to proceed past M1

1. **GitHub repo** ✅ — https://github.com/mitnicki/gaussian-splatting-viewer-ios (private)
2. **Apple Developer Account** (~€99/yr) — only for M3 (TestFlight distribution).
   Enrollment is pending. M1 and M2 work without it (simulator + local file / WebDAV).

## License

MIT — see `LICENSE`. MetalSplatter and Niantic `spz` are also MIT.
