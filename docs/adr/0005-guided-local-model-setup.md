# ADR 0005 — Guided local-model setup: trust boundary, platform matrix, and process lifecycle

- **Status:** accepted
- **Date:** 2026-08-09
- **Milestone:** M16
- **Supersedes:** nothing. Extends the provider work in M7 and the
  in-TUI provider selection in M10.4.

## Context

Until M16, "use a local model" meant: install llama.cpp yourself, start
`llama-server` yourself, and type its base URL into a form. That is a
reasonable ask of somebody who already knows what those words mean. It is
not a reasonable ask of the person this application is for, and the result
was that the private, local, no-account path — the one `docs/old/DESIGN.md`
section 13.2 treats as the *default* posture — was in practice the hardest
one to take.

M16 makes Syzygy do the work: inventory the machine, reuse whatever is
already installed, recommend a model that will actually run, obtain only
what the user explicitly approves, start a localhost-only server, and
verify it with a real Syzygy-shaped request before switching anything
over.

Doing that means Syzygy now downloads executables and multi-gigabyte data
files, and runs a child process. Those are the largest new powers this
codebase has taken, and this ADR records the boundaries around them.

## Decision

### 1. llama.cpp is a user-approved external runtime, not a Python dependency

Syzygy does **not** depend on `llama-cpp-python` or any in-process
inference library.

- **Licensing and distribution.** A Python inference package would drag
  compiled CUDA/Metal/ROCm variants into Syzygy's own dependency graph and
  its own wheels. llama.cpp is MIT and AGPL-compatible either way, but
  vendoring accelerator builds into an astrology program's install is a
  packaging burden with no upside — `pip install syzygy` must stay small
  and must not need a compiler.
- **Blast radius.** An in-process model shares Syzygy's address space:
  an out-of-memory kill takes the interface, the database connection, and
  the unsaved ritual with it. A child process cannot do that. When it
  dies, the card is already committed (`ReadingStatus`), the reading is
  retryable, and the user sees a remedy.
- **Substitutability.** The OpenAI-compatible `/v1` surface means an
  externally-managed server, LM Studio, Ollama, or a machine on the LAN
  the user configures by hand are all the *same* integration. There is one
  transport (`interpretation.providers.llama_cpp`), not two.
- **Consequence, accepted:** Syzygy has to acquire a binary, which is the
  rest of this ADR.

### 2. Trust boundary

