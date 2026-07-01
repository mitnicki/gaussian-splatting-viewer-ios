// ModelIdentifier.swift
// Minimal routing value for splat sources. Adapted from MetalSplatter SampleApp (MIT),
// reduced to the URL-loading case.

import Foundation

struct SplatSource: Hashable {
    let url: URL
}
