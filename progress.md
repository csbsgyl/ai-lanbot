## 2026-07-04 - Task: Download LangBot source for secondary development
### What was done
- Downloaded the LangBot `master` source snapshot from GitHub as a ZIP archive because direct `git clone` / `git fetch` repeatedly timed out or reset.
- Expanded the archive into `D:\ai-lanbot`, removed temporary archive/extract files, and cleaned the incomplete `.git` left by failed network fetches.
- Initialized a new local Git repository and set `origin` to `https://github.com/langbot-app/LangBot.git` for future upstream reference.

### Testing
- Verified key project files and directories exist: `AGENTS.md`, `pyproject.toml`, `src`, and `web/package.json`.
- Verified temporary download artifacts `LangBot-master.zip` and `_extract_langbot` were removed.
- Verified the Git remote is set to the upstream LangBot repository.

### Notes
- `D:\ai-lanbot\*`: imported the upstream LangBot source snapshot for local secondary development.
- `D:\ai-lanbot\.git`: created a fresh local Git repository after the original clone/fetch left an unusable partial repository.
- `D:\ai-lanbot\progress.md`: added this task log entry required by the repository workflow.
- Rollback: delete `D:\ai-lanbot` or remove the import baseline commit with `git reset --hard HEAD~1` after a baseline commit exists.

## 2026-07-04 - Task: Publish LangBot secondary development repository to GitHub
### What was done
- Created the private GitHub repository `csbsgyl/ai-lanbot` for secondary development and remote deployment.
- Changed the local `origin` remote to `https://github.com/csbsgyl/ai-lanbot.git`.
- Preserved the original upstream LangBot repository as the `upstream` remote.
- Renamed the local branch to `main` and pushed it to the new GitHub repository.

### Testing
- Verified `git push -u origin main` completed successfully.
- Verified `origin` points to `https://github.com/csbsgyl/ai-lanbot.git`.
- Verified `upstream` points to `https://github.com/langbot-app/LangBot.git`.

### Notes
- `D:\ai-lanbot\.git\config`: updated repository remotes so local development pushes to the user's GitHub repository while retaining the original upstream remote.
- `D:\ai-lanbot\progress.md`: appended this publish log entry.
- Rollback: remove the GitHub repository `csbsgyl/ai-lanbot` from GitHub, or locally restore the original remote with `git remote remove origin; git remote rename upstream origin`.

## 2026-07-04 - Task: Prepare public fork attribution and one-click deployment
### What was done
- Added clear fork attribution at the top of the English and Chinese README files, including upstream and fork repository links.
- Added public fork notice documentation and one-click deployment documentation.
- Added a Linux one-click deployment script that installs Docker when needed, downloads or updates this fork, builds local Docker images from source, and starts LangBot with Docker Compose.
- Added automatic GitHub direct-download detection and fallback to `https://github.xiaohangyun.org` for repository archive downloads; the README command also falls back to the accelerator when fetching the script itself.
- Added a Docker Compose local-build override so deployments use this fork's source instead of the upstream `rockchin/langbot` image.
- Updated Dockerfile `nsjail` source retrieval to use release archive downloads with accelerator fallback instead of a direct GitHub git clone.

### Testing
- Ran `bash -n scripts/one-click-deploy.sh` with Git Bash successfully.
- Verified `https://github.xiaohangyun.org` supports raw GitHub file proxying and GitHub archive tarball proxying.
- Verified accelerated `nsjail` archive download returns HTTP 200.
- Ran a content-level secret scan; only documented example secrets and test fixture tokens were found.
- Docker runtime verification was not run locally because Docker is not installed on this workstation.

### Notes
- `D:\ai-lanbot\README.md`: added fork attribution and the one-click Linux deployment command.
- `D:\ai-lanbot\README_CN.md`: added Chinese fork attribution and the one-click Linux deployment command.
- `D:\ai-lanbot\docs\FORK_NOTICE.md`: documented upstream attribution, license preservation, and fork-specific changes.
- `D:\ai-lanbot\docs\ONE_CLICK_DEPLOY.md`: documented one-click deployment behavior, optional variables, and maintenance commands.
- `D:\ai-lanbot\scripts\one-click-deploy.sh`: added automated Linux deployment with direct GitHub and accelerator fallback logic.
- `D:\ai-lanbot\docker\docker-compose.local-build.yaml`: added a source-build compose override for this fork.
- `D:\ai-lanbot\Dockerfile`: changed `nsjail` source retrieval to archive download with accelerator fallback.
- `D:\ai-lanbot\pyproject.toml`: updated repository metadata for this fork while preserving the upstream link.
- `D:\ai-lanbot\progress.md`: appended this task log entry.
- Rollback: revert this task with `git revert <commit>` after it is committed, and set the GitHub repository visibility back to private if needed.

## 2026-07-04 - Task: Make GitHub repository public and verify accelerated access
### What was done
- Changed `csbsgyl/ai-lanbot` from private to public on GitHub.
- Verified anonymous public access through the GitHub API.
- Verified accelerated anonymous access through `https://github.xiaohangyun.org` for README, the one-click deployment script, and the main branch tarball.

### Testing
- GitHub API reported `private=false` and `visibility=public` for `csbsgyl/ai-lanbot`.
- `https://github.xiaohangyun.org/https://raw.githubusercontent.com/csbsgyl/ai-lanbot/main/README_CN.md` returned HTTP 206.
- `https://github.xiaohangyun.org/https://raw.githubusercontent.com/csbsgyl/ai-lanbot/main/scripts/one-click-deploy.sh` returned HTTP 206.
- `https://github.xiaohangyun.org/https://github.com/csbsgyl/ai-lanbot/archive/refs/heads/main.tar.gz` returned HTTP 200.
- Downloaded the remote deployment script through the accelerator and verified it with `bash -n`.

### Notes
- `GitHub repository settings`: changed visibility to public for `csbsgyl/ai-lanbot`.
- `D:\ai-lanbot\progress.md`: appended this public-access verification log entry.
- Rollback: change repository visibility back to private in GitHub repository settings or via GitHub API with `private=true`.
