// Copyright (c) 2026 Jean-Baptiste Meyer
// SPDX-License-Identifier: MIT

import Foundation
import Testing
@testable import Meet_Your_Memory

struct MeetYourMemoryTests {
    @Test("Every scan is balanced and valid")
    func challengeBankIsBalanced() {
        let challenges = MemoryChallengeBank.makeScan()
        #expect(challenges.count == 12)
        #expect(Set(challenges.map(\.signature)).count == 12)
        for category in MemoryCategory.allCases {
            let categoryChallenges = challenges.filter { $0.category == category }
            #expect(categoryChallenges.count == 2)
            #expect(Set(categoryChallenges.map(\.questionFamily)).count == 2)
        }
        for challenge in challenges {
            #expect(challenge.options.count == 4)
            #expect(challenge.options.indices.contains(challenge.correctOption))
            #expect(challenge.studySeconds >= 6)
        }
    }

    @Test("A replay avoids the immediately previous questions")
    func replayHasFreshQuestions() {
        let first = MemoryChallengeBank.makeScan()
        let second = MemoryChallengeBank.makeScan(avoiding: Set(first.map(\.signature)))
        #expect(Set(first.map(\.signature)).isDisjoint(with: Set(second.map(\.signature))))
    }

    @Test("Procedural generation creates a large variety")
    func challengeVariety() {
        let signatures = Set((0..<30).flatMap { _ in MemoryChallengeBank.makeScan().map(\.signature) })
        #expect(signatures.count > 100)
    }

    @Test("Repeated scans exercise several question styles in every category")
    func questionStyleVariety() {
        let scans = (0..<30).flatMap { _ in MemoryChallengeBank.makeScan() }
        for category in MemoryCategory.allCases {
            let families = Set(scans.filter { $0.category == category }.map(\.questionFamily))
            #expect(families.count >= 3)
        }
    }

    @Test("A visual lead produces the expected score")
    func visualProfile() {
        let correct: [MemoryCategory: Int] = [.visual: 2, .words: 1, .sound: 0, .spatial: 1, .association: 1, .sequence: 0]
        let total = Dictionary(uniqueKeysWithValues: MemoryCategory.allCases.map { ($0, 2) })
        let profile = MemoryProfile.build(correct: correct, total: total)
        #expect(profile.primaryCategory == .visual)
        #expect(profile.overallPercent == 42)
    }

    @MainActor
    @Test("Completed scans persist in local history")
    func historyPersists() {
        let suite = "MeetYourMemoryTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let total = Dictionary(uniqueKeysWithValues: MemoryCategory.allCases.map { ($0, 2) })
        let profile = MemoryProfile.build(correct: [.sound: 2, .visual: 1], total: total)
        let store = MemoryHistoryStore(defaults: defaults, key: "history")
        store.record(profile, date: Date(timeIntervalSince1970: 1_000))
        let reloaded = MemoryHistoryStore(defaults: defaults, key: "history")
        #expect(reloaded.sessions.count == 1)
        #expect(reloaded.sessions[0].primaryCategory == .sound)
        #expect(reloaded.sessions[0].overallPercent == 25)
    }
}
