# Suggested title

I open-sourced the complete SwiftUI project behind my App Store app (MIT)

# Post

Hi r/appledevelopers,

I’m the developer of **Meet Your Memory**, a small SwiftUI app I recently took from an idea to the App Store. I’m sharing it here primarily as an open-source development resource rather than just an app launch.

I’ve released the complete project under the **MIT License**, so anyone learning Apple development can inspect it, run it, modify it, or use parts of it in their own experiments:

- **Source code:** https://github.com/jib63/MeetYourMemory

The repository is a complete shipped app rather than an isolated tutorial sample. Some of the implementation areas that may be useful to other developers include:

- A SwiftUI flow built around explicit home, playing, and results states
- A procedural engine that creates 12 challenges across six memory categories
- Generation rules and tests that prevent invalid, unbalanced, or immediately repeated challenges
- Locally generated tones with `AVAudioEngine`, without downloaded audio files
- On-device persistence for previous results, with no account or backend
- Eight localizations and responsive iPhone/iPad layouts
- Reduced-motion support and reusable SwiftUI components
- XCTest coverage plus an XCUITest screenshot rig for localized App Store assets

I also wrote a detailed article about the decisions and lessons behind the project—from defining one clear product promise and designing replayability into the architecture, through privacy, localization, invariant testing, and automating the App Store screenshot pipeline:

- **Build tutorial:** https://www.linkedin.com/pulse/from-simple-idea-app-store-how-i-built-meet-your-memory-meyer-vtk7e/

If you want to see the shipped result before exploring the code:

- **Website:** https://meetyourmemory.jibstudios.com/
- **App Store:** https://apps.apple.com/fr/app/meet-your-memory/id6796454074?l=en-GB

The app is free, has no ads or account, and does not collect user data. It is intended as entertainment, not as a medical or educational assessment.

I’d especially appreciate developer feedback on the project structure, procedural-generation tests, and automated screenshot workflow. I’d also be interested to hear what documentation would make the repository more useful to someone building their first SwiftUI app.

# Alternative titles

- Open-source SwiftUI App Store project: procedural content, local persistence, localization, and UI tests
- From SwiftUI idea to App Store: full MIT-licensed source and development write-up
