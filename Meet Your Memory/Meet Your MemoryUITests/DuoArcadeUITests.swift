// Copyright (c) 2026 Jean-Baptiste Meyer
// SPDX-License-Identifier: MIT

import XCTest

@MainActor
final class DuoArcadeUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .portrait
    }

    override func tearDownWithError() throws { XCUIDevice.shared.orientation = .portrait }

    private func launch(_ game: String, postureControls: Bool = false) -> XCUIApplication {
        let app = XCUIApplication()
        let expanded = ["panoramaPairs", "orbitMap", "soundBoard", "cometField"].contains(game)
        app.launchArguments = ["--duo-ui-testing", "--duo-test-game", game, "--adaptive-home-mode", expanded ? "expanded" : "folded", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        if postureControls { app.launchArguments.append("--duo-test-posture-controls") }
        app.launch()
        XCTAssertTrue(app.buttons["duo-continue"].waitForExistence(timeout: 15))
        XCTAssertTrue(waitUntilEnabled(app.buttons["duo-continue"]))
        return app
    }

    private func waitUntilEnabled(_ element: XCUIElement) -> Bool {
        let expectation = XCTNSPredicateExpectation(predicate: NSPredicate(format: "isEnabled == true AND exists == true"), object: element)
        return XCTWaiter.wait(for: [expectation], timeout: 5) == .completed
    }

    func testSpatialRotationPausesAndRestoresHiddenRecall() {
        let app = launch("threads", postureControls: true)
        app.buttons["duo-continue"].tap()
        app.buttons["duo-node-0"].tap()
        app.buttons["duo-test-pose-tabletop"].tap()
        XCTAssertTrue(app.scrollViews["duo-recovery"].waitForExistence(timeout: 3))
        XCTAssertEqual(app.staticTexts["duo-recovery-progress"].label, "1 of 6 answers kept")
        XCTAssertFalse(app.otherElements["duo-solution"].exists)
        XCTAssertFalse(app.buttons["duo-node-3"].exists)
        app.buttons["duo-test-pose-book"].tap()
        XCTAssertTrue(app.buttons["duo-resume"].waitForExistence(timeout: 3))
        XCTAssertTrue(waitUntilEnabled(app.buttons["duo-resume"]))
        let snapshot = XCTAttachment(screenshot: app.screenshot())
        snapshot.name = "Saved spatial round ready to resume"; snapshot.lifetime = .keepAlways; add(snapshot)
        app.buttons["duo-resume"].tap()
        XCTAssertEqual(app.staticTexts["duo-progress"].label, "1/6")
        XCTAssertFalse(app.otherElements["duo-solution"].exists)
        for node in [3, 2, 5, 4, 1] { app.buttons["duo-node-\(node)"].tap() }
        check(app, expected: 6)
    }

    func testClosedPhoneOffersFreshChallengeInTheSameScanSlot() {
        let app = launch("orbitMap", postureControls: true)
        app.buttons["duo-continue"].tap()
        app.buttons["duo-node-0"].tap()
        let position = app.staticTexts["scan-position"].label
        app.buttons["duo-test-pose-closed"].tap()
        XCTAssertTrue(app.buttons["duo-replace"].waitForExistence(timeout: 3))
        XCTAssertEqual(app.staticTexts["duo-recovery-progress"].label, "1 of 6 answers kept")
        let snapshot = XCTAttachment(screenshot: app.screenshot())
        snapshot.name = "Closed phone recovery"; snapshot.lifetime = .keepAlways; add(snapshot)
        app.buttons["duo-replace"].tap()
        XCTAssertTrue(app.buttons["regular-ready"].waitForExistence(timeout: 3))
        XCTAssertEqual(app.staticTexts["scan-position"].label, position)
        XCTAssertTrue(app.descendants(matching: .any)["screen-challenge-spatial"].exists)
        app.buttons["regular-ready"].tap()
        app.buttons["regular-option-0"].tap()
        XCTAssertTrue(app.staticTexts["scan-position"].waitForExistence(timeout: 3))
        let next = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "2 / 12"), object: app.staticTexts["scan-position"])
        XCTAssertEqual(XCTWaiter.wait(for: [next], timeout: 5), .completed)
    }

    func testMatchingReflowsAndKeepsDeliveredObjects() {
        let app = launch("courier", postureControls: true)
        app.buttons["duo-continue"].tap()
        app.buttons["duo-object-0"].tap(); app.buttons["duo-pocket-1"].tap()
        XCUIDevice.shared.orientation = .landscapeLeft
        XCTAssertTrue(waitUntilEnabled(app.buttons["duo-object-1"]))
        XCTAssertEqual(app.staticTexts["duo-progress"].label, "1/3")
        app.buttons["duo-test-pose-tabletop"].tap()
        XCTAssertTrue(waitUntilEnabled(app.buttons["duo-object-1"]))
        XCTAssertFalse(app.scrollViews["duo-recovery"].exists)
        XCTAssertEqual(app.staticTexts["duo-progress"].label, "1/3")
        let viewport = app.windows.firstMatch.frame.insetBy(dx: -1, dy: -1)
        for index in 0..<3 {
            for key in ["duo-object-\(index)", "duo-pocket-\(index)"] {
                XCTAssertTrue(viewport.contains(app.buttons[key].frame), "\(key) must stay inside the rotated window")
                XCTAssertTrue(app.buttons[key].isHittable)
            }
        }
        let snapshot = XCTAttachment(screenshot: app.screenshot())
        snapshot.name = "Matching round reflows after rotation"; snapshot.lifetime = .keepAlways; add(snapshot)
        app.buttons["duo-object-1"].tap(); app.buttons["duo-pocket-0"].tap()
        app.buttons["duo-test-pose-flat"].tap()
        XCTAssertTrue(waitUntilEnabled(app.buttons["duo-object-2"]))
        XCTAssertEqual(app.staticTexts["duo-progress"].label, "2/3")
        app.buttons["duo-object-2"].tap(); app.buttons["duo-pocket-2"].tap()
        check(app, expected: 3)
    }

    private func check(_ app: XCUIApplication, expected: Int) {
        app.buttons["duo-check"].tap()
        XCTAssertTrue(app.staticTexts["duo-score"].waitForExistence(timeout: 3))
        XCTAssertEqual(app.staticTexts["duo-score"].label, "\(expected) of \(expected) correct")
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = "Duo round result"; image.lifetime = .keepAlways; add(image)
        app.buttons["duo-continue"].tap()
        XCTAssertFalse(app.staticTexts["duo-score"].exists)
        XCTAssertTrue(app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "screen-challenge-")).firstMatch.waitForExistence(timeout: 3))
    }

    func testCourierDragAndTap() {
        let app = launch("courier")
        app.buttons["duo-continue"].tap()
        let source = app.buttons["duo-object-0"]
        let target = app.buttons["duo-pocket-1"]
        source.press(forDuration: 0.1, thenDragTo: target)
        XCTAssertEqual(app.staticTexts["duo-progress"].label, "1/3")
        app.buttons["duo-object-1"].tap(); app.buttons["duo-pocket-0"].tap()
        app.buttons["duo-object-2"].tap(); app.buttons["duo-pocket-2"].tap()
        check(app, expected: 3)
    }

    func testThreadsGestureRound() {
        let app = launch("threads")
        app.buttons["duo-continue"].tap()
        app.buttons["duo-node-0"].press(forDuration: 0.1, thenDragTo: app.buttons["duo-node-3"])
        XCTAssertEqual(app.staticTexts["duo-progress"].label, "2/6")
        for node in [2, 5, 4, 1] { app.buttons["duo-node-\(node)"].tap() }
        check(app, expected: 6)
    }

    func testCatapultFlickAndButtons() {
        let app = launch("catapult")
        app.buttons["duo-continue"].tap()
        XCTAssertFalse(app.otherElements["duo-solution"].exists)
        let puck = app.images["duo-launcher"]
        let start = puck.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        start.press(forDuration: 0.05, thenDragTo: start.withOffset(CGVector(dx: 70, dy: -80)))
        XCTAssertEqual(app.staticTexts["duo-progress"].label, "1/3")
        for gate in [0, 1] { app.buttons["duo-gate-\(gate)"].tap(); app.buttons["duo-launch"].tap() }
        check(app, expected: 3)
    }

    func testDrumAccessiblePhraseAndUndo() {
        let app = launch("drums")
        app.buttons["duo-play-phrase"].tap()
        app.buttons["duo-continue"].tap()
        XCTAssertFalse(app.buttons["duo-play-phrase"].exists)
        XCTAssertFalse(app.otherElements["duo-solution"].exists)
        app.buttons["duo-beat-right"].tap(); app.buttons["duo-undo"].tap()
        for beat in ["left", "both", "right", "holdLeft"] { app.buttons["duo-beat-\(beat)"].tap() }
        check(app, expected: 4)
    }

    func testFlatExpandedGame() {
        let app = launch("panoramaPairs")
        XCTAssertTrue(app.descendants(matching: .any)["screen-challenge-adaptive-panoramaPairs"].exists)
        app.buttons["duo-continue"].tap()
        for (object, pocket) in [(0, 1), (1, 0), (2, 2)] {
            app.buttons["duo-object-\(object)"].tap()
            app.buttons["duo-pocket-\(pocket)"].tap()
        }
        check(app, expected: 3)
    }

    func testHomeStillStartsMemoryScan() {
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.scrollViews["screen-home"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["open-duo-arcade"].exists)
        XCTAssertFalse(app.staticTexts["adaptive-game-count"].exists)
        app.buttons["start-memory-scan"].tap()
        XCTAssertTrue(app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "screen-challenge-")).firstMatch.waitForExistence(timeout: 5))
    }

    func testUnfoldDuringRegularChallengeChangesOnlyTheNextStep() {
        let app = XCUIApplication()
        app.launchArguments = ["--duo-test-regular-then-expanded", "--adaptive-home-mode", "expanded", "-AppleLanguages", "(en)"]
        app.launch()
        XCTAssertTrue(app.buttons["regular-ready"].waitForExistence(timeout: 15))
        app.buttons["regular-ready"].tap()
        XCTAssertTrue(app.buttons["regular-option-0"].waitForExistence(timeout: 3))
        app.buttons["regular-option-0"].tap()
        let adaptive = app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "screen-challenge-adaptive-"))
        XCTAssertTrue(adaptive.firstMatch.waitForExistence(timeout: 5))
        XCTAssertEqual(app.state, .runningForeground)
    }

    func testOneHomeSelectsAdaptiveGamesWithoutShowingAMenu() {
        let folded = XCUIApplication()
        folded.launchArguments = ["--adaptive-home-mode", "folded", "-AppleLanguages", "(en)"]
        folded.launch()
        XCTAssertTrue(folded.scrollViews["screen-home"].waitForExistence(timeout: 10))
        XCTAssertFalse(folded.staticTexts["adaptive-game-count"].exists)
        XCTAssertFalse(folded.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "adaptive-game-")).firstMatch.exists)
        folded.buttons["start-memory-scan"].tap()
        XCTAssertTrue(folded.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "screen-challenge-adaptive-")).firstMatch.waitForExistence(timeout: 5))
        let foldedImage = XCTAttachment(screenshot: folded.screenshot())
        foldedImage.name = "Transparent adaptive scan · partially folded"; foldedImage.lifetime = .keepAlways; add(foldedImage)

        folded.terminate()
        let expanded = XCUIApplication()
        expanded.launchArguments = ["--adaptive-home-mode", "expanded", "-AppleLanguages", "(en)"]
        expanded.launch()
        XCTAssertTrue(expanded.scrollViews["screen-home"].waitForExistence(timeout: 10))
        XCTAssertFalse(expanded.staticTexts["adaptive-game-count"].exists)
        expanded.buttons["start-memory-scan"].tap()
        let expandedGames = ["panoramaPairs", "orbitMap", "soundBoard", "cometField"].map { "screen-challenge-adaptive-\($0)" }
        XCTAssertTrue(expandedGames.contains { expanded.descendants(matching: .any)[$0].waitForExistence(timeout: 2) })
    }
}
