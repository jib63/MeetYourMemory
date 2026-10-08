# Meet Your Memory

Meet Your Memory is a free, playful iOS memory quiz built with SwiftUI. A five-minute scan explores six dimensions of memory through colourful visual, verbal, auditory, spatial, associative, and sequence challenges.

## Highlights

- Twelve procedurally generated challenges per scan
- Fresh questions on replay, with the previous set actively avoided
- Six-part memory profile and shareable result
- Focused three-challenge practice for the memory mode that needs another pass
- Private on-device history for up to 60 sessions
- Local audio-tone generation with no network dependency
- Contextual discovery cards for Rekko, Ekkos, and Reliquum
- English, French, Spanish, Italian, Portuguese, Japanese, Simplified Chinese, and Hindi localizations
- Reduced-motion support and responsive iPhone/iPad layouts
- One scan that silently mixes the regular library with ten partial-fold games or four expanded-screen games as the display changes

## Requirements

- Xcode 27.1 or newer (includes the iPhone Duo SDK)
- iOS 17.6 or newer for the memory scan and expanded iPad games; iOS 27.1 or newer for live iPhone Duo posture adaptation

Open `Meet Your Memory/Meet Your Memory.xcodeproj` and run the `Meet Your Memory` scheme.

The experience is intended for entertainment and is not a medical or learning-style assessment.

## Adaptive games

There is one home screen, one **Start the scan** action, and no adaptive-game catalog. The scan chooses each upcoming challenge from the libraries available for the current display:

- A compact iPhone uses the regular challenge library.
- A partially folded iPhone Duo uses the regular library plus ten cross-fold challenges, with a preference for the cross-fold choices.
- A flat iPhone Duo or iPad uses the regular library plus Panorama Pairs, Orbit Map, Sound Board, and Comet Field, with a preference for the expanded choices.

Posture changes never silently replace the active challenge. Matching rounds reflow while preserving object and destination identities. Spatial routes, launch direction, and rhythm arrangements stay fixed during recall; a change that would rearrange them pauses the round. Closing the phone, losing either physical pane, or running out of playable space also pauses it. Answers and phase remain saved, and the hidden solution stays hidden. After restoring a compatible layout, the player explicitly resumes. Checked rounds can continue to the scan even on the outer display.

The recovery screen also offers a fresh regular challenge in the same memory category and scan slot, so even a narrow outer display can continue. The abandoned round adds no points or penalty. Only the following slot is selected automatically from the new display's libraries. Board geometry reserves space for the footer and fold margins, rejects crowded panes, and cancels unfinished gestures, sounds, and animations while it settles. Screen-specific scores contribute to the same profile and local scan history. Adaptive text is available in English and French, with English fallback in the other app languages.

The `DuoArcadeTests` suite covers the catalog, transparent next-challenge selection, active-round continuity, scoring, corrections, and gesture geometry. `DuoArcadeUITests` covers every interaction family and verifies that folded and expanded scans expose no game menu. Its deterministic controls require a Debug build and are absent from Release builds. Physical hinge detection and cross-fold touch continuity should also be checked on iPhone Duo hardware.

## App Store media

Localized screenshots, product-page headers and search artwork are prepared
with the App Store Connect API 4.5.1 workflow. See [the media guide](AppStore/README.md)
and [the generated review gallery](AppStore/exports/delivery/index.html).
The 192 prepared screenshots are uploaded to App Store version 1.1.0 in all
eight languages, including two native unfolded Duo game screenshots per
language. The 16 localized header/search assets are also uploaded and verified.
No previews or review submissions were performed.

## License

Meet Your Memory is available under the [MIT License](LICENSE).
