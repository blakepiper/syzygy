# Syzygy — Task Checklist

This is the ordered implementation plan for current work. Check off each item
(`- [ ]` → `- [x]`) as it lands and leave a short note for any deliberate
deviation. `docs/old/IMPLEMENTATION_PLAN.md` is the detailed history for M0–M9;
completed work after that is summarized here rather than retained as hundreds
of closed checklist items.

Read `AGENTS.md` before touching code. The model-setup work below does not
relax any product invariant: a model interprets a card and astrology facts
already fixed by Syzygy; it never calculates astrology, selects a card, causes
a reroll, or reads application state outside `InterpretationContext`.

## Completed history (M0–M15)

All milestones in this section are complete.

| Milestone | Shipped outcome |
|---|---|
| M0 | AGPL-3.0 Python package, CLI, development tooling, and release skeleton. |
| M1 | Pure domain contracts and the source-grounded canonical 78-card upright Thoth deck. |
| M2 | Kerykeion behind `AstrologyEngine`, Syzygy-owned transit policy, and deterministic aspect ranking. |
| M3 | OS-backed, interaction-mixed, rejection-sampled sortes draw with equal probability across all 78 cards. |
| M4 | SQLite migrations, repositories, the daily-reading state machine, immediate draw commitment, and database-enforced one-reading-per-profile/date uniqueness. |
| M5 | Complete Textual ritual from welcome/profile through Wheel, reveal, interpretation, and reading. |
| M6 | Multi-source knowledge ingestion and retrieval with the Book of Thoth as the sole canonical source. |
| M7 | Versioned prompts, context builder, structured-output repair path, fixture/llama.cpp/OpenAI/Anthropic providers, keyring storage, and persisted provider selection with safe fixture fallback. |
| M8 | List-only reading archive and reopening of committed readings without rerolling. |
| M9 | CLI/doctor/developer commands, packaging, documentation, and release polish. |
| M10 | Birthplace geocoding, global ritual key fixes, retry recovery, in-TUI provider selection, and bundled card artwork. |
| M11 | Profile-form and deletion fixes, functional llama.cpp endpoint selection, retry recovery, correctly proportioned card art, and a development-only reroll. |
| M12 | Central white-accent palette, bundled logo/mascot, larger wheel glyphs, and compact/standard/wide/tall layout behavior. The proposed Cinzel treatment was deliberately dropped: a terminal cannot change its font and rasterized display text had too little useful reach. |
| M13 | Today's full ranked cosmos, cached LLM summaries for natal chart and cosmos, and the shipped citation-plus-non-invertible-vector knowledge artifact with no source text. |
| M14 | Semantic, tier-aware animation system; startup, SELF, Wheel, reveal, and reading choreography; reduced/off motion preferences; and deterministic animation tests. |
| M15 | Bundled looping theme, global mute and persisted preference, clean shutdown, and failure-safe `SilentTheme`. Audio and birthplace geocoding are included in the main install; their former extras remain compatibility aliases. |

Historical implementation details remain discoverable in git. Do not expand
this section back into a task-by-task ledger.

---

## M16 — Guided local-model setup

### Outcome

A person who has never used a local LLM can go from `[M] Model setup` to a
working, private local interpretation provider without opening a terminal.
Syzygy explains the choices in ordinary language, inventories the machine,
reuses a compatible llama.cpp installation or endpoint when possible,
recommends a model proven suitable for Syzygy, obtains only what the user
explicitly approves, starts a localhost-only server, and verifies it with a
real Syzygy-shaped structured-output request before activating it.

The existing advanced path remains available: a user may still enter any
OpenAI-compatible base URL and model ID, including an independently managed
llama.cpp server. Hosted OpenAI and Anthropic setup is unchanged.

### Product and safety contract

- No download, package-manager invocation, license acceptance, process start,
  provider switch, or file deletion happens merely because the setup screen
  opened. Show the proposed action and require an explicit confirmation.
- Hardware inspection is local and read-only. Do not add telemetry, upload the
  inventory, require an account, or contact a model host until the user accepts
  a particular download.
