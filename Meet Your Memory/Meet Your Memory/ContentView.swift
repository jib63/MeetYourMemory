import SwiftUI

struct ContentView: View {
    @State private var game: MemoryGame
    @State private var history = MemoryHistoryStore()
    @State private var showsHistory = false
    @State private var showsAbout = false

    init() {
        let game = MemoryGame()
        #if DEBUG
        if let marker = ProcessInfo.processInfo.arguments.firstIndex(of: "--marketing-screen"),
           ProcessInfo.processInfo.arguments.indices.contains(marker + 1) {
            game.prepareMarketingScreen(ProcessInfo.processInfo.arguments[marker + 1])
        }
        #endif
        _game = State(initialValue: game)
    }

    var body: some View {
        ZStack {
            MemoryBackdrop()
            switch game.screen {
            case .home:
                HomeView(
                    sessionCount: history.sessions.count,
                    onStart: game.startQuickScan,
                    onHistory: { showsHistory = true },
                    onAbout: { showsAbout = true }
                )
                    .transition(.opacity.combined(with: .scale(scale: 0.96)))
            case .playing:
                ChallengeView(game: game)
                    .transition(.move(edge: .trailing).combined(with: .opacity))
            case .results:
                ResultsView(profile: game.profile, onReplay: game.startQuickScan, onHome: game.goHome, onHistory: { showsHistory = true })
                    .transition(.scale(scale: 0.94).combined(with: .opacity))
            }
        }
        .preferredColorScheme(.dark)
        .animation(.spring(response: 0.55, dampingFraction: 0.84), value: game.screen)
        .onChange(of: game.screen) { oldValue, newValue in
            if oldValue == .playing, newValue == .results { history.record(game.profile) }
        }
        .sheet(isPresented: $showsHistory) { HistoryView(sessions: history.sessions) }
        .sheet(isPresented: $showsAbout) { AboutView() }
    }
}

private struct HomeView: View {
    let sessionCount: Int
    let onStart: () -> Void
    let onHistory: () -> Void
    let onAbout: () -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var lensIsAlive = false

    var body: some View {
        GeometryReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    HStack {
                        Image(systemName: "brain.head.profile.fill").foregroundStyle(MemoryTheme.aqua)
                        Text(L10n.text("ui.memory.scan"))
                            .font(.system(.caption, design: .monospaced, weight: .black)).tracking(1.5)
                            .lineLimit(1).minimumScaleFactor(0.65)
                        Spacer()
                        HStack(spacing: 7) {
                            Text(L10n.text("ui.free"))
                                .padding(.horizontal, 10).padding(.vertical, 6)
                                .background(.white.opacity(0.12), in: Capsule())
                            Button(action: onAbout) {
                                Label(L10n.text("ui.about"), systemImage: "info.circle.fill")
                                    .padding(.horizontal, 10).padding(.vertical, 6)
                                    .background(MemoryTheme.aqua.opacity(0.2), in: Capsule())
                                    .overlay(Capsule().stroke(MemoryTheme.aqua.opacity(0.45)))
                            }
                            .buttonStyle(.plain)
                            .accessibilityHint(L10n.text("about.subtitle"))
                        }
                        .font(.system(.caption2, design: .monospaced, weight: .black))
                        .minimumScaleFactor(0.7)
                    }
                    .foregroundStyle(.white).padding(.top, 18)

                    MemoryLens(isAlive: lensIsAlive && !reduceMotion)
                        .frame(height: min(310, max(225, proxy.size.height * 0.35))).padding(.top, 5)

                    VStack(alignment: .leading, spacing: 17) {
                        Text(L10n.text("ui.meet.your"))
                            .font(.system(size: 14, weight: .black, design: .monospaced)).tracking(3.2)
                            .foregroundStyle(MemoryTheme.solar)
                        Text("Memory.")
                            .font(.system(size: min(72, proxy.size.width * 0.17), weight: .black, design: .rounded))
                            .tracking(-3).foregroundStyle(.white).minimumScaleFactor(0.65)
                        Text(L10n.text("ui.home.subtitle"))
                            .font(.system(.title3, design: .rounded, weight: .medium))
                            .foregroundStyle(MemoryTheme.mist).fixedSize(horizontal: false, vertical: true)
                        HStack(spacing: 8) {
                            FeaturePill(icon: "sparkles", text: L10n.text("ui.six.modes"), tint: MemoryTheme.coral)
                            FeaturePill(icon: "shuffle", text: L10n.text("ui.fresh.tests"), tint: MemoryTheme.aqua)
                            FeaturePill(icon: "lock.fill", text: L10n.text("ui.private"), tint: MemoryTheme.violet)
                        }
                        Button(action: onStart) {
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(L10n.text("ui.start.scan")).font(.system(.headline, design: .rounded, weight: .black))
                                    Text(L10n.text("ui.about.five")).font(.system(.caption, design: .rounded, weight: .bold)).opacity(0.72)
                                }
                                Spacer(); Image(systemName: "arrow.up.right").font(.title2.weight(.black))
                            }
                            .foregroundStyle(MemoryTheme.ink).padding(.horizontal, 22).frame(minHeight: 72)
                            .background(MemoryTheme.solar, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
                            .shadow(color: MemoryTheme.solar.opacity(0.35), radius: 24, y: 10)
                        }
                        .buttonStyle(MemoryPressStyle())

                        if sessionCount > 0 {
                            Button(action: onHistory) {
                                HStack(spacing: 14) {
                                    Image(systemName: "clock.arrow.trianglehead.counterclockwise.rotate.90")
                                        .font(.title2.weight(.black)).foregroundStyle(MemoryTheme.aqua)
                                    VStack(alignment: .leading, spacing: 3) {
                                        Text(L10n.text("ui.previous.results")).font(.system(.headline, design: .rounded, weight: .black))
                                        Text(L10n.format("ui.saved.sessions", sessionCount)).font(.system(.caption, design: .rounded, weight: .medium)).foregroundStyle(.white.opacity(0.6))
                                    }
                                    Spacer(); Image(systemName: "chevron.right").foregroundStyle(.white.opacity(0.55))
                                }
                                .foregroundStyle(.white).padding(16)
                                .background(.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                                .overlay(RoundedRectangle(cornerRadius: 20).stroke(MemoryTheme.aqua.opacity(0.25)))
                            }
                            .buttonStyle(MemoryPressStyle())
                        }

                        Text(L10n.text("ui.disclaimer.short"))
                            .font(.system(.footnote, design: .rounded, weight: .medium))
                            .foregroundStyle(MemoryTheme.mist.opacity(0.68)).padding(.bottom, 28)
                    }
                }
                .frame(maxWidth: 620).padding(.horizontal, 24).frame(maxWidth: .infinity)
            }.scrollIndicators(.hidden)
        }
        .onAppear { lensIsAlive = true }
    }
}

