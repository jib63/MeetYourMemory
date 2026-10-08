// Copyright (c) 2026 Jean-Baptiste Meyer
// SPDX-License-Identifier: MIT

import UIKit
import XCTest

final class ScreenshotRigContractTests: XCTestCase {
    func testGalleryContainsExactlySixOrderedScreenshots() {
        XCTAssertEqual(ScreenshotRig.Stage.allCases.count, 6)
        XCTAssertEqual(
            ScreenshotRig.Stage.allCases.map(\.filename),
            [
                "01-home", "02-visual-memory", "03-spatial-memory",
                "04-association-memory", "05-memory-profile", "06-history",
            ]
        )
    }

    func testCurrentAppStoreDisplaySizesAreAccepted() throws {
        XCTAssertEqual(ScreenshotRig.displayClass(for: try imageData(width: 1320, height: 2868)), "6.9-inch")
        XCTAssertEqual(ScreenshotRig.displayClass(for: try imageData(width: 2064, height: 2752)), "ipad-13-inch")
        XCTAssertEqual(ScreenshotRig.displayClass(for: try imageData(width: 1179, height: 2556)), "iphone-medium")
        XCTAssertEqual(ScreenshotRig.displayClass(for: try imageData(width: 1398, height: 2034)), "iphone-duo-outer")
        XCTAssertEqual(ScreenshotRig.displayClass(for: try imageData(width: 2853, height: 2007)), "iphone-duo-inner")
        XCTAssertNil(ScreenshotRig.displayClass(for: try imageData(width: 750, height: 1334)))
    }

    private func imageData(width: Int, height: Int) throws -> Data {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let image = UIGraphicsImageRenderer(size: CGSize(width: width, height: height), format: format).image { context in
            UIColor.black.setFill()
            context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        }
        return try XCTUnwrap(image.jpegData(compressionQuality: 0.1))
    }
}