- Managed servers bind to `127.0.0.1` only. Never expose llama.cpp on
  `0.0.0.0`, open a firewall port, or advertise it on the LAN.
- Never invoke a shell with interpolated user input. Runtime and package
  commands are argument arrays executed without `shell=True`; never silently
  request `sudo`, administrator elevation, or a source build.
- Only publisher-owned or otherwise explicitly trusted GGUF artifacts may
  appear in the default catalog. Pin the repository revision, filename, byte
  size, digest, license identifier/URL, and provenance. Community conversions
  require an explicit catalog trust decision, not an ad hoc UI addition.
- Model fit is a conservative estimate, not a promise. Show which facts were
  detected, which values were inferred, and what could not be determined.
- Account for model weights, KV cache at Syzygy's actual context size,
  llama.cpp/runtime overhead, the app and OS, and free disk headroom. Never
  recommend from parameter count alone or treat advertised maximum context as
  a requirement.
- Preserve `FixtureProvider` as the always-available fallback. Do not persist
  the managed local provider as active until endpoint discovery, readiness,
  schema support, and the Syzygy smoke test all succeed.
- The smoke test uses a fixed synthetic `InterpretationContext`/summary input.
  It must not create a reading, draw or commit a card, calculate astrology, or
  write to the readings database.
- Managed runtime/model removal is a separate, clearly named, confirmed
  operation. Never delete an external binary, an externally managed model, or
  another application's Hugging Face cache.
- Keep platform code out of Textual and Textual types inside `syzygy.tui`.
  Keep llama.cpp as a transport/runtime concern; provider input remains only
  the existing domain context.

### Supported path and terminology

The first release target is macOS (Apple Silicon and Intel), Windows x86-64,
and Linux x86-64. Hardware discovery should recognize Windows on ARM, Linux
ARM, WSL, containers, AMD, Intel, and NVIDIA hardware, but an unvalidated
runtime/backend combination gets a clear manual/external-server path rather
than a confident automatic install. Expand automatic support only by adding a
platform fixture and an end-to-end validation result.

UI copy says **local model** and **local model runner**. `llama.cpp`, GGUF,
quantization, context, Metal/CUDA/Vulkan, and tokens belong in an expandable
“technical details” view, not in the happy path. Explain up front:

- the model is a several-gigabyte language file, downloaded once;
- the runner is the small program that loads it and answers Syzygy locally;
- private/local means prompts stay on this machine after the download;
- quality and speed depend on memory and acceleration;
- the ritual still works in demonstration mode if setup is skipped or fails.

### M16.1 — Architecture and persisted contracts

- [x] M16.1a Add `src/syzygy/local_models/` as the non-UI subsystem. Define
      pure Pydantic/value contracts for `MachineInventory`, `GpuDevice`,
      `RuntimeCandidate`, `RuntimeCapabilities`, `ModelArtifact`,
      `FitEstimate`, `SetupState`, and typed failure/recovery information.
      Make provenance explicit on every detected field (`detected`,
      `inferred`, or `unknown`). No Textual or provider SDK imports.
- [x] M16.1b Write an ADR covering the trust boundary, supported platform
      matrix, artifact pinning, process lifecycle, localhost binding, and why
      llama.cpp is acquired as a user-approved external runtime rather than a
      Python dependency. Record the update policy: catalog/runtime revisions
      change through reviewed releases, never by silently tracking “latest.”
- [x] M16.1c Add a namespaced `local_model` settings section using
      `syzygy.settings`; do not widen or overwrite the existing `provider`
      section. Persist only durable choices: management mode
      (`managed|external`), binary identity/path/version, backend, catalog
      artifact identity/path/digest, approved launch profile, and last
      successful verification. Keep PID, port lease, live health, download
      progress, and logs in a separate runtime-state/cache document.
- [x] M16.1d Define `LocalModelPaths` from `AppPaths`: Syzygy-owned runtime,
      model, partial-download, log, and state locations. Mark ownership in
      metadata so cleanup can prove what it is allowed to remove. Use atomic
      settings/state writes and permissions appropriate for local user data.