private struct AboutView: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ZStack {
                MemoryBackdrop()
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        Image(systemName: "brain.head.profile.fill")
                            .font(.system(size: 42, weight: .black))
                            .foregroundStyle(MemoryTheme.aqua)
                        Text(L10n.text("about.title"))
                            .font(.system(.largeTitle, design: .rounded, weight: .black))
                        Text(L10n.text("about.subtitle"))
                            .font(.system(.body, design: .rounded, weight: .medium))
                            .foregroundStyle(MemoryTheme.mist)
                            .fixedSize(horizontal: false, vertical: true)

                        AboutLink(icon: "globe", title: L10n.text("about.marketing"), detail: L10n.text("about.marketing.detail"), color: MemoryTheme.solar, url: AboutLinks.marketing)
                        AboutLink(icon: "hand.raised.fill", title: L10n.text("about.privacy"), detail: L10n.text("about.privacy.detail"), color: MemoryTheme.violet, url: AboutLinks.privacy)
                        AboutLink(icon: "questionmark.bubble.fill", title: L10n.text("about.support"), detail: L10n.text("about.support.detail"), color: MemoryTheme.coral, url: AboutLinks.support)
                    }
                    .foregroundStyle(.white)
                    .frame(maxWidth: 620, alignment: .leading)
                    .padding(24)
                    .frame(maxWidth: .infinity)
                }
            }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(L10n.text("ui.close")) { dismiss() }
                        .fontWeight(.bold)
                }
            }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }
}

private struct AboutLink: View {
    let icon: String
    let title: String
    let detail: String
    let color: Color
    let url: URL

    var body: some View {
        Link(destination: url) {
            HStack(spacing: 15) {
                Image(systemName: icon)
                    .font(.title2.weight(.black))
                    .foregroundStyle(color)
                    .frame(width: 42, height: 42)
                    .background(color.opacity(0.16), in: RoundedRectangle(cornerRadius: 13))
                VStack(alignment: .leading, spacing: 3) {
                    Text(title).font(.system(.headline, design: .rounded, weight: .black))
                    Text(detail)
                        .font(.system(.caption, design: .rounded, weight: .medium))
                        .foregroundStyle(MemoryTheme.mist.opacity(0.72))
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 8)
                Image(systemName: "arrow.up.right")
                    .font(.headline.weight(.black))
                    .foregroundStyle(.white.opacity(0.5))
            }
            .padding(16)
            .background(.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 20).stroke(color.opacity(0.3)))
        }
        .buttonStyle(MemoryPressStyle())
    }
}

