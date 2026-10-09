<div align="center">

<a href="https://typing233.github.io/super-aide/"><img src="https://raw.githubusercontent.com/typing233/super-aide/main/website/assets/logo.png" width="88" height="88" alt="Super Aide"></a>

# Super Aide

**Press a key. Say one thing. Done.**

A Windows assistant that sees your screen. Ask about anything on it, or let it do the work.<br>
It drives **Claude Code** and **Codex** and picks the right engine, model and effort for you.

**English** · [简体中文](README.zh-CN.md)

[![Latest release](https://img.shields.io/github/v/release/typing233/super-aide?label=release&color=5B8CFF)](https://github.com/typing233/super-aide/releases/latest)
[![MIT license](https://img.shields.io/badge/license-MIT-9B6BFF)](https://github.com/typing233/super-aide/blob/main/LICENSE)
[![Windows 10 | 11](https://img.shields.io/badge/Windows-10%20%7C%2011-555)](#install)

**[Website](https://typing233.github.io/super-aide/)** · **[Download for Windows](https://github.com/typing233/super-aide/releases/latest/download/SuperAideSetup.exe)** (about 100 KB)

</div>

https://github.com/user-attachments/assets/cc6cc785-44b5-4b67-bc15-64c983eecea4

## What it does

### Sees what you see

The moment you ask, it reads the exact text of every window — even the parts scrolled out of view — plus a screenshot and any area you select. No more pasting context.

<img src="https://raw.githubusercontent.com/typing233/super-aide/main/website/assets/shots/see-en.webp" width="100%" alt="Super Aide reading the exact text of every window, including notes scrolled out of view">

### Ask — `Alt+Q`

One sentence about anything on screen. The answer leads with the conclusion and shows up right where you're working. Ask mode is read-only: it can read files and run read-only diagnostics, but it never changes your PC.

<img src="https://raw.githubusercontent.com/typing233/super-aide/main/website/assets/shots/ask-en.webp" width="100%" alt="An answer card under a terminal explaining that pandas isn't installed, with the fix">

### Act — `Alt+W`

Say what you want done — command line, files, desktop apps, web pages. It reports the result and how to undo it. Press `Esc` to stop it at any time, and keep using your PC while it works.

<img src="https://raw.githubusercontent.com/typing233/super-aide/main/website/assets/shots/act-en.webp" width="100%" alt="The script runs after Alt+W; result notifications stack up in the corner">

### Shows you where to click

Rather do it yourself? It circles where to click, numbered in order, right on your screen. Step-by-step answers dock to the edge of the screen so you can follow along.

<img src="https://raw.githubusercontent.com/typing233/super-aide/main/website/assets/shots/guide-en.webp" width="100%" alt="Numbered marks on a print dialog: choose Save as PDF, then click Save">

### Claude Code + Codex, picked for you

Every request gets the engine, model and reasoning effort that fits — DeepSeek Harness works too. You never describe the context or pick a model. Success comes first: a faster or cheaper setup is only used once it's proven just as good, and pitfalls it hit before come back to mind in similar situations.

<img src="https://raw.githubusercontent.com/typing233/super-aide/main/website/assets/shots/route-en.webp" width="100%" alt="Requests routed to Claude Code or Codex, each with its own model and effort">

### Improves itself

When a task fails, you stop it with `Esc` and say it got something wrong, you click 👎, or you leave a suggestion in Settings, it uses Claude Code (Opus 5.5 · max) to find the cause and improve its own code; once the tests and an independent review pass, you confirm before it applies. If you like, stable improvements can be contributed upstream under your GitHub account.

<img src="https://raw.githubusercontent.com/typing233/super-aide/main/website/assets/shots/evolve-en.webp" width="100%" alt="The self-improvement panel: cause found, code changed, tests and review passed, applied">

### English / 中文

The UI follows your Windows language and can be switched in Settings; it answers in the language you ask in.

## Install

Needs 64-bit Windows 10 (1809 or later) or Windows 11.

1. Download **`SuperAideSetup.exe`** (about 100 KB) from the [website](https://typing233.github.io/super-aide/) or [Releases](https://github.com/typing233/super-aide/releases/latest).
2. Run it and click Install. It downloads, checks and installs the runtime (about 600 MB the first time, takes a few minutes; it switches to mirrors automatically when the official sources are slow or blocked), then opens Super Aide. No admin rights needed.

> The installer isn't code-signed yet, so Windows may say "Windows protected your PC": click **More info → Run anyway**.

Once installed it behaves like any app: open it from the Start menu, uninstall it from Settings → Apps.

**From source** (developers): `git clone`, then double-click `install.cmd` in the repo root (or run `powershell -ExecutionPolicy Bypass -File scripts\install.ps1`).

## First launch: the setup check

Super Aide uses Claude Code's and Codex's own model configuration, so before you start it checks that they're installed and set up:

| Situation | What the setup window does |
|---|---|
| Claude Code or Codex is missing, and DeepSeek Harness is installed | Asks whether to install them (recommended). You can skip that and use DeepSeek Harness |
| Something is missing and there's no DeepSeek Harness | Installs it automatically from the official npm packages, falling back to a mirror; installs a portable Node.js first if Node.js 22+ isn't there |
| Installed but no model configured | Pick one: **Sign in with your account** (a sign-in window opens; finish in the browser) or **Custom endpoint** (address, key, optional model — tested before saving) |
| Everything is ready | Starts right away |

You can start once at least one engine works. Reopen the check any time from **Settings → General → Setup check**.

A custom endpoint is written into each tool's own config (with a `*.super-aide.bak` backup; other settings and comments are kept): Claude Code → `env` in `~/.claude/settings.json`; Codex → provider `model_providers.super_aide` in `~/.codex/config.toml` with the key in the user environment variable `SUPER_AIDE_CODEX_API_KEY`; DeepSeek Harness → `DEEPSEEK_API_KEY`.

### About DeepSeek Harness

[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (DSH) is an optional alternative engine. Super Aide recognizes both its desktop app and the npm package `@deepseek-ai/dsh`. Ask mode runs in its read-only sandbox; Act mode has full access. Because Super Aide's sessions contain what's on your screen, DSH's default session-log upload is turned off for them (your own DSH settings are untouched).

## Use

- **Open**: "Super Aide" in the Start menu. It has no main window and lives in the tray; when you open it, a notification says so. If you checked "Start with Windows" during install, it's ready after every boot.
- `Alt+Q` to ask, `Alt+W` to act (changeable in Settings). The input box only appears when you press a hotkey.
- **Settings**: hotkeys, theme, **language** (follow system / 中文 / English), apps it never looks at, which models each engine may use, autostart.
- **Updates**: Settings → General → Version. It checks when you open Settings; click Update and Super Aide quits, the installer installs the new version and reopens it. Settings and history are kept.

## Self-improvement

- **When**: a task fails (network or sign-in problems don't count); you press `Esc` during an action and say what the assistant got wrong (no answer means it wasn't its fault); you click 👎; or you write a suggestion in **Settings → Advanced**.
- **How**: it first checks whether this is a defect it can fix itself. If so, it changes the code in a working copy, adds tests, runs the whole test suite itself, then has a separate session review the change. By default it uses Claude Code + Opus 5.5 (maximum effort); if that isn't available, it uses the best tool and model on your PC.
- **You apply it**: you get a notification when it's ready; open it to see what changed, then click Apply to switch to the new version (Super Aide restarts in a few seconds). If the new version doesn't start, the previous one is restored automatically, and you can undo the latest improvement at any time. The version becomes something like `0.2.0+aide.1`; official updates still show up, and afterwards your local improvements are carried over to the new version (again with your confirmation).
- **Meanwhile**: it reminds you to keep your PC on and online, and you can keep using it. Progress shows in the first line of the tray menu and in Settings. It resumes after network drops and restarts. One improvement at a time; later ones queue and first check whether an earlier improvement already fixed them.
- **Community contributions** (optional): Settings → Advanced → Contribute to the community, then sign in with GitHub once. Improvements that run stably for a day are submitted as pull requests under your account — code changes only, no screen content or logs; anything that looks like personal info isn't submitted automatically. The maintainer reviews before merging; see [CONTRIBUTING.md](CONTRIBUTING.md).
- Self-improvement data lives in `~/.super_aide/evolve/`: jobs, the working copy, built packages. The conversation and logs used for analysis go only to the model service you configured and are deleted when the job ends; only the conclusion and the patch are kept.

## Privacy

Super Aide's own data lives in `~/.super_aide/`. Screen content is only sent to the model service you configured. Apps on the "never look at" list are blacked out in screenshots and their text isn't read.

## Uninstall

Windows **Settings → Apps → Super Aide → Uninstall** (optionally delete your data too). Claude Code and Codex are separate tools and stay installed. From-source installs: `uv tool uninstall super-aide`.

## Development

```powershell
uv sync
uv run python -m super_aide
uv run python -m pytest -q
powershell -ExecutionPolicy Bypass -File scripts\build_installer.ps1
```

The website lives in `website/` and is published to GitHub Pages by `.github/workflows/pages.yml` (which also puts the latest installer on the site). The promo film and the screenshots are rendered from `video/` with Remotion — see [video/README.md](video/README.md).

UI text is written in Chinese first: `tr("中文")` in Python with English in `src/super_aide/locales/en_*.py`; `data-i18n` / `I18N.t("中文")` in the web pages with English in `src/super_aide/ui/web/i18n-en.js`. `tests/test_i18n.py` checks every string has an English version.

Releases: push a `v*` tag (`git tag v0.2.0 && git push origin v0.2.0`) and `.github/workflows/release.yml` tests, builds the wheel and the installer, creates the GitHub Release and publishes to PyPI via Trusted Publishing (one-time setup: a PyPI pending publisher for `super-aide` with workflow `release.yml` and environment `pypi`, plus a `pypi` environment in the GitHub repo).

## License

[MIT](LICENSE)
