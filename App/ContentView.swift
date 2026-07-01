// ContentView.swift
// iOS-only. Presents a file picker for .ply / .splat / .spz and navigates to the
// Metal renderer. Adapted from MetalSplatter SampleApp's ContentView (MIT).
//
// M2 will replace the local file picker with a Nextcloud WebDAV browser.

import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @State private var isPickingFile = false
    @State private var navigationPath = NavigationPath()

    var body: some View {
        NavigationStack(path: $navigationPath) {
            mainView
                .navigationTitle("Splat Viewer")
                .navigationDestination(for: SplatSource.self) { source in
                    MetalKitSceneView(url: source.url)
                        .navigationTitle(source.url.lastPathComponent)
                        .navigationBarTitleDisplayMode(.inline)
                }
        }
    }

    @ViewBuilder
    private var mainView: some View {
        VStack(spacing: 24) {
            Spacer()

            Image(systemName: "cube.transparent")
                .font(.system(size: 56))
                .foregroundStyle(.tint)
                .symbolEffect(.pulse)

            VStack(spacing: 6) {
                Text("Gaussian Splatting Viewer")
                    .font(.title2.bold())
                Text("Native Metal renderer — .ply / .splat / .spz")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Button {
                isPickingFile = true
            } label: {
                Label("Open Splat File", systemImage: "folder")
                    .frame(maxWidth: 240)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(isPickingFile)

            Spacer()
        }
        .padding()
        .fileImporter(
            isPresented: $isPickingFile,
            allowedContentTypes: [
                UTType(filenameExtension: "ply")!,
                UTType(filenameExtension: "splat")!,
                UTType(filenameExtension: "spz")!,
            ]
        ) { result in
            isPickingFile = false
            switch result {
            case .success(let url):
                // Keep the security-scoped resource alive while the renderer uses it.
                _ = url.startAccessingSecurityScopedResource()
                navigationPath.append(SplatSource(url: url))
            case .failure:
                break
            }
        }
    }
}