private enum AboutLinks {
    private static let base = URL(string: "https://meetyourmemory.jibstudios.com")!
    private static var language: String {
        let code = (Bundle.main.preferredLocalizations.first ?? "en").lowercased()
        if code.hasPrefix("fr") { return "fr" }
        if code.hasPrefix("es") { return "es" }
        if code.hasPrefix("it") { return "it" }
        if code.hasPrefix("pt") { return "pt" }
        if code.hasPrefix("ja") { return "ja" }
        if code.hasPrefix("zh") { return "zh-Hans" }
        if code.hasPrefix("hi") { return "hi" }
        return "en"
    }

    static var marketing: URL { base.appending(path: language) }
    static var privacy: URL { base.appending(path: language).appending(path: "privacy.html") }
    static var support: URL { base.appending(path: language).appending(path: "support.html") }
}

private struct FeaturePill: View {
    let icon: String, text: String, tint: Color
    var body: some View {
        Label(text, systemImage: icon)
            .font(.system(.caption, design: .rounded, weight: .bold)).foregroundStyle(.white)
            .padding(.horizontal, 10).padding(.vertical, 9)
            .background(tint.opacity(0.24), in: Capsule()).overlay(Capsule().stroke(tint.opacity(0.55)))
            .minimumScaleFactor(0.7)
    }
}

private struct ChallengeView: View {
    @Bindable var game: MemoryGame
    @State private var tonePlayer = TonePlayer()
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        GeometryReader { proxy in
            VStack(spacing: 0) {
                VStack(spacing: 12) {
                    HStack {
                        Button(action: game.goHome) {
                            Image(systemName: "xmark").font(.headline.weight(.black)).frame(width: 42, height: 42).background(.white.opacity(0.1), in: Circle())
                        }.foregroundStyle(.white).accessibilityLabel(L10n.text("ui.leave.scan"))
                        Spacer()
                        Text("\(game.currentIndex + 1) / \(game.challengeCount)").font(.system(.caption, design: .monospaced, weight: .black)).foregroundStyle(.white.opacity(0.76))
                    }
                    GeometryReader { geometry in
                        ZStack(alignment: .leading) {
                            Capsule().fill(.white.opacity(0.11))
                            Capsule().fill(game.currentChallenge.category.tint).frame(width: geometry.size.width * game.progress)
                        }
                    }.frame(height: 7)
                }.padding(.horizontal, 20).padding(.top, 12)

                ScrollView {
                    VStack(spacing: 18) {
                        HStack(spacing: 12) {
                            Image(systemName: game.currentChallenge.category.icon).font(.title3.weight(.black)).foregroundStyle(MemoryTheme.ink)
                                .frame(width: 44, height: 44).background(game.currentChallenge.category.tint, in: RoundedRectangle(cornerRadius: 14))
                            VStack(alignment: .leading, spacing: 2) {
                                Text(game.phase == .study ? game.currentChallenge.category.studyVerb : L10n.text("ui.recall"))
                                    .font(.system(.caption2, design: .monospaced, weight: .black)).tracking(1.8).foregroundStyle(game.currentChallenge.category.tint)
                                Text(game.currentChallenge.category.title)
                                    .font(.system(.headline, design: .rounded, weight: .black))
                                    .foregroundStyle(.white)
                                    .lineLimit(nil)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                            .layoutPriority(1)
                            Spacer()
                        }
                        Group {
                            switch game.phase {
                            case .study:
                                StudyCard(challenge: game.currentChallenge, countdown: game.countdown, onReady: game.revealAnswers, onReplaySound: playCurrentSound)
                            case .answer, .feedback: AnswerCard(game: game)
                            }
                        }
                        .id("\(game.currentChallenge.id)-\(game.phase)")
                        .transition(.opacity.combined(with: .scale(scale: 0.97)))
                        Spacer(minLength: 16)
                    }
                    .frame(maxWidth: 620).padding(.horizontal, 20).padding(.top, 18)
                    .frame(maxWidth: .infinity, minHeight: proxy.size.height - 86)
                }.scrollIndicators(.hidden)
            }
        }
        .task(id: "\(game.currentChallenge.id)-\(game.phase)") {
            guard game.phase == .study, case .tones = game.currentChallenge.stimulus else { return }
            try? await Task.sleep(for: .milliseconds(350)); guard !Task.isCancelled else { return }; playCurrentSound()
        }
        .animation(reduceMotion ? nil : .spring(response: 0.45, dampingFraction: 0.88), value: game.phase)
    }

