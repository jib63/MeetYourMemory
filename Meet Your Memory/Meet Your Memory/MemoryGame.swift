// Copyright (c) 2026 Jean-Baptiste Meyer
// SPDX-License-Identifier: MIT

import Foundation
import Observation

enum GameScreen: Equatable { case home, playing, results, focusResults }
enum ChallengePhase: Equatable { case study, answer, feedback }

enum MemoryCategory: String, CaseIterable, Identifiable, Codable {
    case visual, words, sound, spatial, association, sequence
    var id: String { rawValue }
    var title: String { L10n.text("category.\(rawValue)") }
    var studyVerb: String { L10n.text("verb.\(rawValue)") }
    var profileTitle: String { L10n.text("profile.\(rawValue).title") }
    var profileBlurb: String { L10n.text("profile.\(rawValue).blurb") }
    var icon: String {
        switch self {
        case .visual: "eye.fill"
        case .words: "text.quote"
        case .sound: "ear.fill"
        case .spatial: "map.fill"
        case .association: "link"
        case .sequence: "point.3.connected.trianglepath.dotted"
        }
    }
}

enum MemorySwatch: String, CaseIterable {
    case violet, coral, aqua, yellow, blue
    var title: String { L10n.text("colour.\(rawValue)") }
}

enum MemoryTone: String, CaseIterable {
    case bass, low, mid, high
    var title: String { L10n.text("tone.\(rawValue)") }
    var frequency: Double {
        switch self { case .bass: 220; case .low: 293.66; case .mid: 440; case .high: 659.25 }
    }
}

struct MemoryPair: Identifiable, Equatable {
    let symbol: String
    let word: String
    var id: String { "\(symbol)-\(word)" }
}

enum MemoryStimulus: Equatable {
    case symbols([String])
    case words(String)
    case colors([MemorySwatch])
    case tones([MemoryTone])
    case grid([Int])
    case pairs([MemoryPair])
    case sequence([String])
}

struct MemoryChallenge: Identifiable, Equatable {
    let id: String
    let signature: String
    let questionFamily: String
    let category: MemoryCategory
    let eyebrow: String
    let title: String
    let instruction: String
    let stimulus: MemoryStimulus
    let question: String
    let options: [String]
    let correctOption: Int
    let studySeconds: Int
}

enum MemoryChallengeBank {
    static let questionsPerCategory = 2
    static let focusedChallengeCount = 3

    static func makeScan(avoiding previous: Set<String> = []) -> [MemoryChallenge] {
        var selected: [MemoryChallenge] = []
        var used = Set<String>()
        var usedFamilies: [MemoryCategory: Set<String>] = [:]
        for category in MemoryCategory.allCases {
            for variant in 0..<questionsPerCategory {
                var candidate = make(category: category, variant: variant)
                var attempts = 0
                while (previous.contains(candidate.signature)
                    || used.contains(candidate.signature)
                    || usedFamilies[category, default: []].contains(candidate.questionFamily)) && attempts < 60 {
                    candidate = make(category: category, variant: variant)
                    attempts += 1
                }
                selected.append(candidate)
                used.insert(candidate.signature)
                usedFamilies[category, default: []].insert(candidate.questionFamily)
            }
        }
        return selected.shuffled()
    }

    static func makeFocusedPractice(for category: MemoryCategory, avoiding previous: Set<String> = []) -> [MemoryChallenge] {
        var selected: [MemoryChallenge] = []
        var usedFamilies = Set<String>()
        for variant in 0..<focusedChallengeCount {
            var candidate = make(category: category, variant: variant)
            var attempts = 0
            while (previous.contains(candidate.signature)
                || selected.contains(where: { $0.signature == candidate.signature })
                || usedFamilies.contains(candidate.questionFamily)) && attempts < 60 {
                candidate = make(category: category, variant: variant)
                attempts += 1
            }
            selected.append(candidate)
            usedFamilies.insert(candidate.questionFamily)
        }
        return selected.shuffled()
    }

