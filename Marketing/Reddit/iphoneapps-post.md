# Suggested title

What I learned building a private iPhone app with no account, backend, ads, or analytics

# Post

Hi r/iPhoneApps,

I’m the developer of **Meet Your Memory**, and I wanted to share a few things I learned while building and shipping it—not just leave an App Store link and disappear.

The app is a playful five-minute memory scan with 12 short challenges covering visual, verbal, sound, spatial, associative, and sequence memory. It creates a profile at the end and keeps previous results locally on the device.

The biggest product decision was choosing what *not* to build. There is no account, backend, cloud database, advertising, analytics, or tracking. That made privacy clearer for users, but it also made the app smaller and removed several possible failure points.

A few other lessons from the project:

- Procedural content needs rules, not just randomness. Each scan includes every memory category twice, varies the question styles, and avoids immediately repeating the previous session.
- A small, explicit state flow made the SwiftUI code easier to reason about: home → playing → results, with study → answer → result inside each challenge.
- Localization affects layout as much as text. Supporting eight languages meant planning for longer labels and different typography across iPhone and iPad.
- Automating App Store screenshots early was worth it. An XCUITest rig generates controlled screens for every supported language and device family.
- Keeping data on-device can be a useful product feature, not merely a technical limitation.

I released the complete project under the **MIT License** in case anyone wants to study, modify, or build on it:

- **Source code:** https://github.com/jib63/MeetYourMemory
- **Detailed build tutorial:** https://www.linkedin.com/pulse/from-simple-idea-app-store-how-i-built-meet-your-memory-meyer-vtk7e/

For transparency, the shipped app is completely free, with **no subscriptions or in-app purchases**:

- **Website:** https://meetyourmemory.jibstudios.com/
- **App Store:** https://apps.apple.com/fr/app/meet-your-memory/id6796454074?l=en-GB

I’m curious how people here feel about fully local apps: do you prefer not needing an account, even when that means your history does not automatically sync between devices?

The memory profile is intended for entertainment and self-discovery, not as a medical or educational assessment.

# Alternative titles

- Do you prefer iPhone apps with no account, even if your data cannot sync automatically?
- I built an entirely local iPhone app and open-sourced it—here’s what I learned

# Posting note

r/iPhoneApps says standalone promotional posts may be removed and asks members to contribute before mentioning their own apps. Use this version only if you are already participating in the community. Otherwise, contribute to existing discussions first or ask the moderators whether this open-source development write-up is appropriate.
