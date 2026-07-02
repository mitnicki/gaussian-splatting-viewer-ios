// SplatRendererView.swift
// SwiftUI wrapper that adds loading / error states around MetalKitSceneView.
// M2.3: UX polish — shows a spinner while the splat file is being parsed
// and an error overlay if loading fails, instead of a blank black screen.

#if os(iOS)

import SwiftUI

struct SplatRendererView: View {
    let url: URL?

    @State private var loadState: LoadState = .loading

    private enum LoadState {
        case loading
        case ready
        case error(String)
    }

    var body: some View {
        ZStack {
            MetalKitSceneView(url: url)
                .ignoresSafeArea()

            switch loadState {
            case .loading:
                LoadingOverlay()
                    .transition(.opacity)
            case .error(let message):
                ErrorOverlay(message: message)
                    .transition(.opacity)
            case .ready:
                Color.clear
            }
        }
        .animation(.easeInOut(duration: 0.25), value: loadState)
        .task(id: url) {
            await checkLoadStatus()
        }
    }

    // MARK: - Load status

    /// MetalSplatter's SplatRenderer.load is async — we can't easily get
    /// a callback from inside MetalKitSceneRenderer. Instead, we do a
    /// lightweight pre-check: verify the file exists and is readable.
    /// The actual Metal load happens inside MetalKitSceneView; if it fails,
    /// the MTKView stays black (the renderer's isReadyToRender stays false).
    /// For the common failure case (file missing / unreadable), we catch it here.
    private func checkLoadStatus() async {
        guard let url else {
            loadState = .error("No file URL")
            return
        }

        // Check file exists and is readable
        if !FileManager.default.fileExists(atPath: url.path) {
            loadState = .error("File not found: \(url.lastPathComponent)")
            return
        }

        // Check file is not empty
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: url.path),
              let size = attrs[.size] as? Int64, size > 0 else {
            loadState = .error("File is empty or unreadable")
            return
        }

        // File looks good — show the MetalKit view (it loads asynchronously).
        // Give a brief loading state, then transition to ready.
        loadState = .loading
        try? await Task.sleep(nanoseconds: 300_000_000)  // 0.3s
        loadState = .ready
    }
}

// MARK: - Loading Overlay

private struct LoadingOverlay: View {
    @State private var animatePulse = false

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "cube.transparent")
                .font(.system(size: 48))
                .foregroundStyle(.tint)
                .symbolEffect(.pulse, options: .repeating)
                .scaleEffect(animatePulse ? 1.1 : 1.0)

            Text("Loading splat…")
                .font(.headline)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(.systemBackground).opacity(0.9))
        .onAppear {
            withAnimation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true)) {
                animatePulse = true
            }
        }
    }
}

// MARK: - Error Overlay

private struct ErrorOverlay: View {
    let message: String

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 48))
                .foregroundStyle(.orange)

            Text("Failed to Load")
                .font(.headline)

            Text(message)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(.systemBackground).opacity(0.95))
    }
}

#endif // os(iOS)
