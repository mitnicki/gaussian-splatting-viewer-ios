// SplatRendererView.swift
// SwiftUI wrapper that adds loading / error states around MetalKitSceneView,
// plus a floating control overlay (auto-rotate toggle, reset, gesture hints).

#if os(iOS)

import SwiftUI

struct SplatRendererView: View {
    let url: URL?

    @State private var loadState: LoadState = .loading
    @State private var renderer: MetalKitSceneRenderer?
    @State private var autoRotate: Bool = false
    @State private var showControls: Bool = true

    private enum LoadState: Equatable {
        case loading
        case ready
        case error(String)
    }

    var body: some View {
        ZStack {
            MetalKitSceneView(
                url: url,
                onLoadComplete: { error in
                    if let error {
                        loadState = .error(error.localizedDescription)
                    } else {
                        loadState = .ready
                    }
                },
                onRendererReady: { r in
                    renderer = r
                    autoRotate = r.autoRotate
                }
            )
            .ignoresSafeArea()

            if loadState == .ready, let renderer {
                controlOverlay(renderer)
                    .transition(.opacity)
            }

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
        .tint(.ciAccent)
        }
        .animation(.easeInOut(duration: 0.25), value: loadState)
        .task(id: url) {
            loadState = .loading

            guard let url else {
                loadState = .error("No file URL")
                return
            }

            if !FileManager.default.fileExists(atPath: url.path) {
                loadState = .error("File not found: \(url.lastPathComponent)")
                return
            }

            guard let attrs = try? FileManager.default.attributesOfItem(atPath: url.path),
                  let size = attrs[.size] as? Int64, size > 0 else {
                loadState = .error("File is empty or unreadable")
                return
            }
        }
    }

    // MARK: - Control overlay

    @ViewBuilder
    private func controlOverlay(_ renderer: MetalKitSceneRenderer) -> some View {
        VStack {
            HStack {
                Button {
                    autoRotate.toggle()
                    renderer.autoRotate = autoRotate
                } label: {
                    Image(systemName: autoRotate ? "pause.circle.fill" : "play.circle.fill")
                        .font(.title2)
                        .foregroundStyle(.white)
                        .shadow(radius: 2)
                }

                Button {
                    renderer.resetView()
                    autoRotate = false
                    renderer.autoRotate = false
                } label: {
                    Image(systemName: "arrow.counterclockwise.circle.fill")
                        .font(.title2)
                        .foregroundStyle(.white)
                        .shadow(radius: 2)
                }

                Spacer()

                Button {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        showControls.toggle()
                    }
                } label: {
                    Image(systemName: showControls ? "chevron.up.circle.fill" : "chevron.down.circle.fill")
                        .font(.title2)
                        .foregroundStyle(.white)
                        .shadow(radius: 2)
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)

            if showControls {
                HStack(spacing: 12) {
                    Label("1-finger drag: rotate", systemImage: "hand.draw")
                    Label("2-finger: pan", systemImage: "hand.draw.fill")
                    Label("Pinch: zoom", systemImage: "plus.magnifyingglass")
                }
                .font(.caption2)
                .foregroundStyle(.white.opacity(0.8))
                .shadow(radius: 1)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .background(.ultraThinMaterial.opacity(0.6), in: Capsule())
                .transition(.opacity)
            }

            Spacer()
        }
    }
}

// MARK: - Loading Overlay

private struct LoadingOverlay: View {
    @State private var animatePulse = false

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "cube.transparent")
                .font(.system(size: 48))
                .foregroundStyle(.ciAccent)
                .symbolEffect(.pulse, options: .repeating)
                .scaleEffect(animatePulse ? 1.1 : 1.0)

            Text("Loading splat…")
                .font(.headline)
                .foregroundStyle(.ciTextSecondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.ciBgBase.opacity(0.9))
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
                .foregroundStyle(.ciStatusAmber)

            Text("Failed to Load")
                .font(.headline)
                .foregroundStyle(.ciTextPrimary)

            Text(message)
                .font(.subheadline)
                .foregroundStyle(.ciTextSecondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.ciBgBase.opacity(0.95))
    }
}

#endif // os(iOS)
