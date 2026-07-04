// WebDAVBrowseView.swift
// SwiftUI view for browsing Nextcloud splat files via WebDAV.
// Shows folder navigation, file list, download progress, and launches the renderer.
// M2: Nextcloud integration.

#if os(iOS)

import SwiftUI
import UniformTypeIdentifiers

struct WebDAVBrowseView: View {
    let credentials: WebDAVCredentials

    @State private var client: WebDAVClient?
    @State private var entries: [WebDAVEntry] = []
    @State private var currentPath: String = ""
    @State private var navigationPath: [String] = []
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var downloadProgress: DownloadProgress?

    @State private var selectedSplat: SplatSource?

    var body: some View {
        NavigationStack(path: $navigationPath) {
            contentView
                .navigationTitle(navigationTitle)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    if !navigationPath.isEmpty {
                        ToolbarItem(placement: .navigationBarLeading) {
                            Button {
                                navigationPath.removeLast()
                                currentPath = navigationPath.joined(separator: "/")
                                Task { await loadDirectory() }
                            } label: {
                                Image(systemName: "chevron.left")
                            }
                        }
                    }
                }
                .refreshable {
                    await loadDirectory()
                }
        }
        .sheet(item: $selectedSplat) { source in
            NavigationStack {
                SplatRendererView(url: source.url)
                    .navigationTitle(source.url.lastPathComponent)
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar {
                        ToolbarItem(placement: .navigationBarTrailing) {
                            Button("Done") {
                                selectedSplat = nil
                                downloadProgress = nil
                            }
                        }
                    }
            }
        }
    }

    private var navigationTitle: String {
        if navigationPath.isEmpty {
            return "Nextcloud"
        }
        return navigationPath.last ?? "Files"
    }

    @ViewBuilder
    private var contentView: some View {
        VStack(spacing: 0) {
            if let error = errorMessage {
                errorView(error)
            } else if isLoading && entries.isEmpty {
                ProgressView("Loading...")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if entries.isEmpty {
                emptyView
            } else {
                fileList
            }
        }
        .task {
            if client == nil {
                client = WebDAVClient(credentials: credentials)
            }
            await loadDirectory()
        }
    }

    // MARK: - File list

    @ViewBuilder
    private var fileList: some View {
        List {
            // Directories first
            let dirs = entries.filter { $0.isDirectory }
            let files = entries.filter { !$0.isDirectory }

            if !dirs.isEmpty {
                Section("Folders") {
                    ForEach(dirs) { entry in
                        Button {
                            navigationPath.append(entry.name)
                            currentPath = navigationPath.joined(separator: "/")
                            Task { await loadDirectory() }
                        } label: {
                            Label(entry.name, systemImage: "folder")
                                .foregroundStyle(.primary)
                        }
                    }
                }
            }

            if !files.isEmpty {
                Section("Splat Files") {
                    ForEach(files) { entry in
                        splatFileRow(entry)
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
    }

    @ViewBuilder
    private func splatFileRow(_ entry: WebDAVEntry) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Image(systemName: fileIcon(for: entry))
                    .foregroundStyle(entry.isSplatFile ? Color.accentColor : Color.secondary)
                VStack(alignment: .leading, spacing: 2) {
                    Text(entry.name)
                        .font(.body)
                    HStack(spacing: 8) {
                        if entry.size > 0 {
                            Text(formatBytes(entry.size))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        if let date = entry.lastModified {
                            Text(date, style: .date)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                Spacer()

                if let progress = downloadProgress, progress.path == entry.path {
                    if progress.completed {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundStyle(.ciStatusGreen)
                    } else {
                        ProgressView(value: progress.fraction)
                            .frame(width: 60)
                    }
                } else {
                    Image(systemName: "arrow.down.circle")
                        .foregroundStyle(.ciAccent)
                }
            }
        }
        .contentShape(Rectangle())
        .onTapGesture {
            Task { await downloadAndRender(entry) }
        }
    }

    // MARK: - States

    @ViewBuilder
    private var emptyView: some View {
        ContentUnavailableView {
            Label("No Files", systemImage: "tray")
        } description: {
            Text("No splat files found in this folder.\nUpload .ply / .splat / .spz files to your Nextcloud.")
        }
    }

    @ViewBuilder
    private func errorView(_ message: String) -> some View {
        ContentUnavailableView {
            Label("Error", systemImage: "exclamationmark.triangle")
        } description: {
            Text(message)
        } actions: {
            Button("Retry") {
                errorMessage = nil
                Task { await loadDirectory() }
            }
            .buttonStyle(.borderedProminent)
        }
    }

    // MARK: - Actions

    private func loadDirectory() async {
        guard let client else { return }
        isLoading = true
        errorMessage = nil

        do {
            let result = try await client.listDirectory(relativePath: currentPath)
            entries = result
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    private func downloadAndRender(_ entry: WebDAVEntry) async {
        guard entry.isSplatFile else { return }
        guard let client else { return }

        // Check cache first
        let cache = SplatCacheManager()
        if let cachedURL = await cache.cachedFile(forRelativePath: entry.path) {
            selectedSplat = SplatSource(url: cachedURL)
            return
        }

        // Download
        downloadProgress = DownloadProgress(path: entry.path, fraction: 0, completed: false)

        // Throttle progress updates to avoid excessive SwiftUI redraws.
        // URLSessionDownloadDelegate can fire didWriteData hundreds of times
        // per second for large files. Without throttling, each callback spawns
        // a MainActor Task that triggers a view body re-evaluation.
        let lastUpdate = LastUpdateBox()

        do {
            // Download to temp file
            let tempURL = FileManager.default.temporaryDirectory
                .appendingPathComponent(UUID().uuidString + "." + entry.fileExtension)

            try await client.downloadFile(relativePath: entry.path,
                                           destinationURL: tempURL) { fraction in
                let now = ContinuousClock.now
                // Update at most every 100ms, or when complete
                if fraction >= 1.0 || now - lastUpdate.value >= .milliseconds(100) {
                    lastUpdate.value = now
                    Task { @MainActor in
                        downloadProgress = DownloadProgress(path: entry.path,
                                                             fraction: fraction,
                                                             completed: false)
                    }
                }
            }

            // Cache it
            let cachedURL = try await cache.cacheFile(from: tempURL, relativePath: entry.path)

            // Clean up temp
            try? FileManager.default.removeItem(at: tempURL)

            downloadProgress = DownloadProgress(path: entry.path, fraction: 1.0, completed: true)

            // Launch renderer
            selectedSplat = SplatSource(url: cachedURL)

        } catch {
            errorMessage = error.localizedDescription
            downloadProgress = nil
        }
    }

    // MARK: - Helpers

    private func fileIcon(for entry: WebDAVEntry) -> String {
        if entry.isSplatFile {
            return "cube.transparent"
        }
        switch entry.fileExtension {
        case "ply":  return "cube"
        case "splat": return "cube"
        case "spz":  return "cube.transparent"
        default:     return "doc"
        }
    }

    private func formatBytes(_ bytes: Int64) -> String {
        let formatter = ByteCountFormatter()
        formatter.allowedUnits = [.useMB, .useKB]
        formatter.countStyle = .file
        return formatter.string(fromByteCount: bytes)
    }
}

// MARK: - Download progress

struct DownloadProgress: Equatable {
    let path: String
    let fraction: Double
    let completed: Bool
}

/// Box wrapper to allow mutation of a captured variable in concurrent code.
private final class LastUpdateBox: @unchecked Sendable {
    var value: ContinuousClock.Instant = .now
}

#endif // os(iOS)
