import CoreText
import Foundation

enum ProductTypography {
    static func registerBundledFonts() {
        guard let url = Bundle.main.url(forResource: "Outfit-Variable", withExtension: "ttf") else { return }
        CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
    }
}
