// SettingsView.swift
// SwiftUI settings screen for configuring Nextcloud WebDAV connection.
// Stores credentials in iOS Keychain.
// M2: Nextcloud integration.

#if os(iOS)

import SwiftUI
import Security

struct SettingsView: View {
    @AppStorage("nextcloud.serverURL") private var serverURLString: String = ""
    @AppStorage("nextcloud.username") private var username: String = ""
    @State private var appPassword: String = ""
    @State private var showSavedAlert = false
    @State private var testingConnection = false
    @State private var connectionResult: String?

    var body: some View {
        Form {
            Section("Nextcloud Server") {
                TextField("Server URL", text: $serverURLString,
                           prompt: Text("https://files.dkroeker.de"))
                    .keyboardType(.URL)
                    .autocapitalization(.none)
                    .textContentType(.URL)
                TextField("Username", text: $username,
                           prompt: Text("dennis"))
                    .autocapitalization(.none)
                    .textContentType(.username)
                SecureField("App Password", text: $appPassword,
                             prompt: Text("Nextcloud app password"))
                    .textContentType(.password)
            }

            Section {
                Button("Test Connection") {
                    Task { await testConnection() }
                }
                .disabled(testingConnection || serverURLString.isEmpty || username.isEmpty)

                if testingConnection {
                    ProgressView("Testing...")
                }

                if let result = connectionResult {
                    Text(result)
                        .font(.ciCaption)
                        .foregroundStyle(result.starts(with: "✓") ? Color.ciStatusGreen : Color.ciStatusRed)
                }
            }

            Section("About") {
                LabeledContent("App Version", value: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.1.0")
                LabeledContent("Renderer", value: "MetalSplatter (Metal)")
                LabeledContent("Format", value: ".ply / .splat / .spz")
            }

            Section("How to get an app password") {
                Text("1. Open your Nextcloud in a browser\n2. Go to Settings → Security\n3. Under 'Devices & sessions', enter a name (e.g. 'Splat Viewer')\n4. Click 'Create new app password'\n5. Copy the password here")
                    .font(.ciCaption)
                    .foregroundStyle(.ciTextSecondary)
            }
        }
        .navigationTitle("Settings")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            appPassword = KeychainHelper.shared.read(account: username) ?? ""
        }
        .onChange(of: appPassword) { _, newValue in
            if !username.isEmpty {
                KeychainHelper.shared.save(account: username, password: newValue)
                NotificationCenter.default.post(name: .nextcloudCredentialsChanged, object: nil)
            }
        }
        .onChange(of: serverURLString) { _, _ in
            NotificationCenter.default.post(name: .nextcloudCredentialsChanged, object: nil)
        }
        .onChange(of: username) { _, _ in
            NotificationCenter.default.post(name: .nextcloudCredentialsChanged, object: nil)
        }
    }

    // MARK: - Connection test

    private func testConnection() async {
        guard let url = URL(string: serverURLString) else {
            connectionResult = "Invalid URL"
            return
        }

        testingConnection = true
        connectionResult = nil

        let creds = WebDAVCredentials(serverURL: url,
                                        username: username,
                                        appPassword: appPassword)
        let client = WebDAVClient(credentials: creds)

        do {
            let entries = try await client.listDirectory(relativePath: "")
            testingConnection = false
            connectionResult = "✓ Connected — \(entries.count) items in root"
        } catch {
            testingConnection = false
            connectionResult = "✗ \(error.localizedDescription)"
        }
    }
}

// MARK: - Keychain helper

final class KeychainHelper: @unchecked Sendable {
    static let shared = KeychainHelper()
    private let service = "cloud.dkroeker.GaussianSplattingViewer"

    private init() {}

    func save(account: String, password: String) {
        guard let data = password.data(using: .utf8) else { return }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]

        // Delete existing
        SecItemDelete(query as CFDictionary)

        // Add new
        var addQuery = query
        addQuery[kSecValueData as String] = data
        SecItemAdd(addQuery as CFDictionary, nil)
    }

    func read(account: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        guard status == errSecSuccess,
              let data = result as? Data,
              let password = String(data: data, encoding: .utf8) else {
            return nil
        }
        return password
    }

    func delete(account: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
        SecItemDelete(query as CFDictionary)
    }
}

#endif // os(iOS)
