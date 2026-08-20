// Copyright (c) 2026 Jean-Baptiste Meyer
// SPDX-License-Identifier: MIT

import XCTest

@MainActor
final class ScreenshotTests: XCTestCase {
    override func setUp() {
        super.setUp()
        continueAfterFailure = true
    }

    func test01_English() { ScreenshotRig.runAllFrames(in: .english, on: self) }
    func test02_French() { ScreenshotRig.runAllFrames(in: .french, on: self) }
    func test03_Spanish() { ScreenshotRig.runAllFrames(in: .spanish, on: self) }
    func test04_Italian() { ScreenshotRig.runAllFrames(in: .italian, on: self) }
    func test05_Portuguese() { ScreenshotRig.runAllFrames(in: .portuguese, on: self) }
    func test06_Japanese() { ScreenshotRig.runAllFrames(in: .japanese, on: self) }
    func test07_ChineseHans() { ScreenshotRig.runAllFrames(in: .chineseHans, on: self) }
    func test08_Hindi() { ScreenshotRig.runAllFrames(in: .hindi, on: self) }
}
