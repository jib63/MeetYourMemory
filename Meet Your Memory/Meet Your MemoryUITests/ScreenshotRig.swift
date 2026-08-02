import ImageIO
import UIKit
import XCTest

enum ScreenshotRig {
    struct Language {
        let code: String
        let region: String

        static let english = Language(code: "en", region: "en_US")
        static let french = Language(code: "fr", region: "fr_FR")
        static let spanish = Language(code: "es", region: "es_ES")
        static let italian = Language(code: "it", region: "it_IT")
        static let portuguese = Language(code: "pt", region: "pt_PT")
        static let japanese = Language(code: "ja", region: "ja_JP")
        static let chineseHans = Language(code: "zh-Hans", region: "zh_Hans_CN")
        static let hindi = Language(code: "hi", region: "hi_IN")
    }

    enum Stage: CaseIterable {
        case home, visual, spatial, association, result, history

        var filename: String {
            switch self {
            case .home: return "01-home"
            case .visual: return "02-visual-memory"
            case .spatial: return "03-spatial-memory"
            case .association: return "04-association-memory"
            case .result: return "05-memory-profile"
            case .history: return "06-history"
            }
        }

        var launchScreen: String {
            switch self {
            case .home: return "home"
            case .visual: return "visual"
            case .spatial: return "spatial"
            case .association: return "association"
            case .result: return "result"
            case .history: return "history"
            }
        }

        var marker: String {
            switch self {
            case .home: return "screen-home"
            case .visual: return "screen-challenge-visual"
            case .spatial: return "screen-challenge-spatial"
            case .association: return "screen-challenge-association"
            case .result: return "screen-results"
            case .history: return "screen-history"
            }
        }
    }

    @MainActor
    static func runAllFrames(in language: Language, on testCase: XCTestCase) {
        for stage in Stage.allCases {
            let app = XCUIApplication()
            app.launchArguments = [
                "-AppleLanguages", "(\(language.code))",
                "-AppleLocale", language.region,
                "--marketing-screen", stage.launchScreen,
                "UI_TESTING",
            ]
            app.launch()

            let marker = app.descendants(matching: .any)
                .matching(identifier: stage.marker)
                .firstMatch
            guard marker.waitForExistence(timeout: 8) else {
                XCTFail("Missing \(stage.marker); \(stage.filename) was not replaced")
                app.terminate()
                continue
            }
            Thread.sleep(forTimeInterval: stage == .history ? 1.5 : 1.0)
            capture(stage.filename, language: language, on: testCase)
            app.terminate()
        }
    }

    @MainActor
    private static func capture(_ frame: String, language: Language, on testCase: XCTestCase) {
        let screenshot = XCUIScreen.main.screenshot()
        guard let jpeg = screenshot.image.jpegData(compressionQuality: 0.9) else {
            XCTFail("Could not encode \(frame) as JPEG")
            return
        }
        guard let displayClass = displayClass(for: jpeg) else {
            XCTFail("Unsupported screenshot dimensions for \(frame). Use iPhone 17 Pro Max or iPad Pro 13-inch.")
            return
        }
        let directory = URL(filePath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appending(path: "Screenshots")
            .appending(path: displayClass)
            .appending(path: language.code)
        let destination = directory.appending(path: "\(frame).jpg")
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            try jpeg.write(to: destination, options: .atomic)
        } catch {
            XCTFail("Could not write \(destination.path): \(error)")
        }

        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = "\(language.code)/\(frame)"
        attachment.lifetime = .keepAlways
        testCase.add(attachment)
    }

    static func displayClass(for data: Data) -> String? {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = properties[kCGImagePropertyPixelWidth] as? Int,
              let height = properties[kCGImagePropertyPixelHeight] as? Int else { return nil }
        switch (min(width, height), max(width, height)) {
        case (1320, 2868), (1290, 2796): return "6.9-inch"
        case (2064, 2752), (2048, 2732): return "ipad-13-inch"
        default: return nil
        }
    }
}