    private static func make(category: MemoryCategory, variant: Int) -> MemoryChallenge {
        switch category {
        case .visual: makeVisual(useColours: variant.isMultiple(of: 2))
        case .words: makeWords()
        case .sound: makeSound()
        case .spatial: makeSpatial()
        case .association: makeAssociation()
        case .sequence: makeSequence(useArrows: variant.isMultiple(of: 2))
        }
    }

    private static func makeVisual(useColours: Bool) -> MemoryChallenge {
        let style = Int.random(in: 0..<4)
        if useColours {
            let sequence = Array(MemorySwatch.allCases.shuffled().prefix(4))
            let family: String
            let question: String
            let correct: MemorySwatch
            switch style {
            case 0:
                let target = Int.random(in: sequence.indices)
                family = "position"; question = L10n.format("question.position", target + 1); correct = sequence[target]
            case 1:
                let target = Int.random(in: 1..<sequence.count)
                family = "before"; question = L10n.format("question.before.item", sequence[target].title); correct = sequence[target - 1]
            case 2:
                let target = Int.random(in: 0..<(sequence.count - 1))
                family = "after"; question = L10n.format("question.after.item", sequence[target].title); correct = sequence[target + 1]
            default:
                family = "missing"; question = L10n.text("question.missing.item"); correct = MemorySwatch.allCases.first { !sequence.contains($0) }!
            }
            let answers = shuffledAnswers(correct: correct, distractors: MemorySwatch.allCases.filter { $0 != correct })
            return challenge(signature: "visual-colours-\(family)-\(sequence.map(\.rawValue).joined(separator: "-"))-\(correct.rawValue)", family: family, category: .visual, stimulus: .colors(sequence), question: question, options: answers.values.map(\.title), correctOption: answers.correctIndex, seconds: 6)
        }
        let pool = ["🛼", "🍋", "🪩", "🦋", "🎈", "🧩", "🚀", "🌵", "🎸", "🦊", "🍉", "🎨", "🐙", "🛸", "🧁", "🎲"]
        let sequence = Array(pool.shuffled().prefix(5))
        let family: String
        let question: String
        let correct: String
        switch style {
        case 0:
            let target = Int.random(in: sequence.indices)
            family = "position"; question = L10n.format("question.position", target + 1); correct = sequence[target]
        case 1:
            let target = Int.random(in: 1..<sequence.count)
            family = "before"; question = L10n.format("question.before.item", sequence[target]); correct = sequence[target - 1]
        case 2:
            let target = Int.random(in: 0..<(sequence.count - 1))
            family = "after"; question = L10n.format("question.after.item", sequence[target]); correct = sequence[target + 1]
        default:
            family = "missing"; question = L10n.text("question.missing.item"); correct = pool.first { !sequence.contains($0) }!
        }
        let answers = shuffledAnswers(correct: correct, distractors: pool.filter { !sequence.contains($0) })
        return challenge(signature: "visual-symbols-\(family)-\(sequence.joined())-\(correct)", family: family, category: .visual, stimulus: .symbols(sequence), question: question, options: answers.values, correctOption: answers.correctIndex, seconds: 6)
    }

    private static func makeWords() -> MemoryChallenge {
        let keys = ["cactus", "violin", "comet", "suitcase", "cinnamon", "forest", "lantern", "ocean", "pepper", "castle", "orange", "tiger", "piano", "cloud", "garden", "rocket", "coffee", "island"]
        let chosenKeys = Array(keys.shuffled().prefix(6))
        let words = chosenKeys.map { L10n.text("word.\($0)") }
        let outsideWords = keys.filter { !chosenKeys.contains($0) }.map { L10n.text("word.\($0)") }
        let style = Int.random(in: 0..<5)
        let family: String
        let question: String
        let correct: String
        let distractors: [String]
        switch style {
        case 0:
            let target = Int.random(in: 0..<(words.count - 1))
            family = "after"; question = L10n.format("question.after.word", words[target]); correct = words[target + 1]; distractors = words.filter { $0 != correct }
        case 1:
            let target = Int.random(in: 1..<words.count)
            family = "before"; question = L10n.format("question.before.word", words[target]); correct = words[target - 1]; distractors = words.filter { $0 != correct }
        case 2:
            let target = Int.random(in: words.indices)
            family = "position"; question = L10n.format("question.word.position", target + 1); correct = words[target]; distractors = words.filter { $0 != correct }
        case 3:
            family = "missing"; question = L10n.text("question.missing.word"); correct = outsideWords.randomElement()!; distractors = words
        default:
            family = "present"; question = L10n.text("question.present.word"); correct = words.randomElement()!; distractors = outsideWords
        }
        let answers = shuffledAnswers(correct: correct, distractors: distractors)
        return challenge(signature: "words-\(family)-\(chosenKeys.joined(separator: "-"))-\(correct)", family: family, category: .words, stimulus: .words(words.map { $0.uppercased() }.joined(separator: "  —  ")), question: question, options: answers.values, correctOption: answers.correctIndex, seconds: 8)
    }