    private func playCurrentSound() {
        if case let .tones(tones) = game.currentChallenge.stimulus { tonePlayer.play(tones) }
    }
}

private struct StudyCard: View {
    let challenge: MemoryChallenge
    let countdown: Int
    let onReady: () -> Void
    let onReplaySound: () -> Void

    var body: some View {
        VStack(spacing: 22) {
            VStack(spacing: 7) {
                Text(challenge.eyebrow.uppercased()).font(.system(.caption, design: .monospaced, weight: .black)).tracking(2).foregroundStyle(MemoryTheme.ink.opacity(0.58))
                Text(challenge.title).font(.system(.title2, design: .rounded, weight: .black)).foregroundStyle(MemoryTheme.ink).multilineTextAlignment(.center)
                Text(challenge.instruction).font(.system(.subheadline, design: .rounded, weight: .semibold)).foregroundStyle(MemoryTheme.ink.opacity(0.65)).multilineTextAlignment(.center)
            }
            StimulusView(stimulus: challenge.stimulus, tint: challenge.category.tint).frame(minHeight: 180)
            HStack(spacing: 12) {
                ZStack {
                    Circle().stroke(MemoryTheme.ink.opacity(0.12), lineWidth: 5)
                    Circle().trim(from: 0, to: CGFloat(countdown) / CGFloat(max(challenge.studySeconds, 1)))
                        .stroke(MemoryTheme.ink, style: StrokeStyle(lineWidth: 5, lineCap: .round)).rotationEffect(.degrees(-90))
                    Text("\(countdown)").font(.system(.headline, design: .monospaced, weight: .black)).foregroundStyle(MemoryTheme.ink)
                }.frame(width: 48, height: 48)
                if case .tones = challenge.stimulus {
                    Button(action: onReplaySound) { Label(L10n.text("ui.play.again"), systemImage: "speaker.wave.2.fill").frame(maxWidth: .infinity) }.buttonStyle(MemorySecondaryButtonStyle())
                } else {
                    Button(action: onReady) { Text(L10n.text("ui.got.it")).frame(maxWidth: .infinity) }.buttonStyle(MemorySecondaryButtonStyle())
                }
            }
        }
        .padding(24)
        .background(LinearGradient(colors: [MemoryTheme.paper, challenge.category.tint.opacity(0.82)], startPoint: .topLeading, endPoint: .bottomTrailing), in: RoundedRectangle(cornerRadius: 32))
        .overlay(RoundedRectangle(cornerRadius: 32).stroke(.white.opacity(0.52))).shadow(color: challenge.category.tint.opacity(0.24), radius: 30, y: 16)
    }
}