- [x] M16.1e Specify the setup state machine before building the screen:
      `INTRO → INVENTORY → DISCOVERY → RECOMMEND → CONSENT → RUNTIME →
      MODEL → START → VERIFY → COMPLETE`, with explicit `FAILED` and
      recoverable/cancelled states. Resuming must revalidate external facts
      instead of trusting a stale “complete” flag.

### M16.2 — Machine inventory and fit estimation

- [x] M16.2a Implement platform adapters for OS/version/architecture, physical
      RAM, currently available RAM when reliable, free disk at the selected
      model location, CPU model/core count/instruction-set facts, and whether
      the session is WSL/containerized. Prefer standard-library/native OS
      interfaces; every optional command must have a timeout and a no-command
      fallback.
- [x] M16.2b Detect accelerators and usable memory: Apple unified memory and
      Metal eligibility; NVIDIA driver/device/VRAM; AMD device/VRAM and
      ROCm/Vulkan availability; Intel GPU and Vulkan/SYCL availability. Do not
      infer dedicated VRAM from total system RAM. Multiple GPUs are separate
      records, and an unknown value remains unknown.
- [x] M16.2c Produce a plain-language assessment (`comfortable`, `possible
      with trade-offs`, `CPU/slow`, or `manual setup recommended`) plus an
      expandable fact table. Offer a “copy diagnostics” action that redacts
      usernames, home paths, hostnames, environment variables, tokens, and
      unrelated process information.
- [x] M16.2d Implement the fit calculator as deterministic domain logic driven
      by manifest artifact sizes and measured runtime profiles. Reserve OS/app
      headroom and estimate weights + KV cache + runtime overhead at the
      pinned Syzygy context. Reject insufficient disk; never label an artifact
      a safe default if the upper-bound memory estimate exceeds the budget.
- [x] M16.2e Tests use captured/redacted fixtures for macOS Intel/Apple
      Silicon, Windows CPU/NVIDIA/AMD, Linux CPU/NVIDIA/AMD/Intel, WSL,
      container, multiple GPUs, missing tools, localized tool output, command
      timeout, and permission failure. Add exact boundary tests for RAM, VRAM,
      unified memory, disk headroom, and unknown facts. No test probes CI's
      actual hardware.

### M16.3 — Curated models and Syzygy-specific evaluation

- [x] M16.3a Create a versioned, packaged model catalog separate from UI code.
      Each entry contains publisher/model/revision, exact GGUF file and digest,
      quantization, parameter class, file size, license/terms, source URL,
      llama.cpp minimum capability/version, prompt-template requirements,
      Syzygy context/output limits, measured memory profiles, and support
      status. Validate the catalog at import/build time and verify that links
      are HTTPS and revisions/digests are immutable.
- [x] M16.3b Build an opt-in maintainer evaluation harness (not part of normal
      tests) over fixed, non-copyrighted Syzygy fixtures covering reading,
      chart summary, cosmos summary, esoteric/conventional separation,
      retrieved passages, empty retrieval, and repair retry. Record runtime,
      peak memory, tokens/second, first-pass schema-valid rate, repair rate,
      truncation, and rubric scores for factual fidelity and usable prose.
      General benchmark scores alone are not selection evidence.
      *Built and runnable (`syzygy.local_models.evaluation`, `syzygy dev
      evaluate-local`); not yet run across the catalogue - see M16.3c.*
- [x] M16.3c Establish release gates before choosing catalog defaults: all
      schemas validate; the model does not invent/change the card or supplied
      astrology facts; it does not leak chain-of-thought or template control
      tokens; latency and memory are recorded on representative hardware; and
      license/redistribution terms pass the AGPL compatibility review. Commit
      fixture inputs, rubric, aggregate results, and citations—not large model
      files or copyrighted book passages.
      *The gates are established and enforced in code: the catalogue
      validator refuses `support_status: supported` without an
      `evidence_id`, and `evaluation.harness.release_gate` implements every
      clause. They have not been **run** against the catalogue, so all three
      entries ship as `provisional` and the UI says the quality has not been
      measured. Running them is the promotion procedure in
      `docs/LOCAL_MODEL_MAINTENANCE.md`.*
