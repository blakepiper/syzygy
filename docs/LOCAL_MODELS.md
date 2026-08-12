# Running a model on your own computer

Syzygy can have the interpretations written by a model running on your
machine, instead of by a company's servers. This page is the whole story:
what gets downloaded, where it goes, what leaves your computer and what
doesn't, and what to do when something goes wrong.

You do not need to know what any of the following words mean to use this.

---

## The short version

1. Open Syzygy, press **`M`**, choose **LOCAL MODEL**.
2. Choose **SET UP A LOCAL MODEL FOR ME**.
3. Read what it says, press the button at the bottom of each step.
4. Somewhere between five minutes and an hour later — mostly download
   time — readings are written on your own computer.

You can stop at any point, and nothing is downloaded until you have seen
an itemised list of exactly what will be fetched and where it will go.

If you would rather not use a terminal at all, that is the whole
procedure; the rest of this page is detail and troubleshooting.

---

## What actually gets downloaded

Two things, once:

**The model.** A single file, between 2.3 GB and 9 GB depending on which
one you choose. It contains the language model's weights — the thing that
writes the words. Syzygy downloads it from the publisher (currently Qwen,
on Hugging Face) and checks it against a published checksum before using
it.

**The runner.** A small program (15–35 MB) called llama.cpp that loads the
model file and answers Syzygy's questions. It is downloaded from its
official GitHub release, digest-checked the same way, and unpacked into
Syzygy's own folder.

Both are put in Syzygy's data directory, not into your system:

```
<your data directory>/local_models/
├── runtime/     the runner
├── gguf/        the model file
├── partial/     downloads in progress
├── logs/        short, anonymised logs of the model starting
└── state.json   which port it used, that sort of thing
```

`<your data directory>` is `~/Library/Application Support/syzygy` on
macOS, `%LOCALAPPDATA%\syzygy` on Windows, and
`~/.local/share/syzygy` on Linux. `syzygy model local status` prints the
exact paths.

Nothing is installed system-wide. Nothing asks for your password. Removing
the folder removes everything Syzygy downloaded.

---

## The privacy boundary

This is the reason to do any of it.

**Before setup:** Syzygy contacts GitHub and Hugging Face to fetch the two
files above. It sends nothing about you — no chart, no birth data, no
name, no machine inventory. Downloading a file is the entire interaction.

**After setup:** nothing leaves your computer at all. The model runs as a
program on your machine, listening only on `127.0.0.1`, which is an
address no other computer can reach — not even another computer on your
own network. Your chart, your card, and the words written about them stay
on the disk they are already on.

Compare with the hosted providers (OpenAI, Anthropic): those send the
day's reading context to their servers on every single reading. Both are
supported; they are different bargains, and Syzygy says which one you are
making.

**What Syzygy inspects about your computer:** operating system and
version, processor model and core count, installed and available memory,
free disk space, and graphics hardware. All of it is read locally to
decide which model will fit. None of it is transmitted anywhere. The
"copy diagnostics" button shows you the entire report, with your username,
home directory, and hostname removed.

---

## Which computers this works on

| Your computer | What you get |
|---|---|
| Mac with Apple Silicon (M1 and later) | Fast. Uses the built-in graphics acceleration. |
| Mac with an Intel processor | Works, slowly. Processor only. |
| Windows, 64-bit Intel/AMD | Fast if you have a graphics card Vulkan can use, otherwise slow but working. |
| Linux, 64-bit Intel/AMD | Same as Windows. |
| Anything else | Syzygy will say so, and offer to use a server you set up yourself. |

**Memory is what decides.** Roughly:

| Installed memory | What to expect |
|---|---|
| under 8 GB | Not enough. Use demonstration mode or a hosted provider. |
| 8–12 GB | The smaller model, and it will be slow. |
| 16 GB | The recommended model runs comfortably. |
| 32 GB and up | Any of them, including the largest. |

Syzygy works this out for you and shows the arithmetic — how much the
weights need, how much the working memory needs, and how much it is
leaving free for your operating system. It is deliberately pessimistic. A
model that technically fits and then makes your computer swap is a worse
outcome than being told to pick the smaller one.

---

## The three choices

When it recommends a model you will see up to three:

- **Faster/smaller** — downloads quickest, needs least memory, writes
  shorter and plainer readings.
- **Recommended** — the default. The best balance for a normal machine.
- **Higher quality** — longer, more specific readings; a much larger
  download and noticeably slower.

Syzygy will *downgrade* on its own if the recommended one will not fit. It
will never *upgrade* on its own, because the cost of guessing wrong on a
nine-gigabyte download is yours, not its.

Press **`T`** on any of these screens for the technical details — the
exact file, its checksum, quantization, context length, and the llama.cpp
version required.

### About "not yet measured"

At the time of writing, every model in Syzygy's list is marked
**provisional**. That means Syzygy has pinned the exact file, checked its
licence, and knows precisely how much memory it needs — but has not yet
run its own quality evaluation on hardware like yours. When it says
"Syzygy has not yet measured how well it writes readings on hardware like
yours", that is a true statement rather than a disclaimer, and the
confidence shown will be "medium" rather than "high".

---

## Licences

The models currently offered are published by Qwen under Apache-2.0, and
llama.cpp is MIT. Both are compatible with Syzygy's own AGPL-3.0 licence.
The wizard shows the licence and links to it before downloading, and
records that you accepted it for that exact model at that exact catalogue
revision. If a future Syzygy update changes either, it will ask again
rather than assume.

---

## Afterwards

