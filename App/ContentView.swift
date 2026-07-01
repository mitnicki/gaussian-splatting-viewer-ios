// ContentView.swift
// Main view — tabbed interface with local file picker (M1) and Nextcloud browser (M2).
// Adapted from MetalSplatter SampleApp's ContentView (MIT).
//
// M1: Local file picker for .ply / .splat / .spz
// M2: Nextcloud WebDAV browser with download + cache

import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @State private var selectedTab = 0

    var body: some View {
        TabView(selection: $selectedTab) {
            // M1: Local file picker
            LocalFilePickerView()
                .tabItem {
                    Label("Local", systemImage: "folder")
                }
                .tag(0)

            // M2: Nextcloud WebDAV browser
            if let creds = nextcloudCredentials() {
                WebDAVBrowseView(credentials: creds)
                    .tabItem {
                        Label("Nextcloud", systemImage: "cloud")
                    }
                    .tag(1)
            } else {
                NoCredentialsView()
                    .tabItem {
                        Label("Nextcloud", systemImage: "cloud.slash")
                    }
                    .tag(1)
            }

            // Settings
            SettingsView()
                .tabItem {
                    Label("Settings", systemImage: "gear")
                }
                .tag(2)
        }
    }

    // MARK: - Credentials

    private func nextcloudCredentials() -> WebDAVCredentials? {
        let defaults = UserDefaults.standard
        guard let serverStr = defaults.string(forKey: "nextcloud.serverURL"),
              !serverStr.isEmpty,
              let username = defaults.string(forKey: "nextcloud.username"),
              !username.isEmpty,
              let url = URL(string: serverStr) else {
            return nil
        }

        let password = KeychainHelper.shared.read(account: username) ?? ""
        guard !password.isEmpty else { return nil }

        return WebDAVCredentials(serverURL: url,
                                  username: username,
                                  appPassword: password)
    }
}

// MARK: - Local File Picker (M1)

struct LocalFilePickerView: View {
    @State private var isPickingFile = false
    @State private var navigationPath = NavigationPath()

    var body: some View {
        NavigationStack(path: $navigationPath) {
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
            .navigationDestination(for: SplatSource.self) { source in
                MetalKitSceneView(url: source.url)
                    .navigationTitle(source.url.lastPathComponent)
                    .navigationBarTitleDisplayMode(.inline)
            }
        }
    }
}

// MARK: - No Credentials Placeholder

struct NoCredentialsView: View {
    var body: some View {
        NavigationStack {
            VStack(spacing: 16) {
                Image(systemName: "cloud.slash")
                    .font(.system(size: 48))
                    .foregroundStyle(.secondary)

                Text("Nextcloud Not Configured")
                    .font(.title3.bold())

                Text("Go to Settings to configure your Nextcloud server URL, username, and app password.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .navigationTitle("Nextcloud")
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}
