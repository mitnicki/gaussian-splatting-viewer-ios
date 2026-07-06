// SettingsView.swift
// SwiftUI settings screen — About / info only.
// Nextcloud WebDAV integration removed per Dennis feedback (v0.11.0):
// files are opened via the native iOS Files picker or "Open In" from other apps.

#if os(iOS)

import SwiftUI

struct SettingsView: View {
    var body: some View {
        Form {
            Section("About") {
                LabeledContent("App Version", value: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.1.0")
                LabeledContent("Renderer", value: "MetalSplatter (Metal)")
                LabeledContent("Format", value: ".ply / .splat / .spz")
            }

            Section("Supported Sources") {
                Text("Open splat files from anywhere via the iOS Files picker — iCloud Drive, local storage, AirDrop, or any cloud provider installed in Files (Nextcloud, Dropbox, Google Drive, etc.).")
                    .font(.ciCaption)
                    .foregroundStyle(.ciTextSecondary)
            }
        }
        .navigationTitle("Settings")
        .navigationBarTitleDisplayMode(.inline)
    }
}

#endif // os(iOS)