Everything Syzygy will download is pinned in a reviewed, packaged
manifest — `src/syzygy/resources/local_models/catalog.yaml` for models and
`runtimes.yaml` for the runner. The rules, enforced by
`local_models.catalog` at load time (so a violation fails the test suite,
not a user's install):

- HTTPS only, and only from an allowlisted host.
- Models pin an **immutable revision** (a 40-char commit sha), and the
  `download_url` must actually contain that revision — a `/resolve/main/`
  URL with a revision recorded beside it is rejected.
- Every artifact pins a `sha256` and an exact `size_bytes`. The digest is
  verified **before** anything is extracted, executed, or promoted.
- Only publisher-owned artifacts are listed. Community requantizations are
  not in the default catalog and adding one would be an explicit,
  recorded trust decision — not a URL a user can paste into a field.
- Archives are extracted with path-traversal, symlink-target, hard-link,
  device-node, and uncompressed-size checks (`local_models.archives`).
- No shell, ever. Every command is an argument array with `shell=False`
  and a timeout. No remote script is piped anywhere. Source compilation is
  never the beginner path.
- No privilege elevation. If a package manager's output indicates it
  wanted administrator rights, the flow **stops and says so** rather than
  escalating or answering a prompt.

### 3. Update policy

Catalog and runtime pins change only through a reviewed release.
Automated freshness checks may *report* that a newer llama.cpp build or
model revision exists; they may not rewrite a pin, and nothing at runtime
tracks "latest". A user who wants a newer runtime updates Syzygy, or
installs llama.cpp themselves and uses the external-server route.

`catalog_version` is recorded alongside a licence acceptance and alongside
the last successful verification, so a catalog change asks the user again
rather than inheriting a consent given to different terms.

### 4. Supported platform matrix

Automatic installation is offered for:

| OS | Architecture | Backend installed |
|---|---|---|
| macOS | arm64 | Metal |
| macOS | x86_64 | CPU |
| Windows | x86-64 | Vulkan, else CPU |
| Linux | x86-64 | Vulkan, else CPU |

Hardware discovery additionally *recognises* Windows on ARM, Linux ARM,
WSL, containers, and AMD/Intel/NVIDIA devices — it simply does not offer
those an automatic install. They get the inventory, the assessment, and a
clear route to the external-server path, which is a supported outcome of
setup and not a failure.

**No CUDA or ROCm archive is in the automatic manifest**, although both
exist upstream. llama.cpp's Windows CUDA build needs a second ~390 MB
CUDA-runtime archive and a driver new enough for the CUDA minor version;
the ROCm build needs a matching ROCm installation Syzygy cannot provide.
Vulkan works on NVIDIA, AMD, and Intel with the driver the user already
has. Somebody who wants CUDA or ROCm installs llama.cpp themselves and
points Syzygy at it. Expanding the table requires a platform fixture *and*
a recorded end-to-end validation result.

### 5. Process lifecycle and localhost binding

- **`--host 127.0.0.1`, always.** Never `0.0.0.0`, never a firewall
  change, never LAN advertisement. The port is leased by binding to port 0
  and reading back the assignment; a collision leases a different port
  rather than retrying the same one.
- **App-managed.** The server starts on demand before the first local
  call, is reused for the rest of the run, and is terminated on exit —
  gracefully, then forcibly, both bounded, so quitting Syzygy can never
  hang on a wedged child. A "keep it running after Syzygy exits" option is
  explicitly out of scope until cross-platform orphan handling is proven.
- **No reading content on the command line.** The argument array carries
  the model path, the context and output limits, threads, GPU layers, the
  host, the port, and an alias. No prompt, profile, card, or date is ever
  visible in the process list.
- **A PID is never trusted alone.** After a crash, a recorded process is
  only acted on when it exists *and* its command line still names both the
  executable and the model path Syzygy launched it with. If the platform
  will not disclose a command line, the answer is "cannot verify", the
  stale record is cleared, and **nothing is signalled**. Syzygy will
  never send a signal to a process it could not identify.

### 6. Verification gates activation

The managed provider is not persisted as active until endpoint discovery,
readiness, schema support, *and* a Syzygy-specific smoke test all succeed.
The smoke test runs the daily-reading, natal-summary, and cosmos-summary
schemas against fixed synthetic input through the same
parse-and-repair path a real reading uses. It creates no reading, draws no
card, calculates no astrology, and does not open the readings database.

Activation captures the previous provider selection first and restores it
on any failure, including partial success. `VerificationRecord` stores the
runtime version, catalog version, prompt version, and served model id, so
a later upgrade can tell when verification must run again — a boolean
could not answer that question.

### 7. Ownership, and what may be deleted

Managed artifacts carry an `OWNERSHIP.json` marker. A destructive
operation requires three things at once: the path resolves inside
Syzygy's managed tree, the directory carries a marker Syzygy recognises,
and that marker names the exact file. An external binary, a
user-referenced model file, and another application's Hugging Face cache
all fail the first condition and can never be removed. Removal is a
separate, clearly named, separately confirmed operation — never a side
effect of setup.

## Consequences

- Syzygy's install stays small; the large artifacts are user-approved and
  live in the user data directory, never in the wheel.
- A user on an unvalidated platform gets a worse experience than one on a
  validated platform, by design: an honest manual route beats a confident
  automatic install that does not work.
- The catalog will go stale between releases. That is the intended
  trade-off against silently tracking a moving upstream.
- **Known gap at the time of writing.** Every catalog entry ships as
  `support_status: provisional`. Pinning, licence review, and the memory
  arithmetic are done and exact; the Syzygy-specific evaluation harness
  (M16.3b — schema-valid rate, repair rate, fidelity rubric, tokens per
  second on representative hardware) has not been run, so no artifact may
  claim `supported` and no recommendation may claim `high` confidence.
  The catalog validator enforces this: an artifact claiming `supported`
  without an `evidence_id` fails to load. The wizard says "Syzygy has not
  yet measured how well it writes readings on hardware like yours" rather
  than implying evidence that does not exist.

## Alternatives considered

- **`llama-cpp-python` in-process.** Rejected: see §1.
- **Ollama as the runtime.** It solves acquisition well, but it is a
  second daemon with its own model store, its own lifecycle, and its own
  update cadence, and it would make Syzygy's "what exactly is on my disk"
  answer somebody else's. Ollama is nevertheless *discovered* — its
  default port is on the conventional-port list, and a running instance
  can be used as an existing server.
- **Downloading whatever the user pastes.** Rejected: without a pinned
  digest there is nothing to verify against, and "paste a URL" is the
  question M16 exists to stop asking.
- **Letting the model choose its own quantization or context.** Rejected:
  Syzygy owns significance and sizing, as it owns transit ranking
  (`AGENTS.md`). The context is pinned at 8192 tokens because that is what
  the real prompt needs, not because a model advertises 128k.