    private static func makeSound() -> MemoryChallenge {
        var tones = (0..<5).map { _ in MemoryTone.allCases.randomElement()! }
        if Set(tones.map(\.rawValue)).count == 1 { tones[2] = tones[0] == .high ? .low : .high }
        let style = Int.random(in: 0..<4)
        if style == 0 {
            let answers = shuffledAnswers(correct: tones, distractors: sequenceDistractors(for: tones, pool: MemoryTone.allCases))
            return challenge(signature: "sound-sequence-\(tones.map(\.rawValue).joined(separator: "-"))", family: "sequence", category: .sound, stimulus: .tones(tones), question: L10n.text("question.sound.sequence"), options: answers.values.map { $0.map { $0.title.uppercased() }.joined(separator: " · ") }, correctOption: answers.correctIndex, seconds: 8)
        }
        if style == 3 {
            let target = MemoryTone.allCases.randomElement()!
            let count = tones.filter { $0 == target }.count
            let answers = shuffledAnswers(correct: count, distractors: Array(0...5).filter { $0 != count })
            return challenge(signature: "sound-count-\(target.rawValue)-\(tones.map(\.rawValue).joined(separator: "-"))", family: "count", category: .sound, stimulus: .tones(tones), question: L10n.format("question.sound.count", target.title), options: answers.values.map(String.init), correctOption: answers.correctIndex, seconds: 8)
        }
        let target = style == 1 ? 0 : tones.count - 1
        let family = style == 1 ? "first" : "last"
        let question = L10n.text(style == 1 ? "question.sound.first" : "question.sound.last")
        let answers = shuffledAnswers(correct: tones[target], distractors: MemoryTone.allCases.filter { $0 != tones[target] })
        return challenge(signature: "sound-\(family)-\(tones.map(\.rawValue).joined(separator: "-"))", family: family, category: .sound, stimulus: .tones(tones), question: question, options: answers.values.map(\.title), correctOption: answers.correctIndex, seconds: 8)
    }

    private static func makeSpatial() -> MemoryChallenge {
        let cells = Array((0..<9).shuffled().prefix(3)).sorted()
        let style = Int.random(in: 0..<3)
        if style == 1 {
            let correct = cells.randomElement()!
            let answers = shuffledAnswers(correct: correct, distractors: (0..<9).filter { !cells.contains($0) })
            return challenge(signature: "spatial-lit-\(cells.map(String.init).joined(separator: "-"))-\(correct)", family: "lit", category: .spatial, stimulus: .grid(cells), question: L10n.text("question.spatial.lit"), options: answers.values.map { L10n.text("grid.\($0)") }, correctOption: answers.correctIndex, seconds: 7)
        }
        if style == 2 {
            let correct = (0..<9).filter { !cells.contains($0) }.randomElement()!
            let answers = shuffledAnswers(correct: correct, distractors: cells)
            return challenge(signature: "spatial-dark-\(cells.map(String.init).joined(separator: "-"))-\(correct)", family: "dark", category: .spatial, stimulus: .grid(cells), question: L10n.text("question.spatial.dark"), options: answers.values.map { L10n.text("grid.\($0)") }, correctOption: answers.correctIndex, seconds: 7)
        }
        var alternatives: [[Int]] = []
        while alternatives.count < 3 {
            let candidate = Array((0..<9).shuffled().prefix(3)).sorted()
            if candidate != cells && !alternatives.contains(candidate) { alternatives.append(candidate) }
        }
        let answers = shuffledAnswers(correct: cells, distractors: alternatives)
        return challenge(signature: "spatial-pattern-\(cells.map(String.init).joined(separator: "-"))", family: "pattern", category: .spatial, stimulus: .grid(cells), question: L10n.text("question.spatial"), options: answers.values.map { $0.map { L10n.text("grid.\($0)") }.joined(separator: " · ") }, correctOption: answers.correctIndex, seconds: 7)
    }

