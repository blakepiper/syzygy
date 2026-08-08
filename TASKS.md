# Syzygy — Task Checklist

Ordered, ID'd checklist. Check off (`- [ ]` → `- [x]`) as you complete each
task, and add a one-line note if you deviated from the plan. Dependencies
are noted inline; unless stated otherwise, tasks within a milestone are
sequential.

**M0–M9 (v0.1) are complete** — see `IMPLEMENTATION_PLAN.md` for that
history; it is not repeated here. This file now tracks a fresh batch of
bugs and gaps found in day-to-day use of v0.1, filed 2026-08-08.

---

## M10 — Onboarding and ritual-key fixes

### M10.1 — Birthplace geocoding autopopulation

`src/syzygy/tui/screens/profile_create.py` currently requires the user to
type latitude, longitude, and IANA timezone by hand — the `geocoding`
extra (`geopy`, `timezonefinder`) is declared in `pyproject.toml` and
referenced in the screen's own docstring and `DESIGN.md` §6.1, but nothing
actually calls it. `DESIGN.md` §6.1's own example transcript shows the
confirm panel displaying *resolved* coordinates/timezone under an
*entered* place label — that resolution step doesn't exist yet.

- [ ] M10.1a `src/syzygy/geocoding.py` (or similar, mirroring the
      `syzygy.astrology` seam): given a free-text place label, return
      `(latitude, longitude, iana_timezone)`. Timezone is the
      **birthplace's** zone (needed to convert local birth time to UTC for
      the natal chart) — never the current-location zone; that keeps this
      consistent with the "no current-location astrology" invariant in
      `AGENTS.md`. Use `geopy` for the place → lat/long lookup and
      `timezonefinder` for lat/long → IANA name. Import both lazily inside
      the function, not at module load, so the rest of the app still runs
      without the `geocoding` extra installed.
- [ ] M10.1b Wire it into the form phase: when the user fills in
      `place-label` and presses REVIEW with `latitude`/`longitude`/`timezone`
      still blank, run M10.1a and prefill those three fields *before*
      showing the confirm panel, clearly marked as auto-resolved. The user
      still reviews and can EDIT before CONFIRM — the existing two-phase
      form/confirm flow already provides that; this task only removes the
      requirement to type coordinates by hand. Manual entry must keep
      working exactly as today (leave lat/long/timezone as the override
      path) — do not make geocoding mandatory.
