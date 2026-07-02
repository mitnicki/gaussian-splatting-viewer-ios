// SplatCacheManager.swift
// Manages on-device cache for downloaded splat files.
// Files are cached in the app's Caches directory and evicted by size.
// M2: Nextcloud download + cache layer.

import Foundation
import os

actor SplatCacheManager {
    private static let log = Logger(subsystem: Bundle.main.bundleIdentifier ?? "GaussianSplattingViewer",
                                     category: "SplatCacheManager")

    private let cacheURL: URL
    private let maxCacheSize: Int64 = 2 * 1024 * 1024 * 1024  // 2 GB

    init() {
        let cachesDir = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first!
        self.cacheURL = cachesDir.appendingPathComponent("SplatCache", isDirectory: true)

        if !FileManager.default.fileExists(atPath: cacheURL.path) {
            try? FileManager.default.createDirectory(at: cacheURL, withIntermediateDirectories: true)
        }
    }

    // MARK: - Public API

    /// Returns the cached file URL if present, nil otherwise.
    func cachedFile(forRelativePath path: String) -> URL? {
        let url = cacheURL(forRelativePath: path)
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }

        // Touch the file to update access time (LRU)
        try? FileManager.default.setAttributes([.modificationDate: Date()], ofItemAtPath: url.path)
        return url
    }

    /// Saves downloaded data to cache and returns the local URL.
    func cacheFile(data: Data, relativePath: String) throws -> URL {
        let url = cacheURL(forRelativePath: relativePath)
        let dir = url.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try data.write(to: url)
        try evictIfNeeded()
        return url
    }

    /// Saves a file from a source URL (move/copy) and returns the cache URL.
    func cacheFile(from sourceURL: URL, relativePath: String) throws -> URL {
        let url = cacheURL(forRelativePath: relativePath)
        let dir = url.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)

        if FileManager.default.fileExists(atPath: url.path) {
            try FileManager.default.removeItem(at: url)
        }

        // Try move first (fast), fall back to copy
        do {
            try FileManager.default.moveItem(at: sourceURL, to: url)
        } catch {
            try FileManager.default.copyItem(at: sourceURL, to: url)
        }

        try evictIfNeeded()
        return url
    }

    /// Clears all cached files.
    func clearCache() throws {
        let contents = try FileManager.default.contentsOfDirectory(at: cacheURL,
                                                                     includingPropertiesForKeys: nil)
        for url in contents {
            try? FileManager.default.removeItem(at: url)
        }
    }

    /// Total cache size in bytes.
    func cacheSize() -> Int64 {
        let resourceKeys: Set<URLResourceKey> = [.totalFileAllocatedSizeKey, .isRegularFileKey]
        guard let enumerator = FileManager.default.enumerator(at: cacheURL,
                                                                includingPropertiesForKeys: Array(resourceKeys)) else {
            return 0
        }
        var total: Int64 = 0
        for case let url as URL in enumerator {
            let resources = try? url.resourceValues(forKeys: resourceKeys)
            if resources?.isRegularFile == true {
                total += resources?.totalFileAllocatedSize ?? 0
            }
        }
        return total
    }

    // MARK: - Memory management

    /// Clear cache on memory pressure (called from UIApplication.didReceiveMemoryWarningNotification)
    func handleMemoryWarning() {
        try? clearCache()
        Self.log.notice("Memory warning: cleared splat cache")
    }

    // MARK: - Private

    private func cacheURL(forRelativePath path: String) -> URL {
        // Sanitize the path — replace path separators to create flat filename
        let safeName = path.replacingOccurrences(of: "/", with: "_")
        return cacheURL.appendingPathComponent(safeName)
    }

    private func evictIfNeeded() throws {
        let currentSize = cacheSize()
        guard currentSize > maxCacheSize else { return }

        // LRU eviction: sort by modification date ascending (oldest first)
        let resourceKeys: Set<URLResourceKey> = [.contentModificationDateKey, .fileSizeKey, .isRegularFileKey]
        guard let enumerator = FileManager.default.enumerator(at: cacheURL,
                                                                includingPropertiesForKeys: Array(resourceKeys)) else {
            return
        }

        var files: [(url: URL, date: Date, size: Int64)] = []
        for case let url as URL in enumerator {
            let resources = try? url.resourceValues(forKeys: resourceKeys)
            if resources?.isRegularFile == true {
                let date = resources?.contentModificationDate ?? Date.distantPast
                let size = Int64(resources?.fileSize ?? 0)
                files.append((url, date, size))
            }
        }

        files.sort { $0.date < $1.date }

        var remaining = currentSize
        for file in files {
            if remaining <= maxCacheSize { break }
            try? FileManager.default.removeItem(at: file.url)
            remaining -= file.size
            Self.log.info("Evicted cached file: \(file.url.lastPathComponent) (\(file.size) bytes)")
        }
    }
}
