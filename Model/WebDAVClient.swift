// WebDAVClient.swift
// Minimal Nextcloud WebDAV client for listing and downloading splat files.
// Uses URLSession + PROPFIND/GET — no third-party dependencies.
// M2: Nextcloud integration.

import Foundation

// MARK: - Errors

enum WebDAVError: LocalizedError {
    case invalidURL
    case unauthorized
    case httpError(Int)
    case parseError
    case downloadFailed(String)

    var errorDescription: String? {
        switch self {
        case .invalidURL:        return "Invalid WebDAV URL"
        case .unauthorized:      return "Invalid credentials — check username and app password"
        case .httpError(let c):  return "HTTP \(c)"
        case .parseError:        return "Could not parse WebDAV response"
        case .downloadFailed(let m): return "Download failed: \(m)"
        }
    }
}

// MARK: - Models

struct WebDAVEntry: Identifiable, Hashable {
    let id: String          // full path
    let name: String
    let path: String        // relative path from root
    let isDirectory: Bool
    let size: Int64
    let contentType: String
    let lastModified: Date?

    var fileExtension: String {
        (name as NSString).pathExtension.lowercased()
    }

    var isSplatFile: Bool {
        ["ply", "splat", "spz"].contains(fileExtension)
    }
}

struct WebDAVCredentials {
    let serverURL: URL       // e.g. https://files.dkroeker.de
    let username: String
    let appPassword: String  // Nextcloud app password (not the account password)

    var davBaseURL: URL {
        serverURL.appendingPathComponent("remote.php/dav/files")
    }

    func url(forPath path: String) -> URL {
        // path is relative (e.g. "GaussianSplats/rc390.spz")
        // Encode each path component separately to preserve slashes
        let components = path.split(separator: "/").map { String($0) }
        var url = davBaseURL.appendingPathComponent(username)
        for comp in components {
            url.appendPathComponent(comp)
        }
        return url
    }
}

// MARK: - WebDAV Client

actor WebDAVClient {
    private let credentials: WebDAVCredentials
    private let session: URLSession

    init(credentials: WebDAVCredentials) {
        self.credentials = credentials
        self.session = URLSession(configuration: .default)
    }

    // MARK: Auth

    private var authHeader: String {
        let token = "\(credentials.username):\(credentials.appPassword)"
        let data = token.data(using: .utf8) ?? Data()
        return "Basic " + data.base64EncodedString()
    }

    private func authorizedRequest(url: URL, method: String, headers: [String: String] = [:]) -> URLRequest {
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue(authHeader, forHTTPHeaderField: "Authorization")
        for (k, v) in headers {
            req.setValue(v, forHTTPHeaderField: k)
        }
        return req
    }

    // MARK: PROPFIND — list directory

    func listDirectory(relativePath: String = "") async throws -> [WebDAVEntry] {
        let url = credentials.url(forPath: relativePath)

        let body = """
        <?xml version="1.0" encoding="utf-8"?>
        <d:propfind xmlns:d="DAV:">
          <d:prop>
            <d:resourcetype/>
            <d:getcontentlength/>
            <d:getcontenttype/>
            <d:getlastmodified/>
            <d:displayname/>
          </d:prop>
        </d:propfind>
        """

        let req = authorizedRequest(url: url, method: "PROPFIND", headers: [
            "Depth": "1",
            "Content-Type": "application/xml; charset=utf-8"
        ])
        req.httpBody = body.data(using: .utf8)

        let (data, response) = try await session.data(for: req)

        guard let http = response as? HTTPURLResponse else {
            throw WebDAVError.parseError
        }

        switch http.statusCode {
        case 207:  // Multi-Status — success
            return try parsePropFind(data: data, basePath: relativePath)
        case 401:
            throw WebDAVError.unauthorized
        default:
            throw WebDAVError.httpError(http.statusCode)
        }
    }

    // MARK: GET — download file

    func downloadFile(relativePath: String,
                      destinationURL: URL,
                      progress: @Sendable (Double) -> Void = { _ in }) async throws {

        let url = credentials.url(forPath: relativePath)
        let req = authorizedRequest(url: url, method: "GET")

        // Use a delegate-based download session so we get real progress callbacks
        // (bytesWritten / totalBytesExpected). The default session.download(for:)
        // streams to disk (no OOM) but provides NO intermediate progress — a
        // 113 MB .spz would show 0% for the entire download then jump to 100%.
        let progressDelegate = DownloadProgressDelegate(progress: progress)
        let downloadSession = URLSession(
            configuration: .default,
            delegate: progressDelegate,
            delegateQueue: nil
        )
        defer { downloadSession.finishTasksAndInvalidate() }

        let (tempURL, response) = try await downloadSession.download(for: req)

        guard let http = response as? HTTPURLResponse else {
            throw WebDAVError.parseError
        }

        switch http.statusCode {
        case 200:
            break
        case 401:
            throw WebDAVError.unauthorized
        case 404:
            throw WebDAVError.downloadFailed("File not found")
        default:
            throw WebDAVError.httpError(http.statusCode)
        }

        // Move the downloaded temp file to the destination
        if FileManager.default.fileExists(atPath: destinationURL.path) {
            try FileManager.default.removeItem(at: destinationURL)
        }
        try FileManager.default.moveItem(at: tempURL, to: destinationURL)
        progress(1.0)
    }

    // MARK: PROPFIND response parser

    private func parsePropFind(data: Data, basePath: String) throws -> [WebDAVEntry] {
        let parser = WebDAVPropFindParser()
        var entries = try parser.parse(data: data)

        // The first entry is the directory itself — filter it out
        if !entries.isEmpty {
            entries.removeFirst()
        }

        return entries
    }
}

