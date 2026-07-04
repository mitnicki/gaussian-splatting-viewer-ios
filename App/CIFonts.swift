// CIFonts.swift
// Corporate Identity typography tokens for kroeker.cloud.
// Source: CI Design Guidelines v1.0, Section 3.
// Fonts: Inter (UI/body), JetBrains Mono (code/monospace).
// Inter is loaded as a variable font; JetBrains Mono uses static instances.

import SwiftUI

extension Font {
    // MARK: - Inter (UI / Body Text)

    /// Inter, 17pt, weight .regular — body text (CI: Body 16px → iOS default 17pt)
    static let ciBody = Font.custom("InterVariable", size: 17)

    /// Inter, 15pt, weight .regular — caption / small text
    static let ciCaption = Font.custom("InterVariable", size: 15)

    /// Inter, 20pt, weight .medium — H4
    static let ciH4 = Font.custom("InterVariable", size: 20).weight(.medium)

    /// Inter, 24pt, weight .semibold — H3
    static let ciH3 = Font.custom("InterVariable", size: 24).weight(.semibold)

    /// Inter, 34pt, weight .bold — H2
    static let ciH2 = Font.custom("InterVariable", size: 34).weight(.bold)

    /// Inter, 48pt, weight .bold — H1 Hero
    static let ciH1 = Font.custom("InterVariable", size: 48).weight(.bold)

    // MARK: - JetBrains Mono (Code / Monospace)

    /// JetBrains Mono, 14pt — code blocks, file names, technical text
    static let ciMono = Font.custom("JetBrainsMono-Regular", size: 14)

    /// JetBrains Mono, 14pt, medium — emphasized code
    static let ciMonoMedium = Font.custom("JetBrainsMono-Medium", size: 14)

    /// JetBrains Mono, 14pt, semibold — code headings
    static let ciMonoSemibold = Font.custom("JetBrainsMono-SemiBold", size: 14)

    /// JetBrains Mono, 14pt, bold — strong code emphasis
    static let ciMonoBold = Font.custom("JetBrainsMono-Bold", size: 14)
}

// MARK: - Convenience for dynamic type scaling
// InterVariable supports Dynamic Type via .relative style.
// Use ciBody.relative() for Dynamic-Type-aware body text in lists/forms.

extension Font {
    /// Body text that scales with Dynamic Type.
    static func ciBody(scaled: Bool = false) -> Font {
        scaled ? .custom("InterVariable", size: 17, relativeTo: .body) : .ciBody
    }
}