private struct StimulusView: View {
    let stimulus: MemoryStimulus
    let tint: Color
    var body: some View {
        switch stimulus {
        case let .symbols(symbols):
            HStack(spacing: 9) { ForEach(Array(symbols.enumerated()), id: \.offset) { index, symbol in
                Text(symbol).font(.system(size: 38)).frame(maxWidth: .infinity, minHeight: 72)
                    .background(.white.opacity(index.isMultiple(of: 2) ? 0.72 : 0.46), in: RoundedRectangle(cornerRadius: 18))
            }}
        case let .words(text):
            Text(text).font(.system(.title3, design: .rounded, weight: .black)).foregroundStyle(MemoryTheme.ink).multilineTextAlignment(.center).lineSpacing(7)
                .padding(18).frame(maxWidth: .infinity, minHeight: 170).background(.white.opacity(0.62), in: RoundedRectangle(cornerRadius: 22))
        case let .colors(swatches):
            HStack(spacing: 12) { ForEach(Array(swatches.enumerated()), id: \.offset) { index, swatch in
                Circle().fill(swatch.color).frame(width: 46, height: 46).overlay(Text("\(index + 1)").font(.caption2.bold()).foregroundStyle(MemoryTheme.ink.opacity(0.52)))
                    .shadow(color: swatch.color.opacity(0.45), radius: 10, y: 5)
            }}.padding(.vertical, 28)
        case .tones:
            VStack(spacing: 16) {
                ZStack { ForEach(0..<3, id: \.self) { ring in Circle().stroke(MemoryTheme.ink.opacity(0.12 + Double(ring) * 0.08), lineWidth: 4).frame(width: CGFloat(82 + ring * 38), height: CGFloat(82 + ring * 38)) }
                    Image(systemName: "waveform").font(.system(size: 46, weight: .black)).foregroundStyle(MemoryTheme.ink) }
                Text(L10n.text("ui.listen.pitch")).font(.system(.subheadline, design: .rounded, weight: .bold)).foregroundStyle(MemoryTheme.ink.opacity(0.62))
            }
        case let .grid(active):
            LazyVGrid(columns: Array(repeating: GridItem(.fixed(58), spacing: 10), count: 3), spacing: 10) {
                ForEach(0..<9, id: \.self) { index in RoundedRectangle(cornerRadius: 15).fill(active.contains(index) ? MemoryTheme.ink : .white.opacity(0.48)).frame(width: 58, height: 58)
                    .overlay { if active.contains(index) { Circle().fill(tint).frame(width: 15, height: 15) } } }
            }
        case let .pairs(pairs):
            VStack(spacing: 9) { ForEach(pairs) { pair in
                HStack { Text(pair.symbol).font(.title2); Image(systemName: "arrow.left.and.right").font(.caption.weight(.black)).foregroundStyle(MemoryTheme.ink.opacity(0.36)); Text(pair.word).font(.system(.headline, design: .rounded, weight: .black)).foregroundStyle(MemoryTheme.ink); Spacer() }
                    .padding(.horizontal, 15).frame(height: 42).background(.white.opacity(0.55), in: RoundedRectangle(cornerRadius: 13))
            }}
        case let .sequence(items):
            HStack(spacing: 9) { ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                Text(item).font(.system(size: 31, weight: .black, design: .rounded)).foregroundStyle(MemoryTheme.ink).frame(maxWidth: .infinity, minHeight: 66)
                    .background(index.isMultiple(of: 2) ? .white.opacity(0.7) : tint.opacity(0.5), in: RoundedRectangle(cornerRadius: 16))
            }}
        }
    }
}

private struct AnswerCard: View {
    @Bindable var game: MemoryGame
    var body: some View {
        VStack(spacing: 20) {
            VStack(spacing: 8) {
                Text(L10n.text("ui.what.stuck")).font(.system(.caption, design: .monospaced, weight: .black)).tracking(2).foregroundStyle(game.currentChallenge.category.tint)
                Text(game.currentChallenge.question)
                    .font(.system(.title2, design: .rounded, weight: .black))
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.center)
                    .lineLimit(nil)
                    .fixedSize(horizontal: false, vertical: true)
            }
            VStack(spacing: 11) {
                ForEach(Array(game.currentChallenge.options.enumerated()), id: \.offset) { index, option in
                    Button { game.answer(index) } label: {
                        HStack(spacing: 14) {
                            Text(String(UnicodeScalar(65 + index)!)).font(.system(.caption, design: .monospaced, weight: .black)).frame(width: 34, height: 34).background(optionForeground(index).opacity(0.13), in: Circle())
                            Text(option)
                                .font(.system(.headline, design: .rounded, weight: .bold))
                                .multilineTextAlignment(.leading)
                                .lineLimit(nil)
                                .fixedSize(horizontal: false, vertical: true)
                                .layoutPriority(1)
                            Spacer(minLength: 0)
                            if game.phase == .feedback, index == game.currentChallenge.correctOption {
                                Image(systemName: "checkmark.circle.fill").font(.title2).foregroundStyle(MemoryTheme.aqua)
                            } else if game.phase == .feedback, index == game.selectedAnswer {
                                Image(systemName: "xmark.circle.fill").font(.title2).foregroundStyle(MemoryTheme.coral)
                            }
                        }
                        .foregroundStyle(optionForeground(index))
                        .padding(.horizontal, 16)
                        .padding(.vertical, 14)
                        .frame(maxWidth: .infinity, minHeight: 64, alignment: .leading)
                        .background(optionBackground(index), in: RoundedRectangle(cornerRadius: 20)).overlay(RoundedRectangle(cornerRadius: 20).stroke(optionBorder(index), lineWidth: 1.5))
                    }.buttonStyle(MemoryPressStyle()).disabled(game.phase == .feedback)
                }
            }
            if game.phase == .feedback {
                Label(L10n.text(game.lastAnswerWasCorrect ? "ui.feedback.correct" : "ui.feedback.wrong"), systemImage: game.lastAnswerWasCorrect ? "sparkles" : "wind")
                    .font(.system(.subheadline, design: .rounded, weight: .black)).foregroundStyle(game.lastAnswerWasCorrect ? MemoryTheme.aqua : MemoryTheme.coral)
            } else {
                Text(L10n.text("ui.choose.answer")).font(.system(.footnote, design: .rounded, weight: .medium)).foregroundStyle(.white.opacity(0.55))
            }
        }
        .padding(22).background(MemoryTheme.inkSoft.opacity(0.96), in: RoundedRectangle(cornerRadius: 32))
        .overlay(RoundedRectangle(cornerRadius: 32).stroke(game.currentChallenge.category.tint.opacity(0.5))).shadow(color: .black.opacity(0.28), radius: 28, y: 15)
    }
    private func optionForeground(_ index: Int) -> Color { game.phase == .feedback && index == game.currentChallenge.correctOption ? MemoryTheme.ink : .white }
    private func optionBackground(_ index: Int) -> Color {
        guard game.phase == .feedback else { return .white.opacity(0.075) }
        if index == game.currentChallenge.correctOption { return MemoryTheme.aqua }
        if index == game.selectedAnswer { return MemoryTheme.coral.opacity(0.28) }
        return .white.opacity(0.045)
    }
    private func optionBorder(_ index: Int) -> Color {
        guard game.phase == .feedback else { return .white.opacity(0.13) }
        if index == game.currentChallenge.correctOption { return MemoryTheme.aqua }
        if index == game.selectedAnswer { return MemoryTheme.coral }
        return .clear
    }
}