// MARK: - XML Parser (non-actor, reusable)

private final class WebDAVPropFindParser: NSObject, XMLParserDelegate {
    private var entries: [WebDAVEntry] = []
    private var currentEntry: ParsedEntry?
    private var currentValue: String = ""
    private var currentElement: String = ""
    private let dateFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()
    private let rfc1123Formatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "EEE, dd MMM yyyy HH:mm:ss zzz"
        return f
    }()

    // The DAV path prefix that precedes the user-specific portion:
    // /remote.php/dav/files/<username>/...
    private let davFilesPrefix = "/remote.php/dav/files/"

    struct ParsedEntry {
        var href: String = ""
        var displayName: String = ""
        var isDirectory: Bool = false
        var contentLength: Int64 = 0
        var contentType: String = ""
        var lastModified: String = ""
    }

    func parse(data: Data) throws -> [WebDAVEntry] {
        let parser = XMLParser(data: data)
        parser.delegate = self
        parser.shouldProcessNamespaces = true
        guard parser.parse() else {
            throw WebDAVError.parseError
        }
        return entries
    }

    // XMLParserDelegate

    func parser(_ parser: XMLParser,
                didStartElement elementName: String,
                namespaceURI: String?,
                qualifiedName qName: String?,
                attributes attributeDict: [String : String] = [:]) {
        currentElement = elementName.lowercased()
        currentValue = ""

        if currentElement == "response" {
            currentEntry = ParsedEntry()
        }
    }

    func parser(_ parser: XMLParser, foundCharacters string: String) {
        currentValue += string
    }

    func parser(_ parser: XMLParser,
                didEndElement elementName: String,
                namespaceURI: String?,
                qualifiedName qName: String?) {
        let name = elementName.lowercased()
        let trimmed = currentValue.trimmingCharacters(in: .whitespacesAndNewlines)

        guard var entry = currentEntry else { return }

        switch name {
        case "href":
            entry.href = trimmed
        case "displayname":
            if entry.displayName.isEmpty {
                entry.displayName = trimmed
            }
        case "collection":
            entry.isDirectory = true
        case "getcontentlength":
            entry.contentLength = Int64(trimmed) ?? 0
        case "getcontenttype":
            entry.contentType = trimmed
        case "getlastmodified":
            entry.lastModified = trimmed
        case "response":
            let displayName = entry.displayName.isEmpty
                ? (entry.href as NSString).lastPathComponent
                : entry.displayName

            // Extract relative path from href.
            // href is like: /remote.php/dav/files/username/GaussianSplats/file.spz
            // We want: GaussianSplats/file.spz
            let decodedHref = entry.href.removingPercentEncoding ?? entry.href
            let relPath: String
            if let range = decodedHref.range(of: davFilesPrefix) {
                let afterPrefix = decodedHref[range.upperBound...]
                // Skip the username segment
                if let nextSlash = afterPrefix.firstIndex(of: "/") {
                    relPath = String(afterPrefix[afterPrefix.index(after: nextSlash)...])
                } else {
                    relPath = ""  // root directory
                }
            } else {
                // Fallback: use last path component
                relPath = (decodedHref as NSString).lastPathComponent
            }

            // Remove trailing slash for directories
            let cleanPath = relPath.hasSuffix("/") ? String(relPath.dropLast()) : relPath

            let lastMod = dateFormatter.date(from: entry.lastModified)
                ?? rfc1123Formatter.date(from: entry.lastModified)

            let webdavEntry = WebDAVEntry(
                id: entry.href,
                name: displayName,
                path: cleanPath,
                isDirectory: entry.isDirectory,
                size: entry.contentLength,
                contentType: entry.contentType,
                lastModified: lastMod
            )
            entries.append(webdavEntry)
            currentEntry = nil
        default:
            break
        }

        currentEntry = entry
    }
}

// MARK: - Download Progress Delegate

/// URLSessionDownloadDelegate that reports real download progress via a callback.
/// Used by WebDAVClient.downloadFile to show incremental progress for large files.
private final class DownloadProgressDelegate: NSObject, URLSessionDownloadDelegate {
    let progress: @Sendable (Double) -> Void

    init(progress: @escaping @Sendable (Double) -> Void) {
        self.progress = progress
    }

    func urlSession(_ session: URLSession,
                    downloadTask: URLSessionDownloadTask,
                    didWriteData bytesWritten: Int64,
                    totalBytesWritten: Int64,
                    totalBytesExpectedToWrite: Int64) {
        guard totalBytesExpectedToWrite > 0 else { return }
        let fraction = Double(totalBytesWritten) / Double(totalBytesExpectedToWrite)
        progress(min(max(fraction, 0.0), 1.0))
    }

    func urlSession(_ session: URLSession,
                    downloadTask: URLSessionDownloadTask,
                    didFinishDownloadingTo location: URL) {
        // The async download(for:) API handles the temp file — nothing to do here.
    }
}
