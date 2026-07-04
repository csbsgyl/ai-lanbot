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

## 2026-07-04 - Task: Replace upstream pull and deployment links with fork-owned endpoints
### What was done
- Replaced remaining user-facing repository, clone, badge, contribution, issue, Docker image, Docker Compose, Kubernetes, CI, and test-environment references so deployment and collaboration paths target `csbsgyl/ai-lanbot`.
- Kept original `langbot-app/LangBot` only as fork attribution and upstream metadata, with explicit fork documentation stating deployment commands and user-facing source links belong to `csbsgyl/ai-lanbot`.
- Extended the one-click deployment flow to detect Docker Hub availability and automatically use `https://docker.xiaohangyun.org` for Docker base images when direct access is unavailable.
- Updated one-click deployment documentation to state that GitHub and Docker acceleration are detected automatically and do not require users to enter accelerator URLs.

### Testing
- Ran `D:\rj-gj\Git\bin\bash.exe -n scripts/one-click-deploy.sh` successfully.
- Ran `uv run pytest tests/unit_tests/provider/test_mcp_resources.py -q`: 8 tests passed.
- Ran `git diff --check` successfully.
- Verified `https://github.xiaohangyun.org/https://raw.githubusercontent.com/csbsgyl/ai-lanbot/main/README.md` can be fetched successfully.
- Verified `https://docker.xiaohangyun.org/v2/library/node/tags/list` contains `22-alpine` and `https://docker.xiaohangyun.org/v2/library/python/tags/list` contains `3.12.7-slim`.
- Verified `resolve_docker_image_prefix` captures `docker.xiaohangyun.org/library/` when Docker Hub direct access is unavailable, and captures a manually supplied `LANBOT_DOCKER_IMAGE_PREFIX` unchanged.
- Ran an upstream pull/deploy/image scan for `rockchin/langbot`, `git clone https://github.com/langbot-app/LangBot`, `RockChinQ/LangBot`, and `langbot-plugin-demo`; no active matches remained outside historical progress notes and fork attribution.
- Docker Compose runtime/build verification was not run because Docker is not installed on this workstation.

### Notes
- `D:\ai-lanbot\.github\pull_request_template.md`: updated contribution and CLA links to the fork repository.
- `D:\ai-lanbot\.github\workflows\build-dev-image.yaml`: changed dev image publishing to `csbsgyl/ai-lanbot`.
- `D:\ai-lanbot\.github\workflows\build-docker-image.yml`: changed release and prerelease image publishing to `csbsgyl/ai-lanbot`.
- `D:\ai-lanbot\.github\workflows\cla.yml`: moved CLA document and signature storage references to `csbsgyl/ai-lanbot`.
- `D:\ai-lanbot\.github\workflows\test-dev-image.yaml`: changed dev image smoke-test substitution to `csbsgyl/ai-lanbot:master`.
- `D:\ai-lanbot\Dockerfile`: added Docker base-image prefix support for accelerated base image pulls.
- `D:\ai-lanbot\README.md`: updated deployment, badge, release, star, contributor, and acceleration references for the fork.
- `D:\ai-lanbot\README_CN.md`: updated Chinese deployment, badge, release, star, contributor, and acceleration references for the fork.
- `D:\ai-lanbot\README_ES.md`: updated Spanish clone, badge, release, star, and contributor references for the fork.
- `D:\ai-lanbot\README_FR.md`: updated French clone, badge, release, star, and contributor references for the fork.
- `D:\ai-lanbot\README_JP.md`: updated Japanese clone, badge, release, star, and contributor references for the fork.
- `D:\ai-lanbot\README_KO.md`: updated Korean clone, badge, release, star, and contributor references for the fork.
- `D:\ai-lanbot\README_RU.md`: updated Russian clone, badge, release, star, and contributor references for the fork.
- `D:\ai-lanbot\README_TW.md`: updated Traditional Chinese clone, badge, release, star, and contributor references for the fork.
- `D:\ai-lanbot\README_VI.md`: updated Vietnamese clone, badge, release, star, and contributor references for the fork.
- `D:\ai-lanbot\docker\docker-compose.local-build.yaml`: added Docker base-image prefix build args and removed upstream image wording.
- `D:\ai-lanbot\docker\docker-compose.yaml`: changed service images to `csbsgyl/ai-lanbot:latest`.
- `D:\ai-lanbot\docker\kubernetes.yaml`: changed deployment images to `csbsgyl/ai-lanbot:latest`.
- `D:\ai-lanbot\docs\FORK_NOTICE.md`: documented that deployment, CI, image, and user-facing source references target this fork.
- `D:\ai-lanbot\docs\ONE_CLICK_DEPLOY.md`: documented automatic GitHub and Docker accelerator selection.
- `D:\ai-lanbot\docs\PYPI_INSTALLATION.md`: corrected the source checkout directory after cloning this fork.
- `D:\ai-lanbot\docs\review\mcp-resources-pr-2215-review.md`: updated the PR reference to the fork namespace.
- `D:\ai-lanbot\docs\service-api-openapi.json`: updated the license URL to the fork repository.
- `D:\ai-lanbot\scripts\one-click-deploy.sh`: added Docker Hub probing, Docker accelerator probing, and `.env` prefix writing for accelerated base image pulls.
- `D:\ai-lanbot\skills\skills\langbot-deploy\SKILL.md`: updated deploy clone commands to this fork and its checkout directory.
- `D:\ai-lanbot\skills\skills\langbot-plugin-dev\references\test-env-setup.md`: updated test environment images to `csbsgyl/ai-lanbot`.
- `D:\ai-lanbot\skills\skills\langbot-testing\cases\langbot-fake-provider-debug-chat-cross-pipeline-isolation.yaml`: updated issue references to the fork.
- `D:\ai-lanbot\skills\skills\langbot-testing\references\performance-reliability-testing.md`: updated issue references to the fork.
- `D:\ai-lanbot\src\langbot\__main__.py`: updated the startup open-source repository URL to this fork.
- `D:\ai-lanbot\tests\e2e\utils\process_manager.py`: updated the fallback test-build path away from the upstream namespace.
- `D:\ai-lanbot\tests\unit_tests\provider\test_mcp_resources.py`: updated repository URI test examples to the fork namespace.
- `D:\ai-lanbot\web\src\app\home\components\home-sidebar\HomeSidebar.tsx`: updated the web UI GitHub link to this fork.
- `D:\ai-lanbot\web\src\app\home\plugins\components\plugin-market\PluginMarketComponent.tsx`: updated plugin request links to this fork's issue entry.
- `D:\ai-lanbot\progress.md`: appended this task log entry.
- Rollback: before commit, run `git restore <file>` for the listed files; after commit, run `git revert <commit>` to undo this task as a single change set.

