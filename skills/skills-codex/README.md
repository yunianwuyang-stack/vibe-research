# `skills-codex`

Codex-native mirror and adaptation layer for the main Vibe Research `skills/` package.

## Scope

- Base mirror coverage: all `67` mainline skills under `skills/`
- Support directory: `shared-references/`
- Default reviewer contract for reviewer-heavy skills:
  - round 1: `spawn_agent`
  - follow-up: `send_input`
  - reasoning effort: `xhigh`
- Optional overlays:
  - `skills-codex-claude-review`
  - `skills-codex-gemini-review`

This package is still an appendage to the Claude mainline, not a separate Codex-first product line.

## Recommended Install

Project-local install is the default path for Codex:

```bash
git clone https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep.git ~/vibe_repo
cd ~/your-project

bash ~/vibe_repo/tools/install_vibe_codex.sh .
```

This creates a flat managed layout:

```text
.agents/skills/<skill-name> -> ~/vibe_repo/skills/skills-codex/<skill-name>
.vibe/installed-skills-codex.txt
AGENTS.md   # managed Codex block
```

Reconcile after upstream changes:

```bash
cd ~/vibe_repo && git pull
bash ~/vibe_repo/tools/install_vibe_codex.sh ~/your-project --reconcile
```

Uninstall only managed Codex entries:

```bash
bash ~/vibe_repo/tools/install_vibe_codex.sh ~/your-project --uninstall
```

## Optional Overlays

Install the base first, then choose an overlay:

```bash
bash ~/vibe_repo/tools/install_vibe_codex.sh ~/your-project --reconcile --with-claude-review-overlay
```

```bash
bash ~/vibe_repo/tools/install_vibe_codex.sh ~/your-project --reconcile --with-gemini-review-overlay
```

Overlays only replace reviewer routing. They do not replace the base mirror or the executor model.

## Copy Install and Update

If you intentionally use a copied Codex install instead of managed project symlinks:

```bash
mkdir -p ~/.codex/skills
cp -a ~/vibe_repo/skills/skills-codex/. ~/.codex/skills/
```

Update copied installs with:

```bash
bash ~/vibe_repo/tools/smart_update_codex.sh
bash ~/vibe_repo/tools/smart_update_codex.sh --apply
```

For a copied project-local Codex install:

```bash
bash ~/vibe_repo/tools/smart_update_codex.sh --project ~/your-project
bash ~/vibe_repo/tools/smart_update_codex.sh --project ~/your-project --apply
```

`smart_update_codex.sh` refuses symlink-managed installs and redirects them to `install_vibe_codex.sh --reconcile`.

## Non-Degrading Skills

The following Codex skills must not silently degrade when their required capability is missing:

- `comm-lit-review`
- `research-lit`
- `paper-poster`
- `pixel-art`

If the required source, reviewer, or local preview capability is unavailable, the skill should stop and tell the user what to configure.