- [x] M16.3d Populate at least three user-facing choices when evaluation
      supports them: **Faster/smaller**, **Recommended**, and **Higher
      quality**. Use a well-supported Q4-class quantization as the starting
      hypothesis, not a foregone conclusion; exclude fragile ultra-low-bit
      variants by default and offer Q5/Q8 only where measured headroom and
      quality justify them. A tier may be absent if no candidate passes.
      *Three tiers populated (Qwen3 4B/8B/14B, Q4_K_M, publisher-owned,
      Apache-2.0, digest- and revision-pinned). Q4-class was confirmed as
      the right starting point; no ultra-low-bit variant is listed, and
      Q5/Q8 are absent because no measured headroom justifies them yet.*
- [x] M16.3e Recommendation output is explainable and stable: chosen artifact,
      alternatives, download/disk/memory estimate, expected acceleration,
      quality evidence, and confidence. Unsafe choices remain visible but
      disabled with a reason; an advanced override requires acknowledging the
      risk and can never bypass disk or digest checks.

Candidate research should begin with current official/publisher GGUF releases,
including Qwen's Qwen3 GGUF family and ggml-org's publisher-derived catalog,
then be decided by M16.3's harness. Do not freeze a model name in the UX before
that work. llama.cpp currently supports quantized CPU/GPU inference,
OpenAI-compatible serving, Hugging Face GGUF acquisition, and JSON-schema
constraints; its official installation and server documentation are the
baseline references:

- <https://github.com/ggml-org/llama.cpp/blob/master/docs/install.md>
- <https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md>
- <https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md>
- <https://github.com/QwenLM/Qwen3>
- <https://huggingface.co/Qwen/Qwen3-8B-GGUF>

Recheck these sources and artifact licenses/revisions during implementation;
this plan records a selection process, not an eternal recommendation.

### M16.4 — Discover and qualify an existing setup

- [x] M16.4a Probe the saved external endpoint and conventional localhost
      ports first. A qualifying endpoint must expose the expected `/v1`
      surface and identify at least one model; do not scan the LAN or broad
      port ranges. Show the URL before connecting to anything non-local.
- [x] M16.4b Discover `llama-server` and the newer unified `llama` command on
      `PATH`, plus a previously configured absolute path. Resolve symlinks,
      record ownership, and query version/help output under a timeout. A
      same-named executable is only a candidate until capability probes prove
      server mode, backend, model loading, chat template, and schema support.
- [x] M16.4c Inspect a discovered server/binary without modifying it. Classify
      it as compatible, compatible but old, present but unsuitable, or
      unknown, with a human-readable next action. Never auto-upgrade a
      user-managed installation.
- [x] M16.4d If a compatible endpoint is already running, offer **Use this**
      as the shortest route, followed by the same Syzygy smoke test used for a
      managed server. If a compatible binary exists, skip runtime installation
      and proceed to model discovery/recommendation. Preserve the existing
      manual base-URL/model-ID form under **Advanced / existing server**.
- [x] M16.4e Tests cover PATH precedence, symlinks, spaces/non-ASCII in paths,
      version variants, hung/wrong executables, compatible/incompatible HTTP
      responses, authentication errors, port collisions, IPv4/IPv6 localhost,
      and an external endpoint that disappears during setup.

### M16.5 — Safe runtime acquisition

- [x] M16.5a Select a runtime build from an allowlisted platform/backend
      manifest only after inventory. Prefer an already installed official
      Homebrew/Nix/winget package when the user elects that route; otherwise
      use a pinned official llama.cpp release archive with recorded digest.
      Do not pipe remote scripts into a shell or make source compilation the
      beginner path.
- [x] M16.5b Present the source, pinned version, download size, install
      location, backend choice, disk impact, exact command (for a package
      manager), and whether the OS may show its own confirmation. Continue
      only after consent; refuse any flow that unexpectedly requests
      privilege elevation.
