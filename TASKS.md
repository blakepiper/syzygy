# Syzygy — Task Checklist

Ordered, ID'd checklist. Check off (`- [ ]` → `- [x]`) as you complete each
task, and add a one-line note if you deviated from the plan. Dependencies
are noted inline; unless stated otherwise, tasks within a milestone are
sequential.

**M0–M9 (v0.1) are complete** — see `IMPLEMENTATION_PLAN.md` for that
history; it is not repeated here. This file now tracks a fresh batch of
bugs and gaps found in day-to-day use of v0.1, filed 2026-08-08.

**M10 is complete.** M11–M15 come from a second hands-on review of the
running app (`feedback.md`, filed 2026-08-08) plus the animation design
spec at `animation.md`. They are ordered so that each milestone unblocks
the next: fix what makes the app untestable (M11), settle the visual
language and screen layout (M12), fill the missing content surfaces
(M13), then animate a UI whose look and layout have stopped moving (M14),
and finally sound (M15). Do not start M14 before M12 lands — animating a
layout that is about to be redesigned is wasted work.

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

- [x] M10.1a `src/syzygy/geocoding.py` (or similar, mirroring the
      `syzygy.astrology` seam): given a free-text place label, return
      `(latitude, longitude, iana_timezone)`. Timezone is the
      **birthplace's** zone (needed to convert local birth time to UTC for
      the natal chart) — never the current-location zone; that keeps this
      consistent with the "no current-location astrology" invariant in
      `AGENTS.md`. Use `geopy` for the place → lat/long lookup and
      `timezonefinder` for lat/long → IANA name. Import both lazily inside
      the function, not at module load, so the rest of the app still runs
      without the `geocoding` extra installed.
- [x] M10.1b Wire it into the form phase: when the user fills in
      `place-label` and presses REVIEW with `latitude`/`longitude`/`timezone`
      still blank, run M10.1a and prefill those three fields *before*
      showing the confirm panel, clearly marked as auto-resolved. The user
      still reviews and can EDIT before CONFIRM — the existing two-phase
      form/confirm flow already provides that; this task only removes the
      requirement to type coordinates by hand. Manual entry must keep
      working exactly as today (leave lat/long/timezone as the override
      path) — do not make geocoding mandatory.