- [ ] M10.1c Handle failure explicitly: extra not installed, no network,
      or no geocoder match — show an inline message on the form ("could
      not resolve a location for <place>; enter coordinates manually") and
      leave the manual fields open, per `DESIGN.md` §23. Never block
      profile creation on a geocoding failure.
- [ ] M10.1d Run geocoding off the event loop (`@work(thread=True)`, same
      pattern `_calculate` already uses) — it's a network call.
- [ ] M10.1e Tests: fake/mocked geocoder + timezone finder for determinism
      (no real network calls in the test suite); cover the prefill path,
      the manual-override path, and the failure path. Update
      `README.md`'s `pip install ".[geocoding]"` note if the UX changes
      what installing the extra actually turns on.

### M10.2 — "q" (quit) does not work on every screen

Confirmed by reading `src/syzygy/tui/screens/*.py`: `("q", "quit", "quit")`
is declared per-screen, and it's simply missing from four of them —
`profile_create.py`, `wheel.py`, `reveal.py`, and `reading.py`. There is no
app-level fallback (`SyzygyApp` in `src/syzygy/tui/app.py` declares no
`BINDINGS` of its own), so on those four screens `q` does nothing at all.
`reading.py` is the screen most readings end on, which is almost certainly
what was actually hit.

- [ ] M10.2a Move the quit binding to `SyzygyApp` itself
      (`src/syzygy/tui/app.py`) as a single `BINDINGS = [("q", "quit",
      "quit")]`, so it applies everywhere by construction instead of being
      copy-pasted per screen. Remove the now-redundant per-screen entries
      in `welcome.py`, `home.py`, `chart.py`, `archive.py`,
      `profile_select.py`, `too_small.py`.
- [ ] M10.2b Verify (via a test, not just reasoning) that a focused `Input`
      on `profile_create.py`'s form still accepts a literal `q` keystroke
      as text rather than quitting — Textual gives a focused widget's own
      key handling first refusal, so this should already hold, but assert
      it explicitly since this task is specifically about `q` behavior.
- [ ] M10.2c Add `[Q] Quit` to the visible hint/footer text on
      `wheel.py`, `reveal.py`, and `reading.py` (currently only some
      screens spell out their keys in a `Static(..., classes="keys")`
      line — `reading.py`'s hint line only lists `1`/`2`/`I`).
- [ ] M10.2d Regression test: from each of `WheelScreen`, `RevealScreen`,
      and `ReadingScreen`, press `q` via `Pilot` and assert the app exits.

### M10.3 — "r" (retry) — audit and fix

`ReadingScreen.action_retry` (`src/syzygy/tui/screens/reading.py`) and the
underlying `interpret_reading` (`src/syzygy/storage/reading_service.py`)
look correct on inspection, and the existing automated test
(`tests/tui/test_ritual_flow.py::test_failed_interpretation_retries_the_same_card`)
passes against a simulated `r` keypress. So this is not a straightforward
logic bug in the retry path itself — treat it as a live-repro task, not a
known fix.

- [ ] M10.3a Reproduce interactively (`syzygy tui`, a real terminal, a
      provider forced to fail — e.g. an intentionally-wrong API key via
      `syzygy model configure`) rather than only via `Pilot`, since
      `Pilot.press()` injects synthetic key events and can mask a
      terminal-driver-level input issue that a real keypress hits. Do this
      *after* M10.2 lands, in case both reports share one root cause
      (e.g. something eating single-letter keys screen-wide).
- [ ] M10.3b `action_retry` silently no-ops if
      `reading.status != ReadingStatus.INTERPRETATION_FAILED` — correct
      behavior (nothing to retry), but a silent no-op is easy to mistake
      for "the key doesn't work." Give it a visible response even when
      there's nothing to do (e.g. `self.app.bell()` or a one-line status
      flash), so a stray `r` press is never ambiguous with a broken
      binding.
- [ ] M10.3c `reading.py`'s hint line only ever shows
      `[1] ESOTERIC   [2] CONVENTIONAL   [I] INPUTS` — `[R] Retry` only
      appears in the panel body, and only in the failed state
      (`reading_panel.py`'s `_pending_text`). Make the hint line
      state-dependent so retry (and quit, per M10.2c) are discoverable
      the same way in every state, not just embedded in body copy.
- [ ] M10.3d Once a real cause is confirmed (or ruled out) in M10.3a, add
      a regression test for whatever was actually found — do not close
      this task on "the existing test already passes" alone.

### M10.4 — No in-TUI onboarding for a model provider

`syzygy model status|configure|use` (`src/syzygy/cli.py`) already do the
real work — provider selection persisted to `AppPaths.settings_path`, API
keys via the OS keyring (`interpretation/providers/api_keys.py`) — but
none of it is reachable from the TUI. A first-time user who never touches
the CLI gets silently defaulted to `FixtureProvider`
(`syzygy/tui/app.py::default_services`), with the fallback reason printed
only to stderr, which is invisible once the TUI has taken over the
terminal. `DESIGN.md` §13.3/§13.2 already scope what's available: local
`llama.cpp` (no key), OpenAI (API key), Anthropic (API key) — a fourth
`fixture` option always remains as the no-model default.

**Scoping note, worth being explicit about in the UI copy:** there is no
"log in with your ChatGPT/Claude subscription" flow to build here, and it
isn't a gap to fix — OpenAI and Anthropic don't expose their consumer
subscription auth (ChatGPT Plus, Claude Pro) to third-party apps at all.
The only credential either provider accepts from an app like Syzygy is a
separate, separately-billed API key. Label this screen "API key," not
"subscription," so it doesn't promise something that isn't possible.

- [ ] M10.4a New screen, e.g. `src/syzygy/tui/screens/model_setup.py`:
      list `fixture` (always available, "no model — canned copy"),
      `llama_cpp` (probe reachability at the default base URL the same
      way `syzygy model status` does, via
      `interpretation.providers.llama_cpp.probe`), `openai`, `anthropic`.
      For the latter two, an input for the API key (masked, same intent as
      `getpass` in the CLI's `_cmd_model_configure`) that calls the
      existing `api_keys.store_api_key` — no new key-storage logic.
      Selecting and confirming calls the existing
      `interpretation.providers.selection.save_selection` /
      `build_provider` — this screen is TUI plumbing around what
      `cli.py`'s `_cmd_model_*` functions already do, not new provider
      logic.
- [ ] M10.4b Entry points: a binding from `HomeScreen` (e.g. `[M] Model`)
      and from `WelcomeScreen`, plus surfacing *current* provider status
      somewhere reachable (mirrors `syzygy model status`'s output) so a
      user can tell whether they're on the fixture fallback and why.
- [ ] M10.4c First-launch nudge, not a gate: if `on_mount` in
      `SyzygyApp`/`WelcomeScreen` finds no saved selection and no stored
      key for either hosted provider, surface a one-line "no model
      configured — press [M] to set one up, or continue with sample
      readings" — never block profile creation or a reading on this,
      per `AGENTS.md`'s "the ritual still never requires a model
      configured."
- [ ] M10.4d Tests: `Pilot`-driven walk through selecting `llama_cpp` with
      a mocked-reachable probe, and selecting `openai`/`anthropic` with a
      fake key and asserting `store_api_key`/`save_selection` were called
      — no real network calls, no real keyring writes in the test suite
      (fixture the keyring backend the way `tests/interpretation/providers`
      already does, if it does).