## 2026-07-04 - Task: Make one-click deployment faster and show post-deploy login guidance
### What was done
- Changed the one-click deployment default path to start from a prebuilt fork image instead of always building locally on the target server.
- Added runtime image detection for Docker Hub, the configured Docker accelerator, GHCR, and a clearly labeled source-build fallback.
- Added deployment failure diagnostics, an HTTP health check against `/api/v1/system/info`, and success output that shows local/remote URLs, `/register` first-admin setup, `/login`, and maintenance commands.
- Fixed the local source-build path so the Dockerfile fetches `nsjail` with its `kafel` submodule instead of failing on the source archive.
- Updated Docker image publishing workflows so main/release builds publish GHCR images, with Docker Hub publishing when Docker Hub secrets are configured.
- Updated deployment documentation and README guidance to state that fresh installs have no default username/password and must create the first administrator at `/register`.

### Testing
- Ran `D:\rj-gj\Git\bin\bash.exe -n scripts/one-click-deploy.sh` successfully.
- Ran `git diff --check` successfully.
- Verified `https://github.xiaohangyun.org/https://raw.githubusercontent.com/csbsgyl/ai-lanbot/main/scripts/one-click-deploy.sh` returns HTTP 200.
- Verified `https://github.xiaohangyun.org/https://github.com/google/nsjail.git` and `https://github.xiaohangyun.org/https://github.com/google/kafel.git` are reachable with `git ls-remote`.
- Verified `https://docker.xiaohangyun.org/v2/library/node/tags/list` and `https://docker.xiaohangyun.org/v2/library/python/tags/list` return HTTP 200.
- Verified `https://docker.xiaohangyun.org/v2/csbsgyl/ai-lanbot/tags/list` currently returns HTTP 404, so the script must still support GHCR and source-build fallback until a Docker Hub image is published.
- Docker Compose runtime verification was not run because Docker is not installed on this workstation.
- GitHub Actions YAML parsing was not run because Python `yaml` is not installed on this workstation; workflow files were reviewed via diff instead.

### Notes
- `D:\ai-lanbot\scripts\one-click-deploy.sh`: switched default deployment to prebuilt image mode, added image resolution, health checks, failure diagnostics, and login/setup output.
- `D:\ai-lanbot\docker\docker-compose.yaml`: made service images configurable through `LANBOT_IMAGE` and made the web port respect `LANGBOT_HTTP_PORT`.
- `D:\ai-lanbot\Dockerfile`: changed `nsjail` build source retrieval to git clone plus submodule initialization with GitHub accelerator fallback.
- `D:\ai-lanbot\.github\workflows\build-dev-image.yaml`: rebuilt the push image workflow to publish multi-arch GHCR images and optional Docker Hub images.
- `D:\ai-lanbot\.github\workflows\build-docker-image.yml`: rebuilt the release image workflow to publish multi-arch GHCR images and optional Docker Hub images.
- `D:\ai-lanbot\.github\workflows\test-dev-image.yaml`: updated the dev image smoke test to run for `main` and use the branch image tag.
- `D:\ai-lanbot\docker\kubernetes.yaml`: changed default Kubernetes images to GHCR for the fork.
- `D:\ai-lanbot\skills\skills\langbot-plugin-dev\references\test-env-setup.md`: changed test environment images to GHCR for the fork.
- `D:\ai-lanbot\docs\ONE_CLICK_DEPLOY.md`: documented fast image deployment, fallback build mode, health checks, and first-admin setup.
- `D:\ai-lanbot\README.md`: documented health-checked one-click deployment and the absence of a default username/password.
- `D:\ai-lanbot\README_CN.md`: documented health-checked one-click deployment and the `/register` first-admin flow in Chinese.
- `D:\ai-lanbot\progress.md`: appended this task log entry.
- Rollback: before commit, run `git restore .github/workflows/build-dev-image.yaml .github/workflows/build-docker-image.yml .github/workflows/test-dev-image.yaml Dockerfile README.md README_CN.md docker/docker-compose.yaml docker/kubernetes.yaml docs/ONE_CLICK_DEPLOY.md scripts/one-click-deploy.sh skills/skills/langbot-plugin-dev/references/test-env-setup.md progress.md`; after commit, run `git revert <commit>` to undo this task as a single change set.