- [x] M10.1c Handle failure explicitly: extra not installed, no network,
      or no geocoder match — show an inline message on the form ("could
      not resolve a location for <place>; enter coordinates manually") and
      leave the manual fields open, per `DESIGN.md` §23. Never block
      profile creation on a geocoding failure.
- [x] M10.1d Run geocoding off the event loop (`@work(thread=True)`, same
      pattern `_calculate` already uses) — it's a network call.
- [x] M10.1e Tests: fake/mocked geocoder + timezone finder for determinism
      (no real network calls in the test suite); cover the prefill path,
      the manual-override path, and the failure path. Update
      `README.md`'s `pip install ".[geocoding]"` note if the UX changes
      what installing the extra actually turns on.
      Note: `README.md`'s existing wording already matched the shipped UX
      (prefill on blank coordinates), so no change was needed there.
      Also added a `[tool.mypy]` override in `pyproject.toml` skipping
      `numpy.*`/`timezonefinder.*` stub following - numpy's bundled stubs
      (pulled in transitively by `timezonefinder`) use 3.12+ `type`
      statement syntax that mypy can't parse under this project's py3.11
      target.

### M10.2 — "q" (quit) does not work on every screen

Confirmed by reading `src/syzygy/tui/screens/*.py`: `("q", "quit", "quit")`
is declared per-screen, and it's simply missing from four of them —
`profile_create.py`, `wheel.py`, `reveal.py`, and `reading.py`. There is no
app-level fallback (`SyzygyApp` in `src/syzygy/tui/app.py` declares no
`BINDINGS` of its own), so on those four screens `q` does nothing at all.
`reading.py` is the screen most readings end on, which is almost certainly
what was actually hit.

- [x] M10.2a Move the quit binding to `SyzygyApp` itself
      (`src/syzygy/tui/app.py`) as a single `BINDINGS = [("q", "quit",
      "quit")]`, so it applies everywhere by construction instead of being
      copy-pasted per screen. Remove the now-redundant per-screen entries
      in `welcome.py`, `home.py`, `chart.py`, `archive.py`,
      `profile_select.py`, `too_small.py`.
- [x] M10.2b Verify (via a test, not just reasoning) that a focused `Input`
      on `profile_create.py`'s form still accepts a literal `q` keystroke
      as text rather than quitting — Textual gives a focused widget's own
      key handling first refusal, so this should already hold, but assert
      it explicitly since this task is specifically about `q` behavior.
- [x] M10.2c Add `[Q] Quit` to the visible hint/footer text on
      `wheel.py`, `reveal.py`, and `reading.py` (currently only some
      screens spell out their keys in a `Static(..., classes="keys")`
      line — `reading.py`'s hint line only lists `1`/`2`/`I`).
      Note: `reading.py`'s hint line was also made state-dependent here
      (adds `[R] RETRY` when `INTERPRETATION_FAILED`) since M10.3c needed
      the same edit - see that task's note.
- [x] M10.2d Regression test: from each of `WheelScreen`, `RevealScreen`,
      and `ReadingScreen`, press `q` via `Pilot` and assert the app exits.
      Found and fixed a real bug surfaced by this test: `WheelWidget.on_key`
      (`src/syzygy/tui/widgets/wheel.py`) swallows every printable key as
      entropy input and calls `event.stop()` - including `q` - so it never
      reached the new app-level binding. `q` is now special-cased to bubble
      through unstopped; the entropy pool stays OS-random-primary
      (`DESIGN.md` 7.2) so this changes nothing about unbiased selection.

### M10.3 — "r" (retry) — audit and fix

`ReadingScreen.action_retry` (`src/syzygy/tui/screens/reading.py`) and the
underlying `interpret_reading` (`src/syzygy/storage/reading_service.py`)
look correct on inspection, and the existing automated test
(`tests/tui/test_ritual_flow.py::test_failed_interpretation_retries_the_same_card`)
passes against a simulated `r` keypress. So this is not a straightforward
logic bug in the retry path itself — treat it as a live-repro task, not a
known fix.

- [x] M10.3a Reproduce interactively (`syzygy tui`, a real terminal, a
      provider forced to fail — e.g. an intentionally-wrong API key via
      `syzygy model configure`) rather than only via `Pilot`, since
      `Pilot.press()` injects synthetic key events and can mask a
      terminal-driver-level input issue that a real keypress hits. Do this
      *after* M10.2 lands, in case both reports share one root cause
      (e.g. something eating single-letter keys screen-wide).
      Note: no interactive terminal was available in this environment, so
      this was reproduced through `Pilot` instead - but via a targeted
      probe rather than the existing passing test. `Pilot.press("R")`
      goes through the same Textual key-dispatch path a real terminal
      does (Textual reports a shifted letter as its own key, "R", not a
      modifier on "r"); it reproduced "retry does nothing" exactly, which
      is what a real terminal sends for that keystroke with Caps Lock on
      or Shift held. `ReadingScreen.BINDINGS` only ever matched lowercase
      `"r"` - not a "something eating single-letter keys" root cause
      shared with M10.2, a distinct case-sensitivity gap. Fixed by binding
      `"r,R"` to `action_retry`.
- [x] M10.3b `action_retry` silently no-ops if
      `reading.status != ReadingStatus.INTERPRETATION_FAILED` — correct
      behavior (nothing to retry), but a silent no-op is easy to mistake
      for "the key doesn't work." Give it a visible response even when
      there's nothing to do (e.g. `self.app.bell()` or a one-line status
      flash), so a stray `r` press is never ambiguous with a broken
      binding.
- [x] M10.3c `reading.py`'s hint line only ever shows
      `[1] ESOTERIC   [2] CONVENTIONAL   [I] INPUTS` — `[R] Retry` only
      appears in the panel body, and only in the failed state
      (`reading_panel.py`'s `_pending_text`). Make the hint line
      state-dependent so retry (and quit, per M10.2c) are discoverable
      the same way in every state, not just embedded in body copy.
      Note: implemented alongside M10.2c since both edit the same
      `#reading-keys` Static - see that task's note.
- [x] M10.3d Once a real cause is confirmed (or ruled out) in M10.3a, add
      a regression test for whatever was actually found — do not close
      this task on "the existing test already passes" alone.
      `tests/tui/test_retry.py` covers the case-sensitivity fix, the
      visible no-op (`bell()`), the state-dependent hint line, and that a
      read-only archive reopen never offers retry it would refuse.

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

- [x] M10.4a New screen, e.g. `src/syzygy/tui/screens/model_setup.py`:
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
      Note: `build_provider` requires a model id for `openai`/`anthropic`
      (raises `ProviderBuildError` without one), so the key form also
      collects a model id - `cli.py`'s `--model` flag has the same
      requirement, this just surfaces it as a second input instead.
- [x] M10.4b Entry points: a binding from `HomeScreen` (e.g. `[M] Model`)
      and from `WelcomeScreen`, plus surfacing *current* provider status
      somewhere reachable (mirrors `syzygy model status`'s output) so a
      user can tell whether they're on the fixture fallback and why.
      Implemented as a `#home-model-status` line on `HomeScreen` itself
      (refreshed on mount and on screen resume) in addition to the full
      status list inside `ModelSetupScreen` - both degrade to "say
      nothing" rather than crash if the `providers` extra isn't installed
      (`load_status` raises plain `ImportError` in that case, caught at
      both call sites; `syzygy doctor` already had this same guard around
      `_print_provider_status`, `default_services` does not - out of
      scope here, that call site is unchanged).
- [x] M10.4c First-launch nudge, not a gate: if `on_mount` in
      `SyzygyApp`/`WelcomeScreen` finds no saved selection and no stored
      key for either hosted provider, surface a one-line "no model
      configured — press [M] to set one up, or continue with sample
      readings" — never block profile creation or a reading on this,
      per `AGENTS.md`'s "the ritual still never requires a model
      configured."
- [x] M10.4d Tests: `Pilot`-driven walk through selecting `llama_cpp` with
      a mocked-reachable probe, and selecting `openai`/`anthropic` with a
      fake key and asserting `store_api_key`/`save_selection` were called
      — no real network calls, no real keyring writes in the test suite
      (fixture the keyring backend the way `tests/interpretation/providers`
      already does, if it does).
      Note: no interactive terminal was available in this environment to
      manually click through the finished screen, so verification is
      Pilot-only (`tests/tui/test_model_setup.py`, 9 tests) plus
      `ruff`/`mypy`/`syzygy doctor` - the same limitation noted in M10.3a.

### M10.5 — Display the bundled card artwork

- [x] M10.5a Bundle the 78 supplied PNG illustrations under
      `src/syzygy/resources/art/` and add Pillow + `rich-pixels` as runtime
      dependencies.
- [x] M10.5b Resolve each canonical deck id to its illustration and render
      it in `TarotCardWidget` on both reveal and reading screens, with the
      existing text/correspondence retained below the art.
- [x] M10.5c Verify every card has a real bundled image, the image renderer
      succeeds, and the built wheel contains all 78 PNGs.

---

## M11 — Unblock the app: bugs that prevent testing anything else

Everything in `feedback.md` downstream of this milestone is hard to
evaluate while profile creation, the model-setup screen, retry, and card
art are broken, and while there is no way to see a second card without
waiting a day. Do M11 first, in order.

### M11.1 — Profile creation is broken (blocks onboarding testing)

`feedback.md`: "I can't test the onboarding flow of setting up a local
model or OpenAI/Claude API key because profile creation is bugged." No
symptom was recorded, and the M10.1 geocoding work (`profile_create.py`
`_review` → `_resolve_birthplace` → `_finish_review`) is the most recent
change to that screen, so treat it as the prime suspect but reproduce
before assuming.

- [x] M11.1a Reproduce in a real terminal (`syzygy tui` → create profile),
      not only via `Pilot`, and write the exact symptom into this task
      before fixing anything. Specific things to check, in order: (1) is
      REVIEW reachable at all by keyboard — the form is `Input`s plus
      `Button`s with no `Enter`-submits-the-form handler and no key
      binding, so a user who never presses Tab has no way forward; (2)
      does `_review` hang with "Resolving …" forever when the `geocoding`
      extra is absent or the network is down (worker raising something
      other than `GeocodingUnavailable`/`GeocodingFailed` escapes the
      `except` in `_resolve_birthplace` and nothing re-enables the REVIEW
      button); (3) does `_collect`'s validation reject plausible input
      with a message the user can't see.
      **Reproduced, and the cause was none of the three predicted.** No
      interactive terminal is available in this environment, so the repro
      was a keyboard-only `Pilot` probe (the existing tests all assign
      `Input.value` directly and call `Button.press()`, which is exactly
      why they never saw it). Symptom: `ProfileCreateScreen` was the only
      interactive screen with no explicit focus on mount, so Textual's
      `AUTO_FOCUS = "*"` focused the first focusable node — the
      `VerticalScroll#profile-form` *container*, which is focusable by
      default. Everything typed before the user's first Tab went nowhere,
      and the first Tab then moved focus to `#display-name`, so **every
      field received the previous field's text**: the name held the birth
      date, the date held the time, the time held the birthplace, and the
      birthplace was empty. Validation then rejected it with a message
      naming the wrong field ("Birth date '14:22' is not an ISO date"),
      which is what made it look unfixable rather than merely misaligned.
      Prediction (1) was also true and fixed in M11.1b (ENTER did nothing
      from a field), but it was the secondary problem, not the cause.
      Separately: the `.venv` in this checkout had a **non-editable**
      install, so `pytest` was running against a stale copy in
      `site-packages` rather than `src/`. Reinstalled with
      `pip install -e ".[dev]"`; worth checking before trusting a green
      suite here.
- [x] M11.1b Fix the reproduced cause. If it is (1), add an explicit
      submit path — `Input.Submitted` on the last field and/or an
      `Enter`/`^S` binding on the screen — and make the focus order and
      the "press Tab / Enter" hint visible in the form's key line.
      Focus `#display-name` on mount and `can_focus=False` on the form
      container (it is a layout device, not a control, and it should not
      be in the tab ring at all). Added `on_input_submitted` so ENTER
      reviews from any field, a `[TAB] next field  [ENTER] review  [ESC]
      cancel` key line, and focus that follows the phase change — ENTER
      on the confirm panel confirms, EDIT returns focus to the first
      field — so ENTER always means "the primary action of what is on
      screen."
- [x] M11.1c Make the worker failure-proof regardless of which cause was
      found: catch `Exception` in `_resolve_birthplace`, always re-enable
      `#review`, and always replace the "Resolving …" text. A geocoding
      bug must never be able to strand the form (`DESIGN.md` §23,
      `AGENTS.md`: never block profile creation on geocoding).
      Also focuses `#latitude` on failure, putting the cursor where the
      work now is. ENTER is ignored while a lookup is in flight rather
      than queueing a second one behind it.
- [x] M11.1d Regression test for the actual reproduced failure, plus a
      `Pilot` test that walks profile creation end to end using only
      keyboard input (no `pilot.click`) — the existing TUI tests should be
      checked for whether they click their way past the very step a real
      user cannot reach.
      Six tests in `tests/tui/test_profile_create.py`, all keyboard-only
      (via `textual.keys._character_to_key`, so text arrives one key event
      at a time the way a terminal delivers it): initial focus, the
      field-shift regression, ENTER-reviews, a full empty-form → saved
      profile walk, ENTER ignored mid-lookup, and the transport-exception
      recovery from M11.1c.

### M11.2 — Delete a profile

`feedback.md`: "There is no way to delete a profile."
`syzygy.storage.profiles` has `insert_profile`/`get_profile`/
`list_profiles` and no delete; `ProfileSelectScreen` is list-and-pick
only.

- [x] M11.2a `delete_profile(conn, profile_id)` in
      `src/syzygy/storage/profiles.py`. Decide and document the fate of
      that profile's readings: readings are keyed by `profile_id`, so
      either cascade-delete them in the same transaction or refuse to
      delete a profile that has readings. Recommendation: cascade, inside
      one transaction, since a profile's readings are meaningless without
      its chart — but say so explicitly in the docstring, and check
      whether the `readings` foreign key in
      `src/syzygy/storage/migrations.py` already declares `ON DELETE
      CASCADE` (and whether `PRAGMA foreign_keys` is actually on in
      `database.py`) rather than assuming.
      Checked: `readings.profile_id` is a plain `REFERENCES profiles(id)`
      with **no** `ON DELETE CASCADE`, and `PRAGMA foreign_keys = ON` *is*
      set in `database.py::connect` — so a naive profile delete would have
      raised `IntegrityError`. Cascading in SQL here rather than adding
      the constraint: SQLite cannot add `ON DELETE CASCADE` to an existing
      table without rebuilding it, which is a far larger and riskier
      migration than two ordered statements, and it would bury a
      destructive behavior in schema metadata where no reader of
      `profiles.py` would see it. Readings are deleted first (foreign keys
      are on, so the order is load-bearing), inside an explicit
      `BEGIN`/`COMMIT` — connections are autocommit, same pattern as
      `knowledge.store.replace_source`. Returns the number of readings
      deleted; a missing profile is not an error. Added `count_readings`
      alongside it for the confirmation copy.
- [x] M11.2b TUI: `[D] Delete` on `ProfileSelectScreen` with a
      confirmation step that names the profile and the number of readings
      that will go with it. Deletion is destructive and irreversible —
      require an explicit confirm, never a single keypress.
      The confirm panel names the profile, its birth data, the reading
      count, and whether it is the active profile. **CANCEL takes focus,
      not DELETE** — a reflexive ENTER on a destructive prompt must not be
      what destroys the data; `escape` also cancels. `[D]` on an empty
      list rings the bell rather than opening a confirmation for nothing.
- [x] M11.2c Handle deleting the *active* profile: clear
      `SyzygyServices`/app state and route back to profile selection (or
      the welcome screen if no profiles remain) rather than leaving a
      dangling `self.syzygy.profile`.
      Added `SyzygyApp.clear_profile()`. Deliberately does *not*
      auto-select a survivor: which self is being read for is the user's
      choice, never a side effect of a deletion. Deleting the last profile
      switches to the welcome screen.
- [x] M11.2d CLI parity: `syzygy profile delete <id>` alongside the
      existing `profile create`/`list`, with a `--yes` flag for the
      non-interactive path.
      Interactive confirmation requires typing the profile's display name,
      not just "y" — it is the only irreversible command in the CLI.
- [x] M11.2e Tests: storage-level delete (with and without readings), the
      confirm-then-delete `Pilot` walk, and the active-profile-deleted
      state transition.
      6 storage tests (including atomicity when the second statement
      fails, via a connection proxy — `sqlite3.Connection.execute` is
      read-only and cannot be monkeypatched), 8 TUI tests
      (`tests/tui/test_profile_delete.py`), 4 CLI tests.

### M11.3 — `[M]` model setup: selecting llama.cpp does nothing

`feedback.md`: "User should be able to set up llama.cpp by pressing 'm'
… Right now it just says 'not reachable, no API key needed' so when you
select it nothing happens." Two distinct problems in
`src/syzygy/tui/screens/model_setup.py`: the row is *informational* about
a failed probe but offers no way to act on it, and selecting an
unreachable provider appears to silently do nothing.

**Reproduced (M11.3a).** Selecting `llama_cpp` with nothing listening
*did* save the selection and *did* write a confirmation — but: (1) the row
still read "not reachable" afterwards, so the state the user cared about
was unchanged; (2) `build_provider` never raises for `llama_cpp`
(unlike the hosted providers it has no key to check), so there was no
warning that readings would silently fall back to fixture; (3) the
confirmation landed at **y=30 inside a scrollable body on a 32-row
screen** — measured, not guessed — so on any smaller terminal it was
below the fold; and (4) most importantly there was nothing to *act on*:
no way to point at a different URL, no way to re-probe after starting a
server, and no hint how to start one. "Nothing happens" was a fair
description.

- [x] M11.3a Make the llama.cpp row actionable: show the base URL being
      probed, let the user edit it (an `Input`, same shape as the API-key
      form), re-probe on demand (`[P] Probe again`), and persist the
      chosen base URL wherever `interpretation.providers.llama_cpp` reads
      it from — check whether that is currently hardcoded and, if so, add
      it to the settings file (`AppPaths.settings_path`, never the
      readings database, per the existing selection module's rule).
      Checked: not hardcoded — `ProviderSelection.base_url` already exists
      and `build_provider` already honours it, and the CLI already has
      `model use --base-url`. The gap was TUI-only, so this adds no new
      persistence, just the form (`#llama-form`) that reaches the existing
      field. Only a *non-default* URL is persisted, so settings never pin
      a default that may move.
      Note on `[P]`: it is a screen binding, so it fires from the provider
      list but **not** while a form `Input` has focus — a focused input
      gets first refusal on every printable key (the same rule that lets a
      literal "q" be typed into a form field, M10.2b). The form therefore
      offers a PROBE button and ENTER-in-the-URL-field instead, and the
      "press [P] to probe again" copy appears on the list view, where it
      works. Tested both ways.
- [x] M11.3b Make selection produce visible feedback in every outcome:
      selected-and-reachable, selected-but-unreachable (allowed — the
      server may start later; say so), and build failure. `_select_local_provider`
      must never return without changing something on screen.
      Selecting now re-probes and says which of the two situations the
      user is in, naming the URL. `#model-message` was also **moved out of
      the scrolling body** so the confirmation is always on screen —
      verified at both 80×24 (y=20) and 100×32 (y=28). A confirmation
      nobody can see is indistinguishable from a dead key.
- [x] M11.3c Add actionable copy for the unreachable case: the exact
      command to start a llama.cpp server and the URL Syzygy expects, so
      "not reachable" tells the user what to do rather than only what is
      wrong.
      `LLAMA_CPP_HELP` gives the `llama-server -m … --port 8080` line and
      notes any OpenAI-compatible `/v1` endpoint works; shown only while
      unreachable, hidden once a server answers. The row itself now names
      the URL it probed.
- [x] M11.3d Tests: `Pilot` walk selecting `llama_cpp` with the probe
      mocked both reachable and unreachable, asserting `save_selection`
      was called and that the screen says something different in each
      case; plus a test for a persisted custom base URL round-tripping
      through settings.
      14 new tests in `tests/tui/test_model_setup.py` (23 total). Two
      robustness fixes fell out of writing them: a malformed base URL made
      `httpx` raise *before* any request, which took down the whole status
      load — `probe_llama_cpp` now treats "could not even try" as "not
      reachable", with a broad catch in `_refresh_status` as a backstop —
      and `#model-message` needed `markup=False`, since Rich was eating
      the literal "[P]" out of its own instructions.

### M11.4 — `[R]` retry still does not work

`feedback.md`: "'r' to retry still seems to not work" — M10.3 fixed a
case-sensitivity gap (`"r,R"`) and added `tests/tui/test_retry.py`, and
those tests pass, so the remaining failure is something the M10.3 probe
did not model. M10.3a was closed without a real-terminal repro (no
interactive terminal was available); that gap is the thing to close here.

**Root cause found — it was M11.4b, and M10.3's fix was unrelated to it.**
A reading can be persisted as `INTERPRETING` and then abandoned: the row
is written by `begin_interpreting` *before* the provider call, so any
process that stops between those two points (quit, crash, closed
terminal) leaves it there permanently. In that state
`ReadingScreen.on_mount` skipped starting interpretation (`status in
(COMPLETE, INTERPRETING)`) *and* `action_retry` refused (`status !=
INTERPRETATION_FAILED`), so the screen showed "INTERPRETING…" forever,
with a spinner that wasn't running, no `[R] RETRY` in the hint line, and
an `r` key that only rang the bell. Since it is the canonical reading for
that date, there was no way out for the rest of the day.

The route there is a direct consequence of M11.3: select llama.cpp with
no server running, start a reading, wait out part of the provider's
**120-second** timeout, give up, quit. Reproduced with a scripted probe
(`INTERPRETING` persisted, screen reopened) — no interactive terminal is
available in this environment, the same limitation noted in M10.3a.

- [x] M11.4a Reproduce in a real terminal with a provider forced to fail
      (`syzygy model configure` with a deliberately wrong API key), and
      record the observed behavior precisely: does the key do nothing at
      all, does the panel flash and revert, or does retry run and fail
      again with the same error (which would be *correct* behavior with a
      still-wrong key, and a copy problem rather than a binding bug)?
      A *wrong API key* turns out to be the case that already worked: the
      provider raises, `interpret_reading` catches it, and the row lands
      on `INTERPRETATION_FAILED` with retry offered (asserted in M11.4b's
      test). The broken case is an *interrupted* call, not a failed one.
- [x] M11.4b Check the states `action_retry` refuses. It no-ops unless
      `status == INTERPRETATION_FAILED`; confirm the reading actually
      reaches that status on a provider error rather than staying in
      `INTERPRETING` (e.g. a worker exception that never writes the failed
      state through `reading_service`), which would make retry
      permanently unavailable while the panel shows a failure.
      This was the bug, in the form the task predicted but by a different
      mechanism — not an exception escaping, but a process ending. Fixed
      by distinguishing "a call of *ours* is in flight" (a new
      `_interpreting` flag on the screen) from "the row says
      `INTERPRETING`": the latter without the former is an interrupted
      reading, which now renders as "INTERPRETATION WAS INTERRUPTED" and
      is retryable. `interpret_reading` already resumed such a row
      correctly — with status `INTERPRETING` it skips `begin_interpreting`
      and calls the provider — so no storage or state-machine change was
      needed.
- [x] M11.4c Verify the retry path re-runs interpretation *without*
      redrawing the card — the `ALLOWED_TRANSITIONS` invariant in
      `syzygy.domain.reading` — and that a second failure leaves the
      reading retryable again rather than in a terminal state.
      Both asserted. `INTERPRETATION_FAILED -> INTERPRETING` is a legal
      transition and the card id is unchanged across every retry path
      tested, including the interrupted one.
- [x] M11.4d Show retry progress: while a retry is in flight the panel
      must say so (this pairs with M14's `processing-start`/`stop`
      events), and a completed retry must visibly replace the error.
      The in-flight state is now checked *before* the stored status in
      both the title and the panel body — a running retry still reads as
      `INTERPRETATION_FAILED` in storage until the call returns, so
      without that ordering the screen showed a failure while working.
      `[R] RETRY` is withdrawn from the hint line while a retry runs, so a
      second press cannot stack a concurrent provider call.
- [x] M11.4e Regression test for whatever M11.4a–b actually turns up. As
      in M10.3d, do not close this on "the existing tests pass."
      6 new tests in `tests/tui/test_retry.py` (10 total): the stranded
      reading is retryable and keeps its card, it says "interrupted" not
      "in progress", a read-only archive reopen still offers no retry, an
      in-flight retry shows progress and refuses a second concurrent call,
      a provider error really does land on `INTERPRETATION_FAILED` in
      storage, and a second failure stays retryable.

### M11.5 — Card art does not display correctly

`feedback.md`: "Tarot card art in the terminal does not display
correctly." `src/syzygy/tui/widgets/card_art.py` renders via
`rich_pixels.Pixels.from_image(image, resize=size)` half-blocks, and its
own docstring says the on-screen size was left to be revisited "once
styling work starts" — this is that task.

- [x] M11.5a Record the actual defect first (screenshot or description):
      wrong aspect ratio, art squashed into too few rows, colors washed
      out, art overlapping the text below it, or nothing rendering at all.
      Terminal cells are roughly 1:2, and `resize=size` takes (columns,
      rows) — a naive square resize will look stretched.
      **The art was squashed to half its height.** Measured: the fixed
      `ART_SIZE = (22, 17)` renders as 22 columns × **9** cell rows,
      because `resize` is in *image pixels* and `HalfcellRenderer` packs
      two image rows into each cell row. Delivered aspect 17/22 = 0.77
      against a source of ~1.54 — an exact factor of two.
      The cause is a double correction. A cell is ~2× taller than wide
      *and* holds 2 stacked image pixels, so an image pixel is already
      about square on screen and the source ratio can go into `resize`
      directly. Correcting for the cell ratio on top of that halves it.
- [x] M11.5b Fix sizing: compute the render size from the widget's actual
      cell dimensions and the source image's aspect ratio, accounting for
      the 1:2 cell ratio and for `HalfcellRenderer` packing two image rows
      per cell row. Re-render on resize rather than caching one fixed size
      (`render_card_pixels`'s `@cache` is keyed on size, so this is a call
      -site change, but check the cache cannot grow unbounded across many
      resize steps).
      `art_size_for(card_id, columns, cell_rows)` searches downward from
      the widest allowed width and derives the height from the source
      ratio each time, so the ratio is never traded away to make something
      fit — if nothing fits, it returns `None` and the caller shows text.
      Widths are quantised to even columns and capped at
      `MAX_ART_COLUMNS`, so dragging a terminal edge cannot decode the PNG
      once per column crossed or fill the cache with near-identical
      entries.
- [x] M11.5c Give the art a stable frame: a fixed aspect-ratio box so the
      card does not reflow the surrounding text as the terminal resizes,
      and a graceful degradation path when the pane is too small to show
      art at all (fall back to the existing text card — this connects to
      the not-yet-implemented "terminal too small" state).
      `#reveal-card`/`#reading-card` now have explicit heights (with
      `-compact` variants) rather than `height: auto` — a card that sizes
      its art from its own box cannot also size its box from that art.
      Two related bugs fell out: the widget rendered its content in
      `__init__`, before `Widget.__init__` had run, so reading `self.size`
      there raised; and the text block's row count was assumed rather than
      measured, so a wrapping correspondence label ("MERCURY in VIRGO
      20°-30°") let the art push the card's own words out of the box —
      verified against all 78 cards, previously 30+ overflowed.
- [x] M11.5d Check the art renders correctly on both `RevealScreen` and
      `ReadingScreen`, in truecolor and 256-color terminals, and note in
      the task which terminals were actually checked.
      Checked on both screens at 80×24, 100×32 and 140×45 through
      `Pilot` — delivered aspect 1.50–1.58 against sources of ~1.49–1.56
      at every size. **Not checked in a real terminal, truecolor or
      256-color**: no interactive terminal is available in this
      environment (the M10.3a limitation). The colour-depth question is
      untouched by this task either way — `rich-pixels` emits the same
      ANSI it always did; only the geometry changed.
      One honest tradeoff to note: at the 80×24 floor the *reading*
      screen's card now declines to draw art at all (7 cell rows left
      after the text, below what any legible size needs) and shows the
      text card. That is the correct call for the current layout rather
      than a squashed smear; M12.5 should give it more room.
- [x] M11.5e Tests: assert the computed render size preserves the source
      aspect ratio within a cell of tolerance across several widget sizes,
      and that a too-small widget falls back to text instead of raising.
      `tests/tui/test_card_art.py`, 25 tests: aspect preserved across 7
      box sizes for all 78 cards, never exceeds its box, declines rather
      than squashing when too short or too narrow, is capped when given a
      huge box, the renderer really produces the cell rows the arithmetic
      assumes, widths quantise, no card overflows the widget, a tiny
      widget renders the text card, and one test pinning the old `(22,17)`
      as a ratio failure so the regression cannot come back quietly.

### M11.6 — Dev-only reroll (testing affordance)

`feedback.md`: "let's create a 'reroll' function in the main display that
allows the user to reroll today's card and recalculate the reading. So
that I can test the animation over and over again."

**This is in direct tension with a core invariant** — `AGENTS.md`: "the
card is committed to storage immediately after the draw, before any LLM
call. A failed or retried interpretation must never redraw the card," and
"one canonical reading per `(profile_id, consultation_local_date)`,
enforced by the database." The requested capability is still worth having
for development, but it must be built as an explicit *destructive dev
tool*, not as a ritual action, and it must not weaken the state machine
or the `UNIQUE` constraint.

- [x] M11.6a Implement reroll as *delete today's reading row, then draw a
      fresh one through the normal path* — never as an in-place card
      mutation, and never by relaxing `ALLOWED_TRANSITIONS` or the
      `UNIQUE` constraint. The existing draw path stays the only way a
      card is ever chosen.
      `syzygy.dev.discard_todays_reading` deletes the row and nothing
      else; callers then run the ordinary `draw_todays_reading`. No
      storage, state-machine, or schema change was needed. The module
      docstring states the invariants and why this keeps them, so the
      next reader doesn't have to re-derive it.
- [x] M11.6b Gate it behind an explicit dev switch (an env var such as
      `SYZYGY_DEV=1`, and/or a `syzygy dev reroll` CLI subcommand
      alongside `dev deck`/`dev astrology`). With the switch off, the
      binding must not exist and the key must do nothing — a normal user
      must not be able to reach it by accident.
      Both: `SYZYGY_DEV` (read at call time, not import time) plus
      `syzygy dev reroll --profile-id --yes`. Three independent gates —
      the TUI never binds the key, the CLI refuses before touching the
      database, and `discard_todays_reading` itself raises — so no single
      oversight exposes it.
- [x] M11.6c TUI binding on `HomeScreen` (dev mode only), visibly labelled
      as a dev action (e.g. `[X] DEV: reroll today`) and confirming before
      it destroys the existing reading, since it discards a real
      interpretation.
      Bound at runtime in `on_mount` rather than declared in `BINDINGS`,
      so with the switch off the binding genuinely does not exist and the
      footer never advertises it. Confirmation names the card being
      destroyed and says it is a development affordance; CANCEL holds
      focus. Interactive CLI confirmation requires typing `reroll`.
- [x] M11.6d Tests: reroll produces a new draw and leaves exactly one row
      for that `(profile_id, date)`; reroll is absent/inert with the dev
      switch off; the state machine and constraint are untouched (assert
      the `UNIQUE` constraint still rejects a duplicate insert).
      21 tests in `tests/test_dev.py` (switch parsing, the refusal, the
      delete, exactly-one-row across four rerolls, the `UNIQUE` constraint
      still rejecting a duplicate insert, other days/profiles untouched),
      5 TUI tests in `tests/tui/test_navigation.py`, 3 CLI tests. The
      "new card" assertion checks a fresh entropy digest rather than a
      different card id — two draws may legitimately land on the same
      card, and asserting otherwise would be pinning the RNG — with a
      separate test over 11 rerolls for the outcome the user cares about.

---

## M12 — Visual identity and use of space

`feedback.md` items 5, 6, 10, 11, 18, 20. Land this before M14: the
animation work in M14 targets these layouts, and redesigning under
finished animations means doing both twice.

### M12.1 — Retire the gold accent for white

`feedback.md`: "Everywhere that is currently piss yellow in the TUI
should be switched to white." That is `$syz-gold: #cf9b3f` in
`src/syzygy/tui/syzygy.tcss` (9 usages).

- [x] M12.1a Repoint the accent to white/bone in the palette block rather
      than editing the 9 call sites — keep a single named variable so the
      accent stays changeable in one place. Decide whether `$syz-gold`
      becomes pure `#ffffff` or the existing `$syz-bone` (`#e6ddc9`);
      recommendation is a true white for the accent and `$syz-bone` for
      body text, so the accent still reads as *brighter* than normal text
      rather than merging with it. Rename the variable to something
      non-color-specific (`$syz-accent`) while doing it.
      `$syz-accent: #ffffff`, taking the recommendation.
- [x] M12.1b Sweep for hardcoded gold/yellow outside the stylesheet —
      Rich markup in Python strings (`[gold]`, `[yellow]`, `[#cf9b3f]`)
      in `screens/` and `widgets/` — not just the TCSS file.
      Three more golds were hiding in Python (`tarot_card.py`,
      `reading_panel.py`, `wheel.py`), and in fact the *whole* palette was
      duplicated as hex literals across four widget modules — TCSS
      variables are unreachable from a Rich `Style`. Rather than
      find-and-replace them, added `syzygy.tui.palette` as the single
      Python source and pointed all four at it. That is why the gold
      would otherwise have survived being "removed": the stylesheet was
      never where those widgets got their colour.
- [x] M12.1c Check contrast on `$syz-field`/`$syz-panel` backgrounds and
      confirm the accent still distinguishes itself from `$syz-bone` body
      text after the change; adjust `$syz-muted`/`$syz-dim` if the
      hierarchy collapses.
      `tests/tui/test_palette.py` asserts the luminance ordering holds
      (accent > bone > muted > dim > field), that the two palette copies
      agree, that no widget hardcodes a colour any more, and that no
      `$syz-*` variable exists on one side only — so the next colour
      change cannot half-land the way this one would have.

### M12.2 — Logo and mascot

`feedback.md`: "Use our logo.svg in the app" and "We now have a
mascot.png that we need to incorporate." The repo root has `logo.svg`,
`logo-dark.svg`, `logo-light.svg` (tracked) and `mascot.png` (untracked),
all outside the package.

- [x] M12.2a Move the assets into the package
      (`src/syzygy/resources/brand/`) so they ship in the wheel, the same
      way `resources/art/` does, and load them via `importlib.resources` —
      never a repo-relative path. `mascot.png` is untracked today; add it
      to the git index as part of the move.
      The mascot was also keyed to transparency (its opaque black field
      would render as a near-black rectangle over `$syz-field`) and
      downscaled 839×1348 → 420×675: `pixel_art.MAX_COLUMNS` means a
      terminal can never ask for more than ~40×64 pixels of it, and the
      full-resolution file was 740 KB in every wheel. Regeneration is
      documented in `docs/BRAND_ASSETS.md`.
- [x] M12.2b Render the logo in the TUI. A terminal cannot display SVG:
      either pre-rasterize `logo.svg` to a PNG at build/author time and
      render it through the existing `rich_pixels` path (same technique as
      card art, reuse `card_art.py`'s renderer rather than writing a
      second one), or hand-author an ASCII/Unicode wordmark derived from
      the logo. Recommendation: rasterized PNG for the welcome/startup
      screen, ASCII wordmark for the persistent title bar — the title bar
      is too short for pixel art. Pick one per surface and say which.
      Note the light/dark variants exist; choose based on the terminal
      background if detectable, otherwise ship the dark-background one.
      Took the recommendation: rasterized PNG on the welcome screen,
      ASCII wordmark kept for one-row contexts and as the too-small
      fallback. Used `logo-dark.svg` (light-on-transparent) rasterized
      with `rsvg-convert -b none` — fully transparent pixels render as
      blank cells with no background, so the terminal's own background
      shows through and the light/dark question mostly answers itself.
      "Reuse the renderer" turned into extracting one: the sizing
      arithmetic and cache moved to `syzygy.tui.widgets.pixel_art`, which
      `card_art` now delegates to. Two copies of that arithmetic is
      exactly how one of them ends up wrong (see M11.5).
- [x] M12.2c Place the mascot deliberately rather than decoratively:
      candidate homes are the welcome/startup screen (M14.2), an idle
      corner on `HomeScreen`, and the "waiting for interpretation" state.
      Do not put it where it competes with the card art.
      Welcome screen only, beside the copy — it is the one screen with
      nothing else to look at, and it never shares a screen with card
      art. Hidden at the compact floor, where its 22 columns are worth
      more to the text. Deliberately *not* on `HomeScreen` or the waiting
      state: both are about to be redesigned in M12.5/M14, and a mascot
      placed now would be placed against a layout that is changing.
- [x] M12.2d Verify the wheel/sdist actually contains the brand assets
      (same check M10.5c did for the 78 PNGs).
      Built the wheel: 78 card PNGs, both brand PNGs, `thoth_deck.yaml`
      and `syzygy.tcss` all present. Tests read the assets through
      `importlib.resources` rather than the filesystem, which is what has
      to work from a zipped install.

### M12.3 — Typography: Cinzel

`feedback.md`: "Change the font to Cinzel."

**Constraint worth stating up front:** a TUI cannot set the terminal's
font — the font is the terminal emulator's, and no escape sequence lets
an application change it. So this task cannot be "switch the app to
Cinzel"; it can be the three things that are actually achievable.

- [ ] M12.3a Bundle a Cinzel-derived display treatment for the places
      where letterforms carry the brand — the wordmark, screen titles,
      the welcome screen — as pre-rendered pixel art (rasterize Cinzel
      text to PNG at author time, render via the `rich_pixels` path) or as
      a hand-tuned ASCII display face. This gets the *look* of Cinzel
      where it matters without pretending to change the terminal font.
      Cinzel is SIL Open Font License 1.1 — permissive, so AGPL-compatible
      per `AGENTS.md`'s dependency rule; record that in the task and, if
      the font file itself is bundled, include its license file.
- [ ] M12.3b Everything else stays in the terminal's own monospace font —
      body copy, chart tables, and card correspondences must stay
      column-aligned, and Cinzel is proportional. Do not attempt pixel-art
      body text.
- [ ] M12.3c Document the recommendation for users who want more: a
      `README.md` note that the intended look pairs Syzygy with a terminal
      configured for a specific font, since that is the user's setting to
      make, not the app's.

### M12.4 — Bigger wheel glyphs

`feedback.md`: "The astrological symbols that rotate around in the wheel
animation are too small — make them larger."

- [x] M12.4a In `src/syzygy/tui/widgets/wheel.py`, the rim glyphs are
      single characters placed one per cell (`place(glyph_x, glyph, lit)`
      around a radius derived from the widget size). Make each rim symbol
      occupy a multi-cell block instead: either a small hand-authored
      2×2/3×3 Unicode block per zodiac sign, or the same `rich_pixels`
      technique used for card art if per-sign artwork exists. Keep the
      2:1 horizontal stretch already applied (`2 * radius * cos`) so the
      rim stays circular.
      Neither of the two suggested routes: per-sign pixel art at 3×3 cells
      is 3×6 pixels, far too coarse for a recognisable zodiac symbol, and
      hand-authored block mosaics have the same problem. What was actually
      wrong is visible in a rendered frame — the glyphs were single specks
      *camouflaged among the rim dots*. Each sign is now a three-cell
      cartouche `(♈)` with its three-letter name on the row below, which
      triples the footprint and, more usefully, makes the rim readable.
      The 2:1 stretch is unchanged.
- [x] M12.4b Scale with the widget: at small terminal sizes fall back to
      the current single-cell glyphs rather than overlapping neighbours.
      Compute how many cells of arc each symbol has available and pick the
      largest representation that fits.
      Three tiers off the available arc (`2 * radius * 2π/12`): bare glyph
      below 6 cells, cartouche from 6, cartouche plus name from 9.
- [x] M12.4c Give the wheel more of the screen while doing this — see
      M12.5; it is the main animated object on its screen and should be
      sized like it.
      **Deferred to M12.5** rather than done here. The wheel already takes
      `1fr` of its screen; making it larger means changing what shares
      that screen, which is the layout pass, not this task. At 110×36 the
      widget is already 110×27.
- [x] M12.4d Tests: rim symbols never overlap at any widget size ≥ the
      minimum, and the small-size fallback engages instead of clipping.
      Stated as something observable rather than as geometry: an
      overlapping symbol gets partly overwritten and its glyph disappears
      from the frame, so the test asserts all 12 appear exactly once —
      across 5 widget sizes × 4 rotation phases. Plus one test per tier,
      and one that every name has its glyph.

### M12.5 — Make the layout use the space

`feedback.md`: "The current TUI does not make intelligent use of the
space — the display feels largely empty. When thinking about the
animations … factor that in." This is the layout half of the same
problem M14 solves in motion, and it must come first.

- [ ] M12.5a Audit each screen at a few real terminal sizes (80×24,
      120×40, and a full-screen modern terminal) and record where the dead
      space actually is. `HomeScreen` is the priority — it is a title, a
      name, three anchor glyphs, a sky line, three badges, two status
      lines, and a button, stacked in a column down the middle.
- [ ] M12.5b Redesign `HomeScreen` around the space: a multi-column layout
      (SELF / COSMOS / CHANCE as parallel regions rather than a stack)
      that fills width, with the chart anchors and today's transits given
      room to breathe, and the primary action anchored where it reads as
      the focal point. Keep the SELF+COSMOS+CHANCE triad legible — it is
      the product's mental model, not decoration.
- [ ] M12.5c Do the same pass on `ReadingScreen` and `RevealScreen`, where
      card art (M11.5) now competes with body text: give the art a real
      column and let the interpretation flow beside it at wide sizes,
      stacking only when narrow.
- [ ] M12.5d Define responsive breakpoints once, in `syzygy.tcss`, and
      apply them consistently rather than per-screen ad hoc sizing. Note
      the widths chosen so M14 and the future "terminal too small" state
      use the same thresholds.
- [ ] M12.5e Snapshot-style tests at the chosen breakpoints (Textual's
      `Pilot` with an explicit terminal size) so a later layout change
      cannot silently re-empty the screen.

---

## M13 — Missing content surfaces

`feedback.md` items 8, 9, 17. All three add things the user can *read*;
they depend on M12's layout only loosely, but the new screens should be
built to the M12.5 breakpoints rather than the old stacked layout.

### M13.1 — Today's cosmos (daily horoscope) screen

`feedback.md`: "There needs to be a function from the main menu to view
today's 'cosmos' horoscope, in a similar way that the user can press 'c'
to view their natal chart."

- [ ] M13.1a New `src/syzygy/tui/screens/cosmos.py`, modelled on
      `screens/chart.py`: a full view of today's sky against the natal
      chart. The data already exists — `rank_current_transits`
      (`syzygy.storage.reading_service`) is what `HomeScreen._load_sky`
      calls and then truncates to three badges. This screen shows the full
      ranked set with orbs, applying/separating, and the natal point each
      transit touches.
- [ ] M13.1b Binding from `HomeScreen` — `[C]` is taken by chart, so use
      `[T] Today` or `[S] Sky`; pick one and add it to the visible key
      line. Keep `[Q]` and `[Esc]` behavior consistent with the other
      secondary screens.
- [ ] M13.1c Respect the invariants: no current-location astrology (no
      current lat/long, houses, Ascendant, or Midheaven — only the natal
      chart uses birthplace), and ranking stays in
      `syzygy.astrology.ranking`, not in the screen. The screen displays a
      ranking it is handed; it must not compute significance itself.
- [ ] M13.1d Calculate off the event loop (`@work(thread=True)`, the
      pattern `HomeScreen._load_sky` already uses) and handle failure
      visibly rather than silently.
- [ ] M13.1e Tests: the screen renders the ranked transits it is given,
      handles the no-profile and calculation-failed states, and does not
      reach for a current location.

### M13.2 — LLM summaries for the chart and the daily cosmos

`feedback.md`: "Both natal chart and the daily horoscope should have an
LLM summary that the user can read."

- [ ] M13.2a Decide and write down the storage model before coding: a
      natal-chart summary is stable for the life of a profile (generate
      once, cache on the profile), while a cosmos summary is per-day
      (cache per `(profile_id, local_date)`). Neither is a *reading* —
      they must not create rows in `readings`, must not consume or affect
      the daily card, and must never be able to trigger a draw. Add
      whatever storage they need as a new append-only migration in
      `syzygy.storage.migrations` (never edit a merged migration).
- [ ] M13.2b Extend the interpretation layer properly rather than calling
      a provider ad hoc: these are new prompt kinds in
      `syzygy.interpretation.prompts` with their own versioned contract,
      fed by the existing context builder. `InterpretationContext` is the
      entire input surface a provider sees (`AGENTS.md`) — if a summary
      needs a fact, add it to the context builder's output; a provider
      must not reach into the database or the astrology engine.
- [ ] M13.2c Both summaries must degrade the same way readings do: with no
      model configured, `FixtureProvider` supplies canned copy and the
      screens still work. Nothing here may become a hard model dependency.
- [ ] M13.2d UI: summary appears on `ChartScreen` and the M13.1 cosmos
      screen, generated on demand (a key press) rather than automatically
      on every open — an automatic call would mean a paid API request
      every time someone glances at their chart. Show a processing state
      while it runs and a retryable error state if it fails, reusing
      whatever M11.4d establishes.
- [ ] M13.2e Tests: prompt-contract schema validation, the cache-hit path
      (a second open makes no provider call), the fixture-fallback path,
      and that no `readings` row is created by either summary.

### M13.3 — Ship the processed knowledge sources

`feedback.md`: "Let's process the knowledge sources (the three books) and
include them as committed artifacts in the repo that all users get
(should be in machine readable, non-pdf form)." Today `syzygy knowledge
ingest` runs per-user against PDFs that `.gitignore` excludes
(`docs/*.pdf`), so a fresh clone has an empty knowledge base — the
ingestion pipeline exists (`syzygy.knowledge.ingest`/`store`) but nobody
gets its output.

- [x] M13.3a **Confirm the redistribution question with the user before
      committing anything.** `.gitignore`'s own note says derived data
      (chunks, FTS index) is fine to commit while the raw PDFs are not —
      but chunked full text of three in-copyright books is, in substance,
      the books. The tier policy in `docs/KNOWLEDGE_SOURCES.md` and the
      AGPL license make this a decision to take deliberately, not a
      detail. Options to put to the user, cheapest first: (1) ship only
      derived non-reproducible artifacts (embeddings/vectors and citation
      metadata, no verbatim text); (2) ship short quoted excerpts only,
      under a documented length cap; (3) ship full chunk text. Record the
      answer in an ADR under `docs/adr/` — this is exactly the kind of
      deviation that directory exists for.
      **User chose option 1** (2026-08-08): vectors and citation metadata
      only, no verbatim text. Recorded in
      `docs/adr/0003-ship-derived-knowledge-index-without-source-text.md`
      (0002 was already taken by the PyMuPDF license review). The
      too-permissive wording in `.gitignore` and
      `docs/KNOWLEDGE_SOURCES.md` was corrected, and `AGENTS.md` gained
      the rule as an invariant.
- [x] M13.3b Build the artifact in whatever form M13.3a settles on, as a
      committed, versioned file under `src/syzygy/resources/knowledge/`
      so it ships in the wheel and reaches every user. Keep it a *build
      product of the existing pipeline* — a script that runs
      `syzygy.knowledge.ingest` against the PDFs and emits the artifact —
      not a hand-maintained file that can drift from the parser.
      `syzygy knowledge build-artifact` reads an ingested database and
      writes `index.json` (290 citations, 131 KB, sorted and readable so a
      reviewer can confirm there is no prose in it) plus `vectors.npy`
      (290 × 256 float32, 297 KB). All 78 cards are covered in all three
      sources.
      One thing had to be sanitised: two section headings were
      segmentation artifacts that had swept up a sentence of Crowley's
      prose, which would have put verbatim text into the artifact through
      the `title` field. `normalize_title` recovers the real heading or
      truncates, and a test asserts no title is prose-shaped.
- [x] M13.3c Load it at first run: on a fresh database, populate
      `knowledge_chunks` (and the FTS index) from the bundled artifact
      instead of requiring `syzygy knowledge ingest`. Keep the existing
      ingest command working as the path for re-ingesting from a local PDF
      — it must stay possible to regenerate, and the Tier 0/Tier 1 rules
      in `AGENTS.md` are unchanged: `docs/book_of_thoth.pdf` remains the
      only canonical source, and nothing here may modify
      `thoth_deck.yaml`.
      `open_database` installs it for any source the database has not
      seen. Not the FTS index: it indexes text, and there is none — FTS
      search correctly returns nothing on a citation-only install.
      **Found and fixed a bug this created:** the artifact records the
      same `file_hash` and `ingestion_version` a real ingest would, so
      `ingest`'s idempotency check reported "already ingested" and did
      nothing — the very first thing a user with their own PDF would try
      was a silent no-op. It now also requires that the existing source
      actually has text (`store.has_full_text`).
- [x] M13.3d If the chosen artifact includes embeddings, pick the
      embedding model deliberately and record it: it must be
      AGPL-compatible, and it must not add a hosted-service dependency or
      a vector database (`AGENTS.md` forbids both) — a small local model
      producing vectors committed to the repo, queried with plain numpy,
      is the shape that fits. Retrieval stays in
      `syzygy.knowledge.retrieve` beside the existing FTS path.
      **No model at all**, which is the version of that with the fewest
      moving parts: `syzygy.knowledge.embedding` is the signed hashing
      trick over stop-worded tokens with sublinear TF, in pure numpy.
      Named honestly as a *hashed lexical signature* rather than an
      embedding — it finds shared vocabulary, not shared meaning. A real
      sentence model has to run at query time as well as build time, which
      would make torch a runtime dependency of a local-first terminal app
      for 290 short documents. `numpy` (BSD-3) becomes an explicit runtime
      dependency; it was already transitive via Pillow and
      `timezonefinder`. `retrieve.search_vectors` sits beside the FTS
      path, exposed as `syzygy knowledge search`.
- [x] M13.3e Tests: a fresh database self-populates from the bundled
      artifact; retrieval returns hits with correct citations without any
      PDF present; the artifact is present in the built wheel; and the
      generator script reproduces the committed artifact byte-for-byte
      from the same inputs (so it can be audited).
      31 tests in `tests/knowledge/test_artifact.py`, including
      `test_the_committed_index_contains_no_prose`, which enforces the ADR
      mechanically rather than by review. Byte-for-byte reproducibility
      was verified twice: as a test, and by re-ingesting all three PDFs
      into a completely separate database and diffing both files against
      the committed ones (identical). Wheel checked by hand — both files
      present, 23.3 MB total.
      Also fixed a latent mypy problem this surfaced: the numpy-stub
      override in `pyproject.toml` never actually applied, because
      `follow_imports` does not cover `.pyi` files without
      `follow_imports_for_stubs`. It went unnoticed while numpy was merely
      transitive.

**What this milestone does and does not change, stated plainly:** a fresh
install now knows where every card is discussed in all three books and can
search that index. It does **not** improve readings — citation-only chunks
are filtered out of the interpretation context, because a citation under
the prompt's "SOURCE PASSAGES" heading with nothing beneath it invites the
model to invent the contents (`DESIGN.md` §23). Grounded readings still
require the user's own PDFs and `syzygy knowledge ingest`.

---

## M14 — The animation system

`feedback.md` items 13, 14, 15, 16 (and 11, 20 as context), designed
against `animation.md`. Do not start before M12 lands. Implement in the
order below, which follows `animation.md` §40's phasing: the framework
first, then the specific moments the user asked for.

### M14.1 — Animation framework

- [ ] M14.1a Read `animation.md` §2, §29, §30, §33 before writing code.
      The mandatory separation is that animated values are never the
      source of truth: application state stays in `syzygy.domain`/storage,
      temporary visual state lives in the animation layer, and the app
      must remain correct with animation disabled entirely.
- [ ] M14.1b Build the layer at `src/syzygy/tui/animation/` (a new package
      under `syzygy.tui` — Textual types stay inside `syzygy.tui` per
      `AGENTS.md`, and no domain module may import it). Use Textual's
      existing animation/timer machinery where it fits rather than writing
      a frame loop from scratch; `animation.md`'s architecture is the
      contract to satisfy, not a mandate to reimplement what Textual
      already provides.
- [ ] M14.1c Provide the primitives `animation.md` §7 lists that Syzygy
      will actually use — reveal, pulse, flash, shake, dim/brighten, glyph
      morph, typewriter/decode, stagger — plus the easing set from §6
      (`easeOutCubic`, `easeInOutQuad`, `easeOutBack`, `easeInCubic`).
      Build only what M14.2–M14.6 consume; skip the rest until something
      needs it.
- [ ] M14.1d Expose semantic events, not low-level calls (§30): screens
      trigger `enter`/`exit`/`focus`/`success`/`error`/`processing-start`/
      `processing-stop`, and the animation layer maps those to visuals.
      This is the interface the rest of M14 is written against.
- [ ] M14.1e Reduced motion (§34) as a real setting in
      `AppPaths.settings_path`: `full` | `reduced` | `off`, with `off`
      rendering final states immediately. Add a CLI/TUI way to set it, and
      honor the terminal/OS reduced-motion signal if one is available.
      Add the debug slow-motion speed multiplier from §39 too — it makes
      every later task in this milestone easier to verify.
- [ ] M14.1f Tests: easing functions are correct at t=0/0.5/1; animations
      are cancelable and retargetable without leaving stale visual state;
      with `animations = off`, every screen reaches the same final state
      it reaches with animation on (this is the "definition of done"
      property from §42, and it is testable).

### M14.2 — Startup animation and welcome screen

`feedback.md`: "We need a startup animation, then a very cool welcome
screen with 'press any button to continue'."

- [ ] M14.2a Startup sequence on app launch: a Level 3 emphasis event
      (`animation.md` §36), 300–700 ms, using the logo/wordmark from
      M12.2/M12.3 — construct the wordmark rather than blitting it (border
      construction, glyph morph, brightness ramp).
- [ ] M14.2b Redesign `WelcomeScreen` to fill the space (M12.5) and to end
      the startup sequence in a settled state, with an explicit "press any
      key to continue" affordance that genuinely accepts *any* key — while
      keeping `[Q]` quit working, per M10.2's app-level binding.
- [ ] M14.2c Skippable: any keypress during the startup animation jumps
      straight to the settled welcome state (§1.3 — input must never wait
      on animation). Nobody should watch this twice.
- [ ] M14.2d Tests: the app reaches the interactive welcome state with
      animations off, with animations on after the sequence completes, and
      immediately when a key is pressed mid-sequence.

### M14.3 — Self-selected transition

`feedback.md`: "We need an animation for after the user selects a self."

- [ ] M14.3a On profile selection, animate SELF resolving into the
      alignment (`AlignmentWidget`'s `self_resolved`) rather than flipping
      it — the chart anchors stagger in (§11, 20–60 ms apart) as the
      profile's data lands. Level 2, 150–350 ms.
- [ ] M14.3b Preserve spatial continuity into `HomeScreen` (§10): the
      selected profile should visibly become the home screen's identity
      rather than the screen being replaced wholesale.
- [ ] M14.3c Handle the slow path: chart data resolves asynchronously, so
      the animation must not assume data is present at trigger time — it
      animates the *state change*, whenever that arrives.

### M14.4 — Turning the wheel

`feedback.md`: "We need a transition animation for when a user selects to
turn the wheel."

- [ ] M14.4a Anticipation → transition → emphasis → settle (§1.2, §12) on
      leaving `HomeScreen` for `WheelScreen`: the primary action reacts,
      the home layout gives way, the wheel arrives already turning.
- [ ] M14.4b The wheel itself is the one place continuous motion is
      justified (§35: a frame loop only while visibly animating). Verify
      idle CPU returns to baseline once the wheel stops — this is the
      screen most at risk of a permanent render loop.
- [ ] M14.4c The draw moment is Level 3 with particles (§22), used once:
      the rim resolves, chance enters the alignment, and the transition to
      reveal begins. Particles are nonessential (§27) and must be
      cancelable.
- [ ] M14.4d **The animation must not touch selection.** Entropy
      collection and the unbiased draw (`syzygy.sortes`) are unchanged —
      the animation reacts to a card that has already been chosen and
      committed to storage. No animation state may feed the entropy pool
      or influence timing of the draw itself.

### M14.5 — Opening the reading

`feedback.md`: "We need a transition animation for when a user opens
today's reading."

- [ ] M14.5a Reveal choreography on `RevealScreen` → `ReadingScreen`: the
      card art (M11.5) settles, then the interpretation reveals beneath it
      (`REVEAL_VERTICAL`, §7) with a typewriter or decode pass on the
      headline only — never on the body copy (§24: animation may introduce
      text but must not delay access to it).
- [ ] M14.5b Interpretation is asynchronous and may fail: wire
      `processing-start`/`processing-stop` (§16 — an animated border or
      pulsing status, not a bare spinner) and the `error` event (§18 —
      one-cell shake plus a brief flash, never obscuring the error text)
      into the existing pending/failed states in
      `widgets/reading_panel.py`. This is where M11.4d's retry-in-flight
      state lands.
- [ ] M14.5c Reopening an existing reading from the archive should *not*
      replay the full first-time reveal — first reveal is a Level 3
      event, revisiting is Level 1 (§36).

### M14.6 — Consistency pass

- [ ] M14.6a Sweep every screen and replace one-off timing hacks with the
      semantic events from M14.1d (`animation.md` §40 Phase 5). Check
      `widgets/wheel.py` and `widgets/tarot_card.py` for existing bespoke
      timing that predates the framework.
- [ ] M14.6b Verify against `animation.md` §42's definition of done, item
      by item, and record the result in this task — especially: no
      flicker, no input latency, no queued animations, and identical
      behavior with animation off.
- [ ] M14.6c Test at the sizes and terminals §39 lists that are actually
      available here, and note which were checked and which were not
      (SSH and slow terminals are easy to skip and easy to regress).

---

## M15 — Sound

### M15.1 — Looping theme music

`feedback.md`: "We now have a theme song, called theme.mp3 that should
play on a loop the whole time the application is running." `theme.mp3` is
at the repo root and untracked.

- [ ] M15.1a Choose the playback mechanism and record the reasoning. There
      is no audio in the stack today, and every option has a real cost:
      a Python audio library adds a runtime dependency that must be
      AGPL-compatible (`AGENTS.md`) and cross-platform; shelling out to a
      system player (`ffplay`, `mpv`, `paplay`, `afplay`) adds no
      dependency but is not portable and not guaranteed present.
      Recommendation: an optional `audio` extra, mirroring how `geocoding`
      and `providers` are already scoped, so the app runs unchanged
      without it — a terminal divination app must not fail to start
      because it cannot open an audio device.
- [ ] M15.1b Bundle `theme.mp3` under `src/syzygy/resources/audio/` and
      commit it (it is untracked today). Note its size in the task — it
      ships in every wheel — and confirm the licensing of the track itself
      is settled for AGPL redistribution.
- [ ] M15.1c Play on app start, loop seamlessly, stop cleanly on exit
      (including on `[Q]`, on an exception, and on SIGINT — a process that
      exits leaving audio playing is a bug). Playback runs off the event
      loop and must never block or delay the TUI.
- [ ] M15.1d Make it controllable and off-by-default-recoverable: a mute
      toggle bound in the TUI, a persisted setting in
      `AppPaths.settings_path`, and a `--no-audio` CLI flag. Decide
      whether audio defaults to on or off on first launch — recommendation
      is on, since it is an explicit product intent, with the mute key
      advertised on the welcome screen.
- [ ] M15.1e Degrade silently: no audio device, no extra installed, no
      system player, or a headless/CI environment must all result in a
      silent app, never a crash or an error dialog. Tests cover the
      no-audio path (CI has no audio device, so that is the path the test
      suite will actually exercise) and the mute setting round-trip.