private struct ResultsView: View {
    let profile: MemoryProfile
    let onReplay: () -> Void
    let onHome: () -> Void
    let onHistory: () -> Void
    var body: some View {
        ScrollView {
            VStack(spacing: 22) {
                HStack {
                    Button(action: onHome) { Image(systemName: "xmark").font(.headline.weight(.black)).frame(width: 42, height: 42).background(.white.opacity(0.1), in: Circle()) }.foregroundStyle(.white)
                    Spacer(); Text(L10n.text("ui.memory.map")).font(.system(.caption, design: .monospaced, weight: .black)).tracking(1.7).foregroundStyle(.white.opacity(0.72)); Spacer(); Color.clear.frame(width: 42, height: 42)
                }
                ProfileHero(profile: profile)
                BreakdownCard(results: profile.results)
                HStack(spacing: 12) {
                    ShareLink(item: profile.shareText) { Label(L10n.text("ui.share"), systemImage: "square.and.arrow.up").frame(maxWidth: .infinity) }.buttonStyle(MemorySecondaryButtonStyle(dark: true))
                    Button(action: onReplay) { Label(L10n.text("ui.replay"), systemImage: "arrow.clockwise").frame(maxWidth: .infinity) }.buttonStyle(MemoryPrimaryButtonStyle())
                }
                Button(action: onHistory) { Label(L10n.text("ui.view.history"), systemImage: "chart.xyaxis.line").frame(maxWidth: .infinity) }.buttonStyle(MemorySecondaryButtonStyle(dark: true))
                PortfolioSection(primaryCategory: profile.primaryCategory)
                Text(L10n.text("ui.disclaimer.long")).font(.system(.footnote, design: .rounded, weight: .medium)).foregroundStyle(.white.opacity(0.5)).multilineTextAlignment(.center).padding(.vertical, 12)
            }
            .frame(maxWidth: 620).padding(.horizontal, 20).padding(.vertical, 16).frame(maxWidth: .infinity)
        }.scrollIndicators(.hidden)
    }
}

private struct ProfileHero: View {
    let profile: MemoryProfile
    var body: some View {
        VStack(spacing: 18) {
            ZStack {
                Circle().fill(.white.opacity(0.3)).frame(width: 136, height: 136)
                Circle().stroke(MemoryTheme.ink.opacity(0.16), style: StrokeStyle(lineWidth: 3, dash: [4, 8])).frame(width: 164, height: 164)
                Image(systemName: profile.primaryCategory.icon).font(.system(size: 62, weight: .black)).foregroundStyle(MemoryTheme.ink)
            }
            VStack(spacing: 7) {
                Text(L10n.text("ui.you.are")).font(.system(.caption, design: .monospaced, weight: .black)).tracking(2.4).foregroundStyle(MemoryTheme.ink.opacity(0.56))
                Text(profile.title).font(.system(.largeTitle, design: .rounded, weight: .black)).tracking(-1.2).foregroundStyle(MemoryTheme.ink).multilineTextAlignment(.center)
                Text(profile.blurb).font(.system(.body, design: .rounded, weight: .semibold)).foregroundStyle(MemoryTheme.ink.opacity(0.7)).multilineTextAlignment(.center)
            }
            HStack(spacing: 7) { Text(L10n.text("ui.memory.spark")).font(.system(.caption2, design: .monospaced, weight: .black)).tracking(1.2); Text("\(profile.overallPercent)%").font(.system(.title3, design: .rounded, weight: .black)) }
                .foregroundStyle(.white).padding(.horizontal, 15).padding(.vertical, 9).background(MemoryTheme.ink, in: Capsule())
        }
        .padding(26).frame(maxWidth: .infinity)
        .background(LinearGradient(colors: [MemoryTheme.paper, profile.primaryCategory.tint], startPoint: .topLeading, endPoint: .bottomTrailing), in: RoundedRectangle(cornerRadius: 34))
        .overlay(RoundedRectangle(cornerRadius: 34).stroke(.white.opacity(0.6))).shadow(color: profile.primaryCategory.tint.opacity(0.33), radius: 34, y: 16)
    }
}

