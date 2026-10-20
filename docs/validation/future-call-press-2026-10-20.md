# Future Call visual revision

- Scope: journey visual components and bundled assets only. No backend, credentials, ASR/TTS state machine, or other module changes in this revision.
- Replaced the faulty display font with complete local Noto Serif SC 400/600; checked distinct glyph mapping for 己、已、巳、回 and inspected the rendered headline/receipt.
- Neutral gray paper, pill buttons, thin browser frame, licensed telephone photograph, newspaper receipt hierarchy.
- CSS entry, paper reveal, hover, focus and press effects; reduced-motion override; recording/playback timers unaffected.
- Browser verified at CSS 2160 x 3840, 390 x 843 and 1440 x 899. No horizontal document overflow. Start button visible on home. Images and fonts loaded.
- Completed text entry -> real compose response -> preview with synthetic sample about a companion robot. Inspected summary, keywords and quote on the receipt. No personal voice recording or new voice enrollment was used in this UI verification.
- All 54 existing frontend tests passed. Production build passed. Print CSS retains 72 mm sizing; physical printer output has not been rechecked.
- Screenshots: `future-call-press-home.png`, `future-call-press-result.png`, `future-call-press-mobile-home.png`, `future-call-press-mobile-result.png`.
