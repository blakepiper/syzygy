# Maintaining the local-model catalogue and runtime pins

For maintainers. Everything here changes what other people's computers
download, so nothing here is automated end-to-end on purpose: a freshness
check may *report* that something moved, but a human decides whether the
pin moves with it.

Read `docs/adr/0005-guided-local-model-setup.md` first — it records why
the boundaries are where they are.

---

## The two files

| File | Holds |
|---|---|
| `src/syzygy/resources/local_models/catalog.yaml` | Curated GGUF models, pinned by revision and digest |
| `src/syzygy/resources/local_models/runtimes.yaml` | The one llama.cpp release Syzygy installs, per platform/backend |

Both are validated on load by `syzygy.local_models.catalog`, and
`tests/local_models/test_catalog.py` runs that validation against what
actually ships. A pin that breaks a rule fails the test suite rather than
a user's install.

---

## Refreshing the llama.cpp pin

1. Pick a release from <https://github.com/ggml-org/llama.cpp/releases>.
   Prefer one that has been up for a few days over the newest possible
   build.

2. Get the asset digests. GitHub publishes a `digest` field per asset:

   ```bash
   curl -sS https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/bXXXXX \
     | python3 -c '
   import json,sys
   d=json.load(sys.stdin)
   for a in d["assets"]:
       print(f"{a[\"name\"]:55s} {a[\"size\"]:>12} {a.get(\"digest\")}")'
   ```

3. Update `release_tag`, `build`, `release_url`, and every entry under
   `builds` — `asset`, `url`, `sha256` (without the `sha256:` prefix),
   and `size_bytes`.

4. Check the archive layout has not changed. The macOS and Linux tarballs
   put everything under `llama-<tag>/`; the Windows zips are flat. The
   installer searches rather than assuming, but `server_executables` must
   still name the right files:

   ```bash
   curl -sSL -o /tmp/llama.tar.gz <the ubuntu-x64 url>
   tar tzf /tmp/llama.tar.gz | grep -E 'llama-server|/llama$'
   ```

5. Re-check the flags the supervisor passes. `local_models.supervisor.build_argv`
   uses `--model --host --port --ctx-size --n-predict --alias --no-webui
   --threads --n-gpu-layers`. Confirm each still exists:

   ```bash
   ./llama-server --help | grep -E -- '--ctx-size|--n-predict|--no-webui|--alias'
   ```

6. Confirm the version string still parses. `llama-server --version`
   writes `version: NNNNN (sha)` to **stderr**; the newer unified `llama
   --version` writes `bNNNNN-sha` to **stdout**. `discovery._VERSION_PATTERNS`
   handles both; if a build changes the format, add a pattern rather than
   replacing one — older installations still report the old shape.

7. Run `pytest tests/local_models/test_catalog.py` and then a real
   end-to-end acquisition on at least one platform.

**Do not add a CUDA or ROCm entry** without also solving the second-archive
and driver-matrix problems ADR 0005 §4 describes, and recording an
end-to-end validation on that hardware.

---

## Adding or refreshing a model

1. **Choose only publisher-owned artifacts.** A community requantization
   is an explicit trust decision recorded in the ADR, not a catalogue
   edit.

2. **Get the immutable revision and the digest** from Hugging Face's API.
   The LFS `oid` *is* the file's sha256, so this is verifiable without
   downloading gigabytes:

   ```bash
   REPO=Qwen/Qwen3-8B-GGUF
   SHA=$(curl -sS "https://huggingface.co/api/models/$REPO" | python3 -c 'import json,sys;print(json.load(sys.stdin)["sha"])')
   curl -sS "https://huggingface.co/api/models/$REPO/tree/$SHA?recursive=true" \
     | python3 -c '
   import json,sys
   for e in json.load(sys.stdin):
       if e["path"].endswith(".gguf"):
           print(e["path"], e["size"], (e.get("lfs") or {}).get("oid"))'
   ```

   The `download_url` **must contain that revision**. A `/resolve/main/`
   URL is rejected by the validator, because a branch can move under a
   digest that then fails for everyone.

3. **Compute the KV cache exactly.** It is arithmetic over the file's own
   GGUF header, not an estimate. Read the header with a range request —
   no full download needed:

   ```python
   import urllib.request, sys
   sys.path.insert(0, "src")
   from syzygy.local_models.gguf import parse_gguf_header

   url = "https://huggingface.co/<repo>/resolve/<sha>/<file>.gguf"
   req = urllib.request.Request(url, headers={"Range": "bytes=0-8388607"})
   with urllib.request.urlopen(req, timeout=60) as response:
       metadata = parse_gguf_header(response.read())
   print(metadata.kv_cache_bytes(8192))
   ```

   Record it as `kv_cache_provenance: computed`, and put the shape it came
   from in `source` (layers, KV heads, head dimensions) so the next person
   can check the arithmetic.

4. **Runtime overhead** is not derivable from the header. Until the model
   has been measured, use the documented rule — **1 GiB + 8% of the weight
   file** — and record it as `runtime_overhead_provenance: estimated`.
   Once you have a measurement, replace it and mark it `measured`.

5. **Licence review.** The artifact's licence must be AGPL-compatible and
   must permit redistribution of the *link*, which is all Syzygy ships.
   Record the identifier and a URL that a person can actually read.

6. `support_status` starts as `provisional`. See the next section for what
   it takes to promote it.

---

## Promoting an artifact to `supported`

The catalogue validator refuses to load an artifact claiming
`support_status: supported` without an `evidence_id`. That is M16.3c's
gate, and this is how you earn one.