private struct BreakdownCard: View {
    let results: [MemoryCategoryResult]
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 4) {
                Text(L10n.text("ui.memory.mix")).font(.system(.caption, design: .monospaced, weight: .black)).tracking(1.7).foregroundStyle(MemoryTheme.aqua)
                Text(L10n.text("ui.mix.subtitle")).font(.system(.headline, design: .rounded, weight: .black)).foregroundStyle(.white)
            }
            ForEach(results) { result in
                VStack(spacing: 7) {
                    HStack { Label(result.category.title, systemImage: result.category.icon).font(.system(.subheadline, design: .rounded, weight: .bold)); Spacer(); Text("\(result.correct)/\(result.total)").font(.system(.caption, design: .monospaced, weight: .black)).foregroundStyle(.white.opacity(0.62)) }.foregroundStyle(.white)
                    GeometryReader { geometry in ZStack(alignment: .leading) { Capsule().fill(.white.opacity(0.09)); Capsule().fill(result.category.tint).frame(width: max(8, geometry.size.width * result.ratio)) } }.frame(height: 9)
                }
            }
        }
        .padding(22).background(MemoryTheme.inkSoft.opacity(0.95), in: RoundedRectangle(cornerRadius: 28)).overlay(RoundedRectangle(cornerRadius: 28).stroke(.white.opacity(0.1)))
    }
}

private struct HistoryView: View {
    let sessions: [MemorySession]
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        ZStack {
            MemoryBackdrop()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(L10n.text("history.eyebrow")).font(.system(.caption, design: .monospaced, weight: .black)).tracking(1.8).foregroundStyle(MemoryTheme.aqua)
                            Text(L10n.text("history.title")).font(.system(.largeTitle, design: .rounded, weight: .black)).foregroundStyle(.white)
                        }
                        Spacer(); Button { dismiss() } label: { Image(systemName: "xmark").font(.headline.weight(.black)).frame(width: 42, height: 42).background(.white.opacity(0.1), in: Circle()) }.foregroundStyle(.white)
                    }
                    Text(L10n.text("history.subtitle")).font(.system(.body, design: .rounded, weight: .medium)).foregroundStyle(.white.opacity(0.65))
                    if sessions.isEmpty {
                        ContentUnavailableView(L10n.text("history.empty.title"), systemImage: "sparkles", description: Text(L10n.text("history.empty.body"))).foregroundStyle(.white)
                    } else {
                        ForEach(Array(sessions.enumerated()), id: \.element.id) { index, session in
                            SessionCard(session: session, isLatest: index == 0)
                        }
                    }
                }.frame(maxWidth: 620).padding(22).frame(maxWidth: .infinity)
            }.scrollIndicators(.hidden)
        }.preferredColorScheme(.dark)
    }
}