    private static func makeAssociation() -> MemoryChallenge {
        let symbols = Array(["🔭", "🎻", "🌙", "🦊", "☁️", "🗝️", "🐙", "🕯️", "🚲", "🎩", "🐚", "🪁"].shuffled().prefix(4))
        let wordKeys = Array(["mint", "velvet", "tuesday", "apricot", "friday", "mango", "opera", "tokyo", "marble", "summer", "violet", "river"].shuffled().prefix(4))
        let words = wordKeys.map { L10n.text("pair.\($0)") }
        let pairs = zip(symbols, words).map { MemoryPair(symbol: $0.0, word: $0.1.uppercased()) }
        let target = Int.random(in: pairs.indices)
        let style = Int.random(in: 0..<3)
        if style == 1 {
            let answers = shuffledAnswers(correct: symbols[target], distractors: symbols.filter { $0 != symbols[target] })
            return challenge(signature: "association-symbol-\(symbols.joined())-\(wordKeys.joined(separator: "-"))-\(target)", family: "symbol", category: .association, stimulus: .pairs(pairs), question: L10n.format("question.symbol.paired", words[target]), options: answers.values, correctOption: answers.correctIndex, seconds: 9)
        }
        if style == 2 {
            let correct = "\(symbols[target]) — \(words[target])"
            let distractors = pairs.indices.filter { $0 != target }.map { index in "\(symbols[index]) — \(words[(index + 1) % words.count])" }
            let answers = shuffledAnswers(correct: correct, distractors: distractors)
            return challenge(signature: "association-pair-\(symbols.joined())-\(wordKeys.joined(separator: "-"))-\(target)", family: "pair", category: .association, stimulus: .pairs(pairs), question: L10n.text("question.pair.present"), options: answers.values, correctOption: answers.correctIndex, seconds: 9)
        }
        let answers = shuffledAnswers(correct: words[target], distractors: words.filter { $0 != words[target] })
        return challenge(signature: "association-word-\(symbols.joined())-\(wordKeys.joined(separator: "-"))-\(target)", family: "word", category: .association, stimulus: .pairs(pairs), question: L10n.format("question.paired", symbols[target]), options: answers.values, correctOption: answers.correctIndex, seconds: 9)
    }

    private static func makeSequence(useArrows: Bool) -> MemoryChallenge {
        let pool = useArrows ? ["↑", "→", "↓", "←", "↗︎", "↙︎"] : ["●", "▲", "■", "◆", "★", "✚"]
        var sequence = (0..<5).map { _ in pool.randomElement()! }
        if Set(sequence).count == 1 { sequence[2] = pool.first { $0 != sequence[0] }! }
        let style = Int.random(in: 0..<4)
        if style == 1 {
            let target = Int.random(in: sequence.indices)
            let answers = shuffledAnswers(correct: sequence[target], distractors: pool.filter { $0 != sequence[target] })
            return challenge(signature: "sequence-position-\(target)-\(sequence.joined())", family: "position", category: .sequence, stimulus: .sequence(sequence), question: L10n.format("question.sequence.position", target + 1), options: answers.values, correctOption: answers.correctIndex, seconds: 7)
        }
        if style == 2 {
            let target = pool.randomElement()!
            let count = sequence.filter { $0 == target }.count
            let answers = shuffledAnswers(correct: count, distractors: Array(0...5).filter { $0 != count })
            return challenge(signature: "sequence-count-\(target)-\(sequence.joined())", family: "count", category: .sequence, stimulus: .sequence(sequence), question: L10n.format("question.sequence.count", target), options: answers.values.map(String.init), correctOption: answers.correctIndex, seconds: 7)
        }
        if style == 3 {
            let reversed = Array(sequence.reversed())
            let answers = shuffledAnswers(correct: reversed, distractors: sequenceDistractors(for: reversed, pool: pool))
            return challenge(signature: "sequence-reverse-\(sequence.joined())", family: "reverse", category: .sequence, stimulus: .sequence(sequence), question: L10n.text("question.sequence.reverse"), options: answers.values.map { $0.joined(separator: "  ") }, correctOption: answers.correctIndex, seconds: 7)
        }
        let answers = shuffledAnswers(correct: sequence, distractors: sequenceDistractors(for: sequence, pool: pool))
        return challenge(signature: "sequence-exact-\(sequence.joined())", family: "exact", category: .sequence, stimulus: .sequence(sequence), question: L10n.text("question.sequence"), options: answers.values.map { $0.joined(separator: "  ") }, correctOption: answers.correctIndex, seconds: 7)
    }