1. Set the model up on the hardware you intend to report:

   ```bash
   SYZYGY_DEV=1 syzygy model setup-local --tier faster --yes
   syzygy model local status        # note the port
   syzygy model local start         # or leave the wizard's server running
   ```

2. Run the harness:

   ```bash
   SYZYGY_DEV=1 syzygy dev evaluate-local \
     --base-url http://127.0.0.1:PORT/v1 \
     --model <served id> \
     --artifact <catalog id> \
     --runtime-version b10331 \
     --hardware "MacBook Pro M2 Pro, 16 GB, Metal" \
     --peak-memory-bytes 9876543210 \
     --license-reviewed \
     --out docs/evaluations/<artifact>-<hardware-slug>.json
   ```

   Peak memory is **measured externally** — `/usr/bin/time -v`, Activity
   Monitor, Task Manager — and passed in. The harness will not guess it,
   and the gate does not pass without it.

3. Read the output. The harness scores what a program can score
   (schema validity, repair rate, truncation, required facts present,
   control-token leakage, how distinct the two registers are). It leaves
   `rubric_factual_fidelity` and `rubric_usable_prose` empty for you to
   fill in on a 1–5 scale after reading the readings it produced. A
   number a program invented for "is this prose any good" would be worse
   than a blank.

4. The gate passes only when: every case validated, no supplied fact was
   dropped, no chain-of-thought or template control token leaked, a token
   rate was recorded, peak memory was recorded, and the licence review is
   recorded.

5. Commit the results JSON, set `evidence_id` to its filename, and change
   `support_status` to `supported`. **Never commit model files, model
   output verbatim at length, or any book passage.**

---

## Retiring an entry

Set `support_status: retired` and remove its `tier` — the validator
rejects a retired entry that still claims one. A retired model disappears
from new setups; an installed copy keeps working, and the repair route
explains why it is no longer listed. Do not delete the entry: a user's
settings still reference its id, and an unknown id is a worse message than
a retired one.

To roll back a bad catalogue revision, restore the previous entry *and*
bump `catalog_version`. The bump is what makes existing installations
re-verify rather than trusting a verification recorded against the version
you just withdrew.

---

## Adding a platform to the automatic matrix

Both of these, not either:

1. **A captured fixture** in `tests/local_models/machines.py`, built from
   real (redacted) tool output on that platform, and inventory assertions
   in `test_inventory.py`. No test may probe CI's actual hardware.
2. **A recorded end-to-end validation**: setup, download, start, smoke
   test, and a real reading, with the runtime and catalogue versions and
   the observed peak memory and timings. Add it to the table below.

Then add the build to `runtimes.yaml` and the platform to
`assessment.VALIDATED_PLATFORMS`.

### Recorded validations

| Platform | Runtime | Model | Result | Notes |
|---|---|---|---|---|
| Linux x86-64, 32 GB, CPU only | llama.cpp b10331 (ubuntu-x64) | Qwen3-4B Q4_K_M | **Pass** | Download, digest, extract, qualify, start on 127.0.0.1, smoke test: daily reading 93.2 s, natal summary 49.8 s, cosmos summary 37.7 s. |
| macOS Apple Silicon | — | — | **Not run** | Needs hardware. |
| Windows x86-64 (CPU) | — | — | **Not run** | Needs hardware. |
| Windows x86-64 (NVIDIA/Vulkan) | — | — | **Not run** | Needs hardware. |
| Linux x86-64 (NVIDIA/Vulkan) | — | — | **Not run** | Needs hardware. |

Record the exact runtime and catalogue versions and the observed peak
memory and timings. Never record a machine identifier, hostname, or
username.

### Evaluation runs

The harness itself has been exercised end to end against a live model.
Recorded here because it is evidence about *the harness*; it is not yet an
`evidence_id`, because peak memory and the rubric were not recorded and
the gate therefore (correctly) did not pass.

**Qwen3-4B Q4_K_M, llama.cpp b10331, Linux x86-64 32 GB, CPU only:**

| Metric | Value |
|---|---|
| Cases succeeded | 7 / 7 |
| Schema-valid on first pass | 86% (6 / 7) |
| Repair turn fired | 14% (1 / 7) |
| Supplied facts dropped | none |
| Control tokens or chain-of-thought leaked | none |
| Register distinctness | 0.75 – 0.84 |
| Median generation rate | 10.9 tokens/second |
| Typical reading length | 700 – 840 completion tokens |

Two observations worth carrying forward:

- **One case truncated at the output limit and recovered.** The
  `register_separation` fixture's first reply ran to 2191 completion
  tokens against `SYZYGY_MAX_OUTPUT_TOKENS = 1536`, was cut off, failed
  validation, and the repair turn produced a valid, shorter reading. That
  is the repair path doing exactly its job, and the cap staying where it
  is keeps readings the length the interface is built for — but it cost
  231 s instead of ~65 s, so a model that does this *often* should be
  visible in `repair_rate` rather than shrugged at.
- **A processor-only machine is genuinely slow.** ~65 s for a reading at
  ~11 tokens/second. The wizard says so before anything is downloaded;
  the figure above is what "slow" means in practice.

The gate did not pass, and reported precisely why: peak memory was not
measured, and the licence review was not passed on the command line. That
is the intended behaviour — the gate cannot be satisfied by running the
harness alone.

---

## Automated freshness checks

A check may open an issue saying "llama.cpp b10500 exists" or "the
publisher pushed a new revision". It may **not** rewrite a pin, edit a
recommendation, or change `support_status`. Every one of those is a
reviewed change with a test run and, for a new platform, a validation
result behind it.