private struct SessionCard: View {
    let session: MemorySession
    let isLatest: Bool
    var body: some View {
        VStack(alignment: .leading, spacing: 15) {
            HStack(alignment: .top) {
                Image(systemName: session.primaryCategory.icon).font(.title2.weight(.black)).foregroundStyle(MemoryTheme.ink).frame(width: 52, height: 52).background(session.primaryCategory.tint, in: RoundedRectangle(cornerRadius: 16))
                VStack(alignment: .leading, spacing: 3) {
                    HStack { Text(session.primaryCategory.profileTitle).font(.system(.headline, design: .rounded, weight: .black)); if isLatest { Text(L10n.text("history.latest")).font(.system(size: 9, weight: .black, design: .monospaced)).foregroundStyle(MemoryTheme.aqua).padding(.horizontal, 7).padding(.vertical, 4).background(MemoryTheme.aqua.opacity(0.14), in: Capsule()) } }
                    Text(session.date.formatted(date: .abbreviated, time: .shortened)).font(.system(.caption, design: .rounded, weight: .medium)).foregroundStyle(.white.opacity(0.55))
                }
                Spacer(); Text("\(session.overallPercent)%").font(.system(.title2, design: .rounded, weight: .black)).foregroundStyle(MemoryTheme.solar)
            }
            HStack(spacing: 6) { ForEach(session.results) { result in VStack(spacing: 5) { Image(systemName: result.category.icon).font(.caption.weight(.black)); Text("\(result.correct)/\(result.total)").font(.system(size: 10, weight: .black, design: .monospaced)) }.foregroundStyle(result.category.tint).frame(maxWidth: .infinity).padding(.vertical, 9).background(.white.opacity(0.055), in: RoundedRectangle(cornerRadius: 12)) } }
        }.foregroundStyle(.white).padding(17).background(MemoryTheme.inkSoft.opacity(0.94), in: RoundedRectangle(cornerRadius: 24)).overlay(RoundedRectangle(cornerRadius: 24).stroke(session.primaryCategory.tint.opacity(0.25)))
    }
}

private struct PortfolioSection: View {
    let primaryCategory: MemoryCategory
    private var apps: [PortfolioApp] { PortfolioApp.ordered(for: primaryCategory) }
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 5) {
                Text(L10n.text("promo.eyebrow")).font(.system(.caption, design: .monospaced, weight: .black)).tracking(1.35).foregroundStyle(MemoryTheme.solar)
                Text(L10n.text("promo.title")).font(.system(.title3, design: .rounded, weight: .black)).foregroundStyle(.white)
            }
            ForEach(Array(apps.enumerated()), id: \.element.id) { index, app in
                Link(destination: app.url) {
                    HStack(spacing: 15) {
                        Image(systemName: app.icon).font(.title2.weight(.black)).foregroundStyle(MemoryTheme.ink).frame(width: 52, height: 52).background(app.tint, in: RoundedRectangle(cornerRadius: 16))
                        VStack(alignment: .leading, spacing: 4) {
                            HStack(spacing: 7) { Text(app.name).font(.system(.headline, design: .rounded, weight: .black)); if index == 0 { Text(L10n.text("promo.match")).font(.system(size: 9, weight: .black, design: .monospaced)).padding(.horizontal, 7).padding(.vertical, 4).background(app.tint.opacity(0.2), in: Capsule()).foregroundStyle(app.tint) } }
                            Text(app.tagline).font(.system(.subheadline, design: .rounded, weight: .medium)).foregroundStyle(.white.opacity(0.62)).multilineTextAlignment(.leading)
                        }
                        Spacer(); Image(systemName: "arrow.up.right").font(.headline.weight(.black)).foregroundStyle(app.tint)
                    }
                    .foregroundStyle(.white).padding(15).background(.white.opacity(index == 0 ? 0.11 : 0.065), in: RoundedRectangle(cornerRadius: 22))
                    .overlay(RoundedRectangle(cornerRadius: 22).stroke(index == 0 ? app.tint.opacity(0.55) : .white.opacity(0.08)))
                }.buttonStyle(MemoryPressStyle())
            }
        }.padding(.top, 8)
    }
}

private struct PortfolioApp: Identifiable {
    let id: String, name: String, tagline: String, icon: String
    let tint: Color
    let url: URL
    static var rekko: PortfolioApp { .init(id: "rekko", name: "Rekko", tagline: L10n.text("promo.rekko"), icon: "play.rectangle.on.rectangle.fill", tint: MemoryTheme.violet, url: URL(string: "https://apps.apple.com/app/id6774924405")!) }
    static var soundLibrary: PortfolioApp { .init(id: "sound", name: "My Sound Library", tagline: L10n.text("promo.sound"), icon: "waveform", tint: MemoryTheme.coral, url: URL(string: "https://apps.apple.com/app/my-sound-library/id6771492676")!) }
    static var reliquum: PortfolioApp { .init(id: "reliquum", name: "Reliquum", tagline: L10n.text("promo.reliquum"), icon: "envelope.badge.fill", tint: MemoryTheme.solar, url: URL(string: "https://apps.apple.com/app/id6769756899")!) }
    static func ordered(for category: MemoryCategory) -> [PortfolioApp] {
        switch category { case .sound, .visual, .spatial: [soundLibrary, reliquum, rekko]; case .words, .sequence: [reliquum, rekko, soundLibrary]; case .association: [rekko, reliquum, soundLibrary] }
    }
}

#Preview { ContentView() }