    private static func challenge(signature: String, family: String, category: MemoryCategory, stimulus: MemoryStimulus, question: String, options: [String], correctOption: Int, seconds: Int) -> MemoryChallenge {
        MemoryChallenge(id: signature, signature: signature, questionFamily: family, category: category, eyebrow: L10n.text("challenge.\(category.rawValue).eyebrow"), title: L10n.text("challenge.\(category.rawValue).title"), instruction: L10n.text("challenge.\(category.rawValue).instruction"), stimulus: stimulus, question: question, options: options, correctOption: correctOption, studySeconds: seconds)
    }

    private static func shuffledAnswers<T: Equatable>(correct: T, distractors: [T]) -> (values: [T], correctIndex: Int) {
        var values = [correct] + Array(distractors.filter { $0 != correct }.shuffled().prefix(3))
        values.shuffle()
        return (values, values.firstIndex(of: correct)!)
    }

    private static func sequenceDistractors<T: Equatable>(for sequence: [T], pool: [T]) -> [[T]] {
        var results: [[T]] = []
        while results.count < 3 {
            var candidate = sequence
            let index = Int.random(in: candidate.indices)
            candidate[index] = pool.filter { $0 != candidate[index] }.randomElement()!
            if candidate != sequence && !results.contains(candidate) { results.append(candidate) }
        }
        return results
    }
}

struct MemoryCategoryResult: Identifiable, Equatable, Codable {
    let category: MemoryCategory
    let correct: Int
    let total: Int
    var id: MemoryCategory { category }
    var ratio: Double { total == 0 ? 0 : Double(correct) / Double(total) }
}

struct MemoryProfile: Equatable {
    let primaryCategory: MemoryCategory
    let overallPercent: Int
    let results: [MemoryCategoryResult]
    var title: String { primaryCategory.profileTitle }
    var blurb: String { primaryCategory.profileBlurb }
    var shareText: String { L10n.format("share.profile", title, primaryCategory.title.lowercased(), overallPercent) }
    var focusCategory: MemoryCategory {
        results.enumerated().min { lhs, rhs in
            if lhs.element.ratio == rhs.element.ratio { return lhs.offset < rhs.offset }
            return lhs.element.ratio < rhs.element.ratio
        }?.element.category ?? .visual
    }

    static func build(correct: [MemoryCategory: Int], total: [MemoryCategory: Int]) -> MemoryProfile {
        let results = MemoryCategory.allCases.map { MemoryCategoryResult(category: $0, correct: correct[$0, default: 0], total: total[$0, default: 0]) }
        let primary = results.enumerated().max { lhs, rhs in lhs.element.ratio == rhs.element.ratio ? lhs.offset > rhs.offset : lhs.element.ratio < rhs.element.ratio }?.element.category ?? .visual
        let correctCount = results.reduce(0) { $0 + $1.correct }
        let questionCount = results.reduce(0) { $0 + $1.total }
        let percent = questionCount == 0 ? 0 : Int((Double(correctCount) / Double(questionCount) * 100).rounded())
        return MemoryProfile(primaryCategory: primary, overallPercent: percent, results: results)
    }
}