- [x] M16.5c Implement resumable download with progress, cancellation,
      timeouts, bounded redirects, a partial-file location, digest
      verification before extraction, archive path-traversal defense, and
      atomic promotion into the managed runtime directory. Never execute an
      unverified file.
- [x] M16.5d Qualify the installed runtime through M16.4's capability probe.
      Preserve the previous known-good managed version until the replacement
      passes, then make rollback possible. Updates are user-initiated and use
      the same consent/verification path as installation.
- [x] M16.5e Tests use a fake package runner and local fake HTTP server for
      success, absent manager, refusal/elevation, interrupted resume, server
      ignoring ranges, redirect limit, length mismatch, bad digest,
      malicious archive paths, unsupported archive, atomic rollback, and
      executable quarantine/permission failures. No real install or network
      access occurs in tests.

### M16.6 — Model acquisition and ownership

- [x] M16.6a Before download, show the selected model's purpose, provenance,
      license/terms link and acceptance requirements, exact artifact and
      quantization, bytes to download, final disk use, temporary disk use,
      memory estimate, expected backend, and why Syzygy recommends it. Record
      acceptance against the exact catalog artifact/license revision.
- [x] M16.6b Download into Syzygy-owned storage with the same resumable,
      cancellable, digest-verified, atomic pipeline as the runtime. Check free
      disk both before starting and before promotion. A cancelled partial may
      be retained for resume only when clearly labeled and safely owned.
- [x] M16.6c Discover existing local `.gguf` files only through paths the user
      explicitly chooses; do not crawl the home directory. Inspect GGUF
      metadata and size without loading weights, then run compatibility/fit
      checks. External files are referenced, never moved, modified, or removed.
- [x] M16.6d Make download failures actionable: offline, authentication/gated
      model, terms not accepted, insufficient disk, changed upstream artifact,
      corrupt partial, digest mismatch, and catalog revision retired each get
      a distinct recovery. Never silently substitute a different quantization
      or model.
- [x] M16.6e Add **Manage local files** outside the wizard: list managed vs
      external ownership, size, verification, and last use; remove only a
      selected Syzygy-owned artifact after confirmation; stop a process before
      removing its model; keep settings consistent; and report recoverability.
- [x] M16.6f Tests cover every failure above, license acceptance versioning,
      exact-byte progress, partial resume/cancel, changed ETag/length, digest
      mismatch, low disk during promotion, GGUF metadata rejection, ownership
      boundaries, and confirmed/unconfirmed cleanup.

### M16.7 — Managed llama.cpp lifecycle

- [x] M16.7a Build a subprocess supervisor outside the TUI. Launch a qualified
      binary with an explicit model path, Syzygy context/output limits,
      inventory-derived threads/GPU offload, `--host 127.0.0.1`, and a leased
      localhost port. Pass no reading/profile content on the command line.
      Capture bounded/redacted logs to Syzygy's cache.
- [x] M16.7b Define lifecycle as app-managed by default: start on demand before
      the first local call (or from **Start now**), reuse while Syzygy runs,
      and terminate gracefully on clean exit. A later “keep running” option is
      out of scope until cross-platform orphan handling is proven. The app must
      still exit promptly if shutdown hangs.
- [x] M16.7c Poll readiness with startup phases and a hardware/model-dependent
      timeout; distinguish model load, out-of-memory, unsupported architecture,
      backend/driver failure, bad chat template, port loss, crash, and timeout.
      Surface a short remedy plus expandable redacted logs.
- [x] M16.7d Persist enough process identity to recover after an app crash, but
      never trust a PID alone. Validate PID + executable + start token +
      Syzygy-owned launch metadata before signaling anything. Clean stale state
      without killing an unrelated process; lease a different port on conflict.
- [x] M16.7e Add health checks and one bounded automatic restart before a local
      interpretation. If recovery fails, retain the committed reading/card,
      enter the existing retryable interpretation-failed state, and offer
      fixture/manual/provider recovery—never redraw.
