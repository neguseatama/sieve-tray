**English** | [日本語](README.ja.md)

# Sieve Tray v0.3.0

**A general-purpose observation tool — a desktop front-end for the Sieve series**

> Combines [Sieve Lens](https://github.com/neguseatama/sieve-lens)'s invisible-content
> observation, [Sieve Scope](https://github.com/neguseatama/sieve-scope)'s code
> similarity detection, and [Sieve Referee](https://github.com/neguseatama/sieve-referee)'s
> text paraphrase detection into a single desktop app. Point it at a folder of
> submissions and it detects and reports, in one pass, documents containing
> invisible content or hidden prompts, code pairs with suspicious structural
> similarity, and text pairs that look paraphrased or reused.

[![Test](https://github.com/neguseatama/sieve-tray/actions/workflows/test.yml/badge.svg)](https://github.com/neguseatama/sieve-tray/actions/workflows/test.yml)
[![Release](https://github.com/neguseatama/sieve-tray/actions/workflows/release.yml/badge.svg)](https://github.com/neguseatama/sieve-tray/actions/workflows/release.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)

---

## 💡 Concept

[Sieve Lens](https://github.com/neguseatama/sieve-lens) answers "does this
document contain something a human can't see but a parser can?".
[Sieve Scope](https://github.com/neguseatama/sieve-scope) answers "do these two
source files share suspiciously similar logic, beyond coincidence?".
[Sieve Referee](https://github.com/neguseatama/sieve-referee) answers "does
this text say the same thing as that one, just reworded?". All three are
zero-dependency, deterministic observation engines in the Sieve series — but
checking a folder of submissions by hand meant running separate tools and
cross-referencing the output yourself.

**Sieve Tray** removes that step. Point it at a directory containing one
subfolder per submission, and it automatically routes each file to the right
engine: documents go to Sieve Lens, `.py` files go to Sieve Scope's pairwise
comparison, and plain-text files (`.txt`/`.md`) additionally go to Sieve
Referee's pairwise paraphrase comparison. Results land in a single window,
with local history so nothing has to be re-run, and a detail view showing
exactly which observation axis fired and why — never a bare verdict, only
what the underlying engines actually observed.

> Like the rest of the Sieve series, this is an **observation tool, not a
> judgment tool**. A flagged item means "this deserves a human look", not
> "this is confirmed misconduct".

---

## 🔥 Key Features

- **One folder in, everything checked** — routes `.py` files to Sieve Scope,
  plain-text files (`.txt`, `.md`) additionally to Sieve Referee, and all
  documents (including `.html`, `.docx`, `.pdf`, images) to Sieve Lens,
  automatically, by extension.
- **Background-threaded GUI** — scanning never freezes the window, even on
  large submission sets.
- **English and Japanese UI** — switch languages from the Settings dialog
  (English by default). Note: Sieve Referee's own explanation text for a
  flagged text pair is generated in Japanese regardless of UI language,
  since the engine's calibration is Japanese-specific; the detail dialog
  shows it labeled as such.
- **Sortable, filterable results** — click any column to sort; filter
  documents by filename and/or "flagged only"; filter code/text pairs by
  filename.
- **Detail dialog** — double-click any row to see the per-axis observation
  states and the underlying evidence/scores/reason the engine recorded, not
  just the mask string.
- **Local history** — every scan is saved to a local SQLite database
  (`~/.sieve_tray/history.db`); revisit a past run without re-scanning.
- **Configurable** — default export folder, history retention, and UI
  language are all adjustable from a Settings dialog.
- **Self-contained HTML export** — every result can be exported as a
  standalone HTML report, for sharing or archiving.
- **Runs entirely on your machine** — scanning happens 100% locally. Submission
  contents never leave your device: no cloud upload, no API calls involved.
- **Zero-dependency core** — the scanning engine (`sieve_tray.py`) itself
  uses only the Python standard library plus Sieve Lens / Sieve Scope /
  Sieve Referee. The GUI is an optional layer (`PySide6`) on top, kept
  separate so the core stays consistent with the rest of the Sieve series'
  "zero dependency, offline, deterministic" design.
- **Cross-platform desktop builds** — CI produces standalone Windows and
  macOS (Apple Silicon + Intel) apps via PyInstaller; no Python installation
  required to run them.

---

## 📦 Installation

### Option 1: Download a pre-built app (recommended)

No Python required. Download the build for your platform from the
[Releases page](https://github.com/neguseatama/sieve-tray/releases):

| Platform | Asset |
|---|---|
| Windows | `SieveTray-windows.zip` |
| macOS (Apple Silicon / M-series) | `SieveTray-macos-arm64.zip` |
| macOS (Intel) | `SieveTray-macos-intel.zip` |

Unzip and run `SieveTray.exe` / `SieveTray.app`. On first launch, macOS will
warn that the developer can't be verified (the app isn't code-signed yet) —
go to **System Settings → Privacy & Security** and click **Open Anyway**.
Windows SmartScreen may show a similar warning; choose **More info → Run
anyway**.

### Option 2: Install from source

```bash
git clone https://github.com/neguseatama/sieve-tray.git
cd sieve-tray
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[gui]"
python3 sieve_tray_gui.py
```

Requires Python 3.10–3.13 (PySide6 does not yet support 3.14).

Core only, no GUI (for CLI usage or scripting):

```bash
pip install -e .
```

---

## 💻 Quick Start

### GUI

1. Launch the app.
2. Click **Select Folder...** and pick a directory containing one subfolder
   per submission.
3. Click **Run Scan**.
4. Browse results in the **Documents**, **Code Pairs**, and **Text
   Similarity** tabs — sort by column, filter by filename, and double-click
   any row for the full per-axis breakdown.
5. Export a shareable report with **Export HTML Report**. Past runs are
   always available under the **History** tab.

(The interface language defaults to English; switch to Japanese from the
Settings dialog. Takes effect after restart.)

### CLI

```bash
python3 sieve_tray.py path/to/submissions -o report.html
```

Expects a directory of subdirectories, one per submission:

```
submissions/
    student_a/
        essay.docx
        solution.py
    student_b/
        essay.docx
        solution.py
```

### As a library

```python
from pathlib import Path
from sieve_tray import run_scan, render

result = run_scan(Path("submissions"), progress=print)
print(result.doc_results)   # path / mask / flagged / h_states / evidence
print(result.code_pairs)    # a / b / mask / h_states / scores
print(result.text_pairs)    # a / b / signal / mask / pattern_name / reason / h_states / scores

Path("report.html").write_text(render(result))
```

---

## 🔬 Testing

```bash
pip install -e . pytest
pytest -v
```

23 tests cover the core scan/render pipeline (including regression tests for
a CSS rendering bug and for Sieve Referee's paraphrase detection), the
history/settings storage layer (save / load / delete / retention pruning,
including migration from pre-Referee databases), and the i18n string tables
(English/Japanese key parity).

CI runs this suite on every push (Python 3.10 and 3.12, on Ubuntu), and
builds Windows/macOS desktop apps on every version tag.

---

## ⚠️ Known Limitations

1. **Code comparison is Python-only.** `.py` is the only extension routed to
   Sieve Scope; other languages are treated as plain documents (or ignored)
   for now.
2. **Text-similarity comparison is plain-text only.** `.txt`/`.md` are
   routed to Sieve Referee; rich formats (`.docx`, `.pdf`) are not
   currently extracted to plain text for this comparison, even though
   Sieve Lens still observes them individually.
3. **Sieve Referee's `reason` text is Japanese-only,** regardless of UI
   language, since the engine's similarity thresholds are calibrated for
   Japanese text. The detail dialog surfaces it labeled as such.
4. **Desktop builds are not code-signed.** Windows SmartScreen and macOS
   Gatekeeper will warn on first launch; this is expected for an unsigned
   build.
5. **This is an observation tool, not a judgment tool** (inherited from
   Sieve Lens, Sieve Scope, and Sieve Referee). A flag means "a human should
   look at this", not "this is confirmed misconduct".

---

## 📚 Related Projects

- [Sieve Lens](https://github.com/neguseatama/sieve-lens) — invisible-content
  observation engine (documents)
- [Sieve Scope](https://github.com/neguseatama/sieve-scope) — code
  similarity detection engine
- [Sieve Referee](https://github.com/neguseatama/sieve-referee) — text
  paraphrase / plagiarism detection engine

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.

---

## 👤 Author

* **Kai IWASAKI**