Syzygy starts the model when it needs it and stops it when you quit. There
is nothing to run, nothing to keep open, and nothing left running in the
background after you close the application.

If Syzygy is ever closed the hard way — a crash, a killed terminal — the
model server can survive it. The next time Syzygy needs the model it looks
for that server first: if it is still answering and still serving the same
model in the same way, Syzygy takes it over and uses it, rather than
loading several gigabytes a second time. If it is wedged, or serving
something else, Syzygy stops it and starts a fresh one. Either way you end
up with one server, and quitting stops it. Syzygy only ever signals a
process it can still prove is its own — matching its own runner, its own
model file — so a process id that has since been reused by something else
is left strictly alone. `syzygy model local status` shows what it found,
and `syzygy model local stop` is always available if you would rather do
it yourself.

The first reading in a session takes longer than the rest, because the
model has to be read from disk into memory. On a processor-only machine, a
reading may take a minute or two; with graphics acceleration, seconds.

**Demonstration mode versus a real reading.** If no model is set up — or
if setup fails, or the model can't start — Syzygy uses its built-in
demonstration text. That text is *canned*: it is the same regardless of
your chart, your transits, and your card. It exists so the ritual is never
broken, not so you can read it as a reading. The interface always says
which one you are looking at.

---

## Managing the files

```
syzygy model local status        # what's configured, and where
syzygy model local doctor        # is it healthy? (--deep re-checks the checksum)
syzygy model local list          # every model file, and who owns it
syzygy model local use-file PATH # use a .gguf you already have
syzygy model local remove PATH   # delete one Syzygy downloaded
syzygy model local start         # run the server by hand (Ctrl-C stops it)
syzygy model local stop          # stop one left running
```

### Using a model file you already have

If you have downloaded a `.gguf` yourself:

```bash
syzygy model local use-file ~/models/some-model.gguf
```

Syzygy reads its header — architecture, layers, trained context length,
whether it carries a chat template — decides whether it will fit, and
tells you. It does **not** load the weights to do this, and it does not
search your disk for models: you say which file, always. The file stays
exactly where it is, and Syzygy will never move, rewrite, or delete it.

You still need a runner. Either let `syzygy model setup-local` install
one, or run your own server (see the advanced section below).

`remove` only ever deletes a file Syzygy downloaded itself. A model file
you pointed Syzygy at, a llama.cpp you installed yourself, and any other
program's model cache are all refused — by design, and not overridable.

**Updating.** New model and runner versions arrive with new Syzygy
releases, never by silently tracking the latest upstream build. When one
does, Syzygy notices its verification is out of date and offers to check
it again.

---

## If it goes wrong

Every failure in the wizard says what happened and what to do about it.
The common ones:

**"Not enough free disk space."** The number needed is shown. Free some
and press try again — a partly-finished download is kept and resumes.

**"The model needed more memory than this computer could give it."** Go
back and choose the smaller model. If the smallest one also fails, this
computer cannot run one locally; a hosted provider or demonstration mode
are the alternatives.

**"The download didn't match its published checksum."** Syzygy discarded
it, which is the correct response. Usually a bad connection; try again.
If it keeps happening, something between you and the publisher is
modifying the file.

**"Nothing answered" / "the model didn't finish starting in time."** Press
`T` for the runner's own output, and `D` to copy an anonymised diagnostic
report.

**"The graphics acceleration this build needs isn't working here."** Your
driver is older or different than the build expects. Choosing the
processor-only route is slower but reliable.

**A reading that sits on "INTERPRETING" for a while.** That is normal for
a local model: the first answer after starting the server includes loading
the weights, and the counter beside the label tells you it is still alive.
Nothing is being decided while you wait — the card, and the Oracle's cast,
were committed before the model was asked anything.

If you want to watch what the machine is actually doing during that wait,
run Syzygy with `SYZYGY_LOG_FILE=~/syzygy.log`. Everything the libraries
log — including the health poll of a server that is still starting — goes
to that file. It never goes to the screen: the interface owns the terminal
while it is running, and a log line printed over it stays there.

Nothing that goes wrong here affects your readings. A card already drawn
stays drawn, a reading already written stays written, and the ritual keeps
working.

---

## Advanced: use a server you run yourself

If you already run llama.cpp, LM Studio, Ollama, or anything else that
speaks the OpenAI-compatible API, Syzygy can simply talk to it.

Syzygy checks the conventional local ports during setup and will offer to
use anything compatible it finds. To point it somewhere specific: press
**`M`**, choose **LOCAL MODEL**, then **USE AN EXISTING SERVER
(ADVANCED)**, and enter the base URL.

A minimal server by hand:

```bash
llama-server \
  --model /path/to/model.gguf \
  --host 127.0.0.1 --port 8080 \
  --ctx-size 8192 \
  --n-predict 1536
```

Then point Syzygy at `http://127.0.0.1:8080/v1`.

Syzygy needs the server to support `response_format` with a JSON schema —
a current llama.cpp build does. It checks before switching over, and says
so clearly if it doesn't. Syzygy will never modify, restart, or upgrade a
server or binary you manage yourself.

From the command line:

```bash
syzygy model use llama_cpp --base-url http://127.0.0.1:8080/v1 --model my-model
```

---

## Setting up without the interface

`syzygy model setup-local` runs the same steps, printed. In a terminal it
asks before downloading; without one (a script, CI) it prints a read-only
inventory and plan and does nothing, so it can never hang waiting for an
answer nobody is there to give.

```bash
syzygy model setup-local                    # interactive
syzygy model setup-local --tier faster      # pick a size
syzygy model setup-local --yes              # accept the plan and licence
```
