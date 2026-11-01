KISAN MITRA — RESPONSIVE, MOTION-FREE FRONTEND
==============================================

WHAT CHANGED
------------
- ALL animation removed: Three.js 3D sprout, particles, scroll-reveal, card tilt,
  scanner line, click ripples, route progress bar, floating taglines, shimmer,
  CSS transitions/keyframes, smooth scrolling and Chart.js chart animation.
- Deleted: js/kisan-3d-effects.js, css/kisan-3d-theme.css and the Three.js CDN tag.
- css/style.css is now the single stylesheet (dark default, light via theme button).
  Mobile-first, fluid spacing and type, CSS grid/flex, 44px touch targets, 16px
  inputs (no iOS zoom), scrollable tables. Tested at 360, 768 and 1280 px widths.
- New js/ui.js (no API calls) adds interactivity:
    * Hamburger menu for navigation on tablets/phones (Esc / outside click closes)
    * Show/Hide password buttons on login and register
    * Drag-and-drop or paste (Ctrl+V) a crop image on the Crop Doctor page
    * Click any table header to sort (numbers, dates, text)
    * Live search box on My Reports
    * Character counters on long text boxes
    * Ctrl/Cmd+Enter sends chat messages; Enter in a filter row runs the search
    * Back-to-top button (instant jump) and auto-scroll to newest chat message
    * Hover / active / focus-visible states (instant colour changes only)

UNCHANGED
---------
HTML element IDs, API paths, payloads, localStorage keys, translations (i18n.js),
authentication, reports, weather, mandi, chat and marketplace logic.

INSTALLATION
------------
Replace your frontend folder with this one and serve it as before.

ALL STATES / DISTRICTS / COMMODITIES (resource 35985678-0d79-46b4-9ed6-6f13308a1d24)
-------------------------------------------------------------------------------
Run once with your data.gov.in key to pull the exact values from the dataset:
    DATA_GOV_API_KEY=your_key node tools/build-mandi-data.mjs
This writes js/mandi-data.js (all states -> districts, all commodities); the
dashboard uses it automatically. Without it, js/mandi-fallback.js supplies every
state/UT and ~140 commodities, and states with no district list get a text box.