struct MemorySession: Identifiable, Equatable, Codable {
    let id: UUID
    let date: Date
    let primaryCategory: MemoryCategory
    let overallPercent: Int
    let results: [MemoryCategoryResult]
    init(id: UUID = UUID(), date: Date = .now, profile: MemoryProfile) {
        self.id = id; self.date = date; primaryCategory = profile.primaryCategory; overallPercent = profile.overallPercent; results = profile.results
    }
}

@MainActor @Observable
final class MemoryHistoryStore {
    private(set) var sessions: [MemorySession]
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let key: String

    init(defaults: UserDefaults = .standard, key: String = "memory.sessions.v1") {
        self.defaults = defaults; self.key = key
        sessions = defaults.data(forKey: key).flatMap { try? JSONDecoder().decode([MemorySession].self, from: $0) } ?? []
    }

    func record(_ profile: MemoryProfile, date: Date = .now) {
        sessions.insert(MemorySession(date: date, profile: profile), at: 0)
        sessions = Array(sessions.prefix(60))
        guard let data = try? JSONEncoder().encode(sessions) else { return }
        defaults.set(data, forKey: key)
    }

    #if DEBUG
    func prepareMarketingHistory() {
        let calendar = Calendar(identifier: .gregorian)
        let anchor = calendar.date(from: DateComponents(year: 2026, month: 8, day: 2, hour: 9, minute: 41)) ?? .now
        let samples: [(MemoryCategory, [MemoryCategory: Int], Int)] = [
            (.visual, [.visual: 2, .words: 1, .sound: 2, .spatial: 1, .association: 2, .sequence: 1], 0),
            (.association, [.visual: 1, .words: 1, .sound: 1, .spatial: 2, .association: 2, .sequence: 1], -7),
            (.words, [.visual: 1, .words: 2, .sound: 1, .spatial: 1, .association: 1, .sequence: 2], -16),
        ]
        let totals = Dictionary(uniqueKeysWithValues: MemoryCategory.allCases.map { ($0, 2) })
        sessions = samples.map { primary, scores, dayOffset in
            let profile = MemoryProfile.build(correct: scores, total: totals)
            let date = calendar.date(byAdding: .day, value: dayOffset, to: anchor) ?? anchor
            return MemorySession(date: date, profile: MemoryProfile(
                primaryCategory: primary,
                overallPercent: profile.overallPercent,
                results: profile.results
            ))
        }
    }
    #endif
}

@MainActor @Observable
final class MemoryGame {
    var screen: GameScreen = .home
    var phase: ChallengePhase = .study
    var currentIndex = 0
    var countdown = 0
    var selectedAnswer: Int?
    var lastAnswerWasCorrect = false
    private(set) var challenges = MemoryChallengeBank.makeScan()
    private(set) var correctScores: [MemoryCategory: Int] = [:]
    private(set) var possibleScores: [MemoryCategory: Int] = [:]
    private(set) var sourceProfile: MemoryProfile?
    private(set) var focusedCategory: MemoryCategory?
    @ObservationIgnored private var previousSignatures = Set<String>()
    @ObservationIgnored private var transitionTask: Task<Void, Never>?
    var currentChallenge: MemoryChallenge { challenges[currentIndex] }
    var challengeCount: Int { challenges.count }
    var progress: Double { Double(currentIndex + 1) / Double(max(challenges.count, 1)) }
    var profile: MemoryProfile { MemoryProfile.build(correct: correctScores, total: possibleScores) }
    var scanProfile: MemoryProfile { sourceProfile ?? profile }
    var focusedCorrectCount: Int { focusedCategory.map { correctScores[$0, default: 0] } ?? 0 }