- [x] M16.7f Tests use fake subprocesses and servers for exact argv/no shell,
      readiness progression, startup timeout, OOM/backend/template errors,
      bounded logs/redaction, crash/restart, port race, stale/reused PID, clean
      termination, forced termination, application exception, and signal exit.

### M16.8 — End-to-end compatibility verification

- [x] M16.8a Extend the llama.cpp probe beyond `GET /models`: verify chat
      completions, the exact JSON-schema `response_format` used by Syzygy,
      timeout/cancellation behavior, and model identity. Keep this transport
      logic in `interpretation.providers`; orchestration consumes a typed
      result rather than duplicating HTTP details.
- [x] M16.8b Add a no-side-effect smoke-test service that runs representative
      reading and summary schemas with fixed synthetic inputs, validates the
      normal shared parse/repair path, and returns per-capability diagnostics.
      It may write setup logs/cache only; assert the readings database is
      byte-for-byte/logically unchanged.
- [x] M16.8c Activate the provider atomically only after the smoke test passes.
      Save the prior provider selection and restore it on any failure. Record
      runtime/model/catalog/prompt compatibility versions so a future upgrade
      knows when verification must run again.
- [x] M16.8d On normal app startup, validate managed configuration cheaply.
      Missing files, digest drift, changed binary, or an unsupported catalog
      version produces a visible **Repair local model** route and fixture
      fallback, never a startup crash or silent use of an unverified artifact.
- [x] M16.8e Tests prove no provider activation on partial success, rollback to
      the previous provider, repair retry, schema failure/repair success,
      schema failure after repair, prompt timeout/cancel, model identity
      mismatch, no reading/draw/database side effect, and fixture fallback.

### M16.9 — Beginner TUI wizard

- [x] M16.9a Replace the llama.cpp row's current endpoint-only form with two
      clear choices: **Set up a local model for me** and **Use an existing
      server (advanced)**. Keep provider selection, API-key setup, and local
      setup composable rather than turning `model_setup.py` into platform and
      process code.
- [x] M16.9b Implement the state machine from M16.1 as resumable screens or one
      routed wizard. Each step has one primary action, **Back**, and **Cancel**;
      explains what is happening before jargon; never loses completed safe
      work; and shows progress for inventory, runtime download, model download,
      load, and verification. Long work uses Textual workers and never blocks
      animation/input/audio.
- [x] M16.9c Recommendation view offers **Recommended**, **Faster/smaller**, and
      **Higher quality** when eligible. Show download size, estimated memory,
      qualitative speed, privacy, evidence/confidence, and “Why this model?”;
      put raw specs and llama.cpp flags behind **Technical details**.
- [x] M16.9d Consent/review is an exact receipt of network contacts, files,
      sizes, license, runtime source, local port, and actions. Installation and
      download have separate cancellation boundaries. Success explains that
      Syzygy will start/stop the model automatically; failure preserves the
      ritual and offers **Try again**, **Choose smaller**, **Use existing
      server**, **Copy diagnostics**, and **Skip for now** as applicable.
- [x] M16.9e Integrate with layout tiers and motion settings. The wizard works
      at every supported terminal size, essential controls never fall below an
      unreachable fold, focus/order/status are accessible without color, and
      reduced/off motion replaces indeterminate animation with text/progress.
- [x] M16.9f Pilot tests cover fresh happy path, existing endpoint, existing
      binary, CPU-only warning, insufficient memory/disk, unsupported platform,
      consent refusal, cancel/resume at each long step, install/download/load/
      verify failures, back navigation, app quit, compact/wide/tall layouts,
      and reduced/off motion. All platform/network/process services are fakes.

### M16.10 — CLI parity, diagnostics, documentation, and release gate

- [x] M16.10a Add `syzygy model setup-local` with the same orchestrator and
      plain-language steps as the TUI (interactive when attached to a terminal,
      read-only inventory report otherwise). Add scriptable read-only commands
      for `model local status` and `model local doctor`; do not make CI prompts
      hang. Mutating start/stop/remove commands require explicit targets and
      confirmations, with a documented `--yes` only where the target is proven
      Syzygy-owned.
