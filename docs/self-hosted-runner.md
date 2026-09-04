# Self-hosted runner — setup & consolidation

This project's CI (`.github/workflows/build.yml`) targets a **self-hosted
runner** labelled `[self-hosted, Linux, X64]` with Docker available. This
box (`cachyworld`) already runs runners for two other repos, so this doc
also answers: *can one runner serve all of them?*

## Can one runner handle multiple repos?

**Short answer: not on a personal account.** `ltfiend` is a GitHub **User**,
not an Organization. GitHub self-hosted runners register at one of three
scopes:

| Scope | Serves | Available to `ltfiend`? |
|-------|--------|-------------------------|
| **Repository** | exactly one repo | ✅ (what you have today) |
| **Organization** | every repo in the org (or a subset via runner groups) | ❌ needs a GitHub org |
| **Enterprise** | every org | ❌ |

A single runner *process* has exactly one registration. On a personal
account the only registration scope is the repository, so **one runner =
one repo**. There is no supported way to point one repo-scoped runner at
three repos.

Today you run two, both as bare foreground processes (not services):

| Directory | Repo | Agent name | Managed by |
|-----------|------|-----------|------------|
| `~/Git/actions-runner` | `ltfiend/neodocker` | `cachyworld` | `bash run.sh` (manual) |
| `~/Git/actions-runner-dnsm` | `ltfiend/dns-manager` | `cachyworld-dnsm` | `bash run.sh` (manual) |

`gpt-jupyter-dns` has **no runner yet**, so its workflow will sit queued
until one is added.

## Two ways to consolidate

### Path A — GitHub Organization (true single runner) ⭐ if you'll use an org

Move the three repos under a (free) GitHub **Organization**, then register
**one** org-level runner. All repos share it via a runner group. One
process, one registration, one thing to manage; new repos need zero runner
setup.

```bash
# after creating an org and transferring the repos:
TOKEN=$(gh api -X POST orgs/<ORG>/actions/runners/registration-token --jq .token)
./config.sh --url https://github.com/<ORG> --token "$TOKEN" \
  --name cachyworld --labels self-hosted,Linux,X64 --unattended
```

Trade-off: transferring personal repos into an org changes their URLs
(redirects are kept) and touches anything that hard-codes `ltfiend/…`.
Worth it only if you're happy operating under an org.

### Path B — stay on personal repos, one box, three services ⭐ recommended now

Keep the repo-scoped model but fix what actually hurts: the runners are
**manual foreground processes**. Convert each to a **systemd service** and
add a third for this repo. You still have three lightweight runner
processes (an idle runner is a few MB of RAM), but management, disk, Docker,
and the tool cache are all shared on one box.

**1. Register a runner for this repo** (reuses the already-downloaded
runner tarball; it self-updates on first connect):

```bash
mkdir -p ~/Git/actions-runner-jdns && cd ~/Git/actions-runner-jdns
tar xzf ~/Git/actions-runner/actions-runner-linux-x64-*.tar.gz

# repo scope needs admin on the repo; gh already has the token
TOKEN=$(gh api -X POST repos/ltfiend/gpt-jupyter-dns/actions/runners/registration-token --jq .token)
./config.sh --url https://github.com/ltfiend/gpt-jupyter-dns --token "$TOKEN" \
  --name cachyworld-jdns --labels self-hosted,Linux,X64 --unattended
```

**2. Install all three as services** (survive reboot, auto-restart). Run
once per runner directory:

```bash
for d in ~/Git/actions-runner ~/Git/actions-runner-dnsm ~/Git/actions-runner-jdns; do
  ( cd "$d" && sudo ./svc.sh install peter && sudo ./svc.sh start )
done
```

Stop the old manual `run.sh` processes first so you don't run two copies:

```bash
pkill -f 'Runner.Listener run'   # then start the services as above
```

Check them:

```bash
systemctl list-units 'actions.runner.*' --all
```

**3. (Optional) share the runner binaries.** Each dir currently keeps its
own copy of `bin.*`/`externals.*` (~0.5 GB each). They can symlink to one
shared extraction; each runner still needs its **own** `_work`, `.runner`,
and `.credentials`. Skip this unless disk matters — it's the least
important win.

## Recommendation

- **Right now:** Path B. It's a small, reversible change (add one runner,
  `svc.sh install ×3`), needs no org migration, and gives you reboot-safe,
  centrally-managed runners for all three repos on this one box.
- **If you plan to add more repos or want a single registration:** Path A —
  create an org and run one org-level runner.

## Housekeeping on the box

Independent of the above, this frees ~0.7 GB and de-clutters:

```bash
# 213 MB installer tarball, no longer needed once extracted
rm ~/Git/actions-runner/actions-runner-linux-x64-2.331.0.tar.gz

# stale previous runner version (current is 2.337.0; keep only the live one)
rm -rf ~/Git/actions-runner/bin.2.336.0 ~/Git/actions-runner/externals.2.336.0
rm -rf ~/Git/actions-runner-dnsm/bin.2.336.0 ~/Git/actions-runner-dnsm/externals.2.336.0
```

The runner keeps `_work/` (checked-out repos + build caches) large over
time; `docker system prune` and clearing `_work/_tool` reclaim space when
needed.

## Runner requirements for this workflow

The workflow assumes the runner user can reach Docker and the internet:

- **Docker** — `peter` is in the `docker` group ✅ (needed for build,
  smoke test, hadolint, Trivy).
- **No buildx required** — the build job uses plain `docker build`, which
  reuses the daemon's local layer cache (faster than shipping cache to
  GitHub on a self-hosted box).
- **Outbound network** — to pull base images and the hadolint/Trivy action
  containers, and to push to GHCR / `registry.devries.tv`.