    func startQuickScan() {
        transitionTask?.cancel()
        sourceProfile = nil
        focusedCategory = nil
        challenges = MemoryChallengeBank.makeScan(avoiding: previousSignatures)
        previousSignatures = Set(challenges.map(\.signature))
        currentIndex = 0; selectedAnswer = nil; lastAnswerWasCorrect = false; correctScores = [:]
        possibleScores = Dictionary(grouping: challenges, by: \.category).mapValues(\.count)
        screen = .playing
        beginStudy()
    }

    func startFocusedPractice() {
        transitionTask?.cancel()
        let source = sourceProfile ?? profile
        let category = focusedCategory ?? source.focusCategory
        sourceProfile = source
        focusedCategory = category
        challenges = MemoryChallengeBank.makeFocusedPractice(for: category, avoiding: previousSignatures)
        previousSignatures = Set(challenges.map(\.signature))
        currentIndex = 0; selectedAnswer = nil; lastAnswerWasCorrect = false; correctScores = [:]
        possibleScores = [category: challenges.count]
        screen = .playing
        beginStudy()
    }

    func revealAnswers() {
        guard screen == .playing, phase == .study else { return }
        transitionTask?.cancel(); phase = .answer; countdown = 0
    }

    func answer(_ option: Int) {
        guard screen == .playing, phase == .answer else { return }
        selectedAnswer = option; lastAnswerWasCorrect = option == currentChallenge.correctOption
        if lastAnswerWasCorrect { correctScores[currentChallenge.category, default: 0] += 1 }
        phase = .feedback; transitionTask?.cancel()
        transitionTask = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(850))
            guard !Task.isCancelled, let self else { return }
            if self.currentIndex == self.challenges.count - 1 { self.screen = self.focusedCategory == nil ? .results : .focusResults }
            else { self.currentIndex += 1; self.selectedAnswer = nil; self.lastAnswerWasCorrect = false; self.beginStudy() }
        }
    }

    func goHome() { transitionTask?.cancel(); screen = .home }
    func returnToScanResults() { transitionTask?.cancel(); screen = .results }

    #if DEBUG
    func prepareMarketingScreen(_ name: String) {
        switch name {
        case "visual": prepareMarketingChallenge(.visual, phase: .study)
        case "spatial": prepareMarketingChallenge(.spatial, phase: .answer)
        case "association": prepareMarketingChallenge(.association, phase: .study)
        case "challenge": prepareMarketingChallenge(.spatial, phase: .answer)
        case "result":
            possibleScores = Dictionary(uniqueKeysWithValues: MemoryCategory.allCases.map { ($0, 2) })
            correctScores = [.visual: 2, .words: 1, .sound: 2, .spatial: 1, .association: 2, .sequence: 1]
            screen = .results
        case "focus-result":
            let totals = Dictionary(uniqueKeysWithValues: MemoryCategory.allCases.map { ($0, 2) })
            sourceProfile = MemoryProfile.build(
                correct: [.visual: 2, .words: 1, .sound: 2, .spatial: 1, .association: 2, .sequence: 1],
                total: totals
            )
            focusedCategory = .words
            challenges = MemoryChallengeBank.makeFocusedPractice(for: .words)
            correctScores = [.words: 2]
            possibleScores = [.words: challenges.count]
            screen = .focusResults
        default:
            screen = .home
        }
    }

    private func prepareMarketingChallenge(_ category: MemoryCategory, phase targetPhase: ChallengePhase) {
        transitionTask?.cancel()
        challenges = MemoryChallengeBank.makeScan()
        currentIndex = challenges.firstIndex { $0.category == category } ?? 0
        phase = targetPhase
        countdown = targetPhase == .study ? currentChallenge.studySeconds : 0
        selectedAnswer = nil
        screen = .playing
    }
    #endif

    private func beginStudy() {
        transitionTask?.cancel(); phase = .study; countdown = currentChallenge.studySeconds
        transitionTask = Task { [weak self] in
            guard let self else { return }
            for remaining in stride(from: self.currentChallenge.studySeconds - 1, through: 0, by: -1) {
                try? await Task.sleep(for: .seconds(1))
                guard !Task.isCancelled else { return }
                self.countdown = remaining
            }
            guard !Task.isCancelled else { return }
            self.phase = .answer
        }
    }
}