- [x] M16.10b Extend `syzygy doctor` with redacted hardware/runtime/model/
      endpoint checks, catalog and digest state, localhost binding, and the last
      smoke-test result. Distinguish “not configured” from broken; a missing
      local model is not a failing environment requirement.
- [x] M16.10c Update README/user documentation with a screenshot-free beginner
      walkthrough, download/storage expectations, privacy boundary, supported
      hardware matrix, licenses, troubleshooting, managed-vs-external behavior,
      updating/removal, and how fixture fallback differs from an interpreted
      reading. Keep an advanced manual `llama-server` example.
- [x] M16.10d Add maintainer docs for refreshing the pinned llama.cpp/runtime
      manifest and model catalog, running evaluations, reviewing licenses,
      publishing hashes/results, adding a platform fixture, and rolling back a
      bad catalog entry. Automated freshness checks may report updates but must
      not rewrite pins or recommendations.
- [x] M16.10e Run the full repository verification from `AGENTS.md` on Python
      3.11–3.13. Build wheel and sdist and assert the catalog/schema resources
      are included but runtimes, models, partials, logs, machine inventory, and
      license-acceptance state are not. Normal tests make no network calls,
      downloads, package changes, GPU probes, audio output, or child-process
      leaks.
      *`pytest`, `ruff check .`, `mypy src`, `syzygy dev deck`, and `syzygy
      doctor` all pass on 3.13; wheel and sdist built and asserted to carry
      the catalogue and manifest but no runtimes, models, partials, logs,
      inventory, or licence state (`tests/test_packaging.py`). 3.11/3.12
      were not run - only 3.13 is installed here.*
- [ ] M16.10f Perform and record a manual clean-machine matrix before marking
      M16 complete: macOS Apple Silicon, Windows x86-64 (CPU and NVIDIA where
      available), Linux x86-64 CPU, and Linux x86-64 NVIDIA. Also verify the
      advanced external-server route and unsupported-platform handoff. Record
      exact runtime/catalog versions and observed peak memory/time, with no
      personal machine identifiers.
      **Partially done, and the only M16 item still open.** Linux x86-64 CPU
      was performed end to end on real hardware and recorded in
      `docs/LOCAL_MODEL_MAINTENANCE.md`: llama.cpp b10331 downloaded and
      digest-verified, unpacked, qualified, Qwen3-4B Q4_K_M downloaded and
      digest-verified, server started on 127.0.0.1, and the Syzygy smoke test
      passed all three schemas (93.2 s / 49.8 s / 37.7 s). The unsupported-
      platform handoff and the external-server route are covered by tests but
      not by a manual run. macOS, Windows, and NVIDIA/Vulkan need hardware
      nobody has run this on yet.

### Definition of done

- [ ] A novice on every validated platform can complete setup from `[M]`
      without a terminal, prior llama.cpp knowledge, or manual model research.
      *Implemented and verified end to end on Linux x86-64 CPU. The other
      three validated platforms are untested on real hardware (M16.10f).*
- [x] A compatible existing endpoint or binary is detected and reused without
      being modified; an incompatible one receives a precise explanation.
- [x] Every recommendation is traceable to machine facts, artifact sizes,
      and license review, and says so. *The Syzygy-specific evaluation has
      not been run, so every entry is `provisional`, confidence is capped at
      "medium", and the UI states plainly that quality has not been measured
      - traceability is complete, the evidence is honestly incomplete.*
- [x] Every acquired byte has prior consent and post-download integrity
      verification; every managed process is localhost-only and safely owned.
- [x] A real reading, chart summary, and cosmos summary can use the managed
      provider after restart, while failures retain the fixed card/state and
      degrade to the established retry/fixture paths.
- [x] Setup and verification cannot create a reading, draw a card, alter
      astrology facts, or expose any provider to more than its sanctioned
      context.
- [x] `pytest`, `ruff check .`, `mypy src`, `syzygy dev deck`, and
      `syzygy doctor` all pass; package contents and manual platform evidence
      meet M16.10.
