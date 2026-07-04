# Fork Notice

This repository is a secondary-development fork of [langbot-app/LangBot](https://github.com/langbot-app/LangBot).

## Upstream

- Original project: `langbot-app/LangBot`
- Upstream repository: <https://github.com/langbot-app/LangBot>
- License: Apache License 2.0, preserved in `LICENSE`

## This Fork

- Fork repository: `csbsgyl/ai-lanbot`
- Purpose: secondary development, deployment packaging, and deployment convenience for self-hosted users.
- Deployment commands, Docker image references, CI links, and user-facing source links target `csbsgyl/ai-lanbot`.
- Current fork-specific additions:
  - Public fork notice and deployment documentation.
  - Source-build Docker Compose override so deployments use this fork's code instead of the upstream image.
  - One-click Linux deployment script with automatic GitHub direct/accelerated archive download selection.
  - Automatic Docker base-image accelerator selection through `https://docker.xiaohangyun.org` when Docker Hub direct access is unavailable.

## Attribution

The original LangBot copyright, license, and upstream links are retained. Fork-specific changes should be described in `progress.md` and, when they affect usage or deployment, in `docs/`.
