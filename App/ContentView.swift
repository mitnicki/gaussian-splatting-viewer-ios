// ContentView.swift
// Main view — single-tab file picker using the native iOS Files document picker.
// Supports .ply / .splat / .spz from any Files provider (iCloud, local, Nextcloud app, etc.)
// Also handles "Open In" from other apps via UTType declarations.
// Adapted from MetalSplatter SampleApp's ContentView (MIT).

import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @State private var isPickingFile = false
    @State private var importedFile: SplatSource?

    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                Spacer()

                Image(systemName: "cube.transparent")
                    .font(.system(size: 56))
                    .foregroundStyle(.ciAccent)
                    .symbolEffect(.pulse)

                VStack(spacing: 6) {
                    Text("Gaussian Splatting Viewer")
                        .font(.ciH3)
                        .foregroundStyle(.ciTextPrimary)
                    Text("Native Metal renderer — .ply / .splat / .spz")
                        .font(.ciCaption)
                        .foregroundStyle(.ciTextSecondary)
                    
                    // Feature hints
                    VStack(spacing: 4) {
                        Text("Tap 'Try Demo' or open a file to access:")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(.ciTextSecondary)
                        Text("Rotate · Zoom · Screenshot · Auto-rotate")
                            .font(.system(size: 11))
                            .foregroundStyle(.ciTextSecondary.opacity(0.7))
                    }
                    .padding(.top, 8)
                }

                Spacer()

                HStack(spacing: 12) {
                    Button {
                        isPickingFile = true
                    } label: {
                        Label("Open Splat File", systemImage: "folder")
                            .frame(maxWidth: 180)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(isPickingFile)

                    Button {
                        if let demoURL = Bundle.main.url(forResource: "demo_scene", withExtension: "splat", subdirectory: "DemoData") {
                            importedFile = SplatSource(url: demoURL)
                        }
                    } label: {
                        Label("Try Demo", systemImage: "sparkles")
                            .frame(maxWidth: 120)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.large)
                }

                Spacer()
            }
            .padding()
            .background(.ciBgBase)
            .fileImporter(
                isPresented: $isPickingFile,
                allowedContentTypes: SplatFileTypes.all,
                allowsMultipleSelection: false
            ) { result in
                isPickingFile = false
                switch result {
                case .success(let urls):
                    if let url = urls.first {
                        importFile(url)
                    }
                case .failure:
                    break
                }
            }
            .navigationDestination(item: $importedFile) { source in
                SplatRendererView(url: source.url)
                    .navigationTitle(source.url.lastPathComponent)
                    .navigationBarTitleDisplayMode(.inline)
            }
        }
        .onOpenURL { url in
            // Handle "Open In" from other apps (Files, Mail, AirDrop, etc.)
            importFile(url)
        }
    }

    // MARK: - File Import

    private func importFile(_ url: URL) {
        // Copy security-scoped file into app's tmp dir so it stays
        // accessible without permanently holding the scope open.
        let tmpURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString + "-" + url.lastPathComponent)
        let didStartAccessing = url.startAccessingSecurityScopedResource()
        defer {
            if didStartAccessing {
                url.stopAccessingSecurityScopedResource()
            }
        }
        do {
            try FileManager.default.copyItem(at: url, to: tmpURL)
            importedFile = SplatSource(url: tmpURL)
        } catch {
            // Fallback: use original URL (may work for some providers)
            importedFile = SplatSource(url: url)
        }
    }
}

// MARK: - Splat File Types

enum SplatFileTypes {
    static let all: [UTType] = [
        UTType(filenameExtension: "ply") ?? .data,
        UTType(filenameExtension: "splat") ?? .data,
        UTType(filenameExtension: "spz") ?? .data,
    ]
}
