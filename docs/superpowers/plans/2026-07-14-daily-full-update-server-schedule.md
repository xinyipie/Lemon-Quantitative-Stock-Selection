# Daily Full Update Server Schedule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy `main` to the Stock server and execute the complete update daily at 02:00 Asia/Shanghai.

**Architecture:** Keep the application in `/opt/stock`, reuse its virtual environment and `.env`, and install one root-owned Bash runner. The `ubuntu` user's cron invokes it; `flock` prevents overlap and an append-only file retains output.

**Tech Stack:** Ubuntu, cron, Bash, flock, Python, Git, systemd

## Global Constraints

- Target `root@124.221.27.192`; project `/opt/stock`; service `stock-web`.
- Use `/opt/stock/.venv/bin/python daily_web_update.py --mode full`.
- Load secrets only from `/opt/stock/.env`.
- Preserve `/opt/stock/data/*.db` and all unrelated server changes.
- Do not add or execute trading, ordering, or position-management behavior.

---

### Task 1: Publish and deploy the revision

**Files:**
- Deploy: local `main` to server `/opt/stock`

**Interfaces:**
- Consumes: approved local `main` revision.
- Produces: matching `origin/main` and server `main` revisions.

- [ ] **Step 1: Check deployment scope**

Run `git status --short --branch`. Expected: branch `main`; unrelated changes remain unstaged.

- [ ] **Step 2: Commit this plan**

Run `git add docs/superpowers/plans/2026-07-14-daily-full-update-server-schedule.md` and `git commit -m "Plan daily full update server deployment"`. Expected: one commit containing only this plan.

- [ ] **Step 3: Publish and fast-forward**

Run `git push origin main`, then remotely run `cd /opt/stock && git pull --ff-only origin main && systemctl restart stock-web`. Expected: server fast-forwards without touching the modified runtime database and `stock-web` restarts.

### Task 2: Install the locked runner

**Files:**
- Create on server: `/usr/local/sbin/stock-daily-full-update`
- Create on server: `/opt/stock/logs/`

**Interfaces:**
- Consumes: `/opt/stock/.env`, virtualenv Python, `daily_web_update.py`.
- Produces: a no-argument executable that skips overlap and returns the updater exit code.

- [ ] **Step 1: Install the runner with mode 0755**

```bash
#!/usr/bin/env bash
set -uo pipefail
exec 9>/run/lock/stock-daily-full-update.lock
/usr/bin/flock -n 9 || exit 0
cd /opt/stock
set -a
. /opt/stock/.env
set +a
mkdir -p /opt/stock/logs
exec /opt/stock/.venv/bin/python daily_web_update.py --mode full >> /opt/stock/logs/daily_full_update.log 2>&1
```

- [ ] **Step 2: Prepare ownership and parse-check**

Run `install -d -o ubuntu -g ubuntu -m 0755 /opt/stock/logs` and `bash -n /usr/local/sbin/stock-daily-full-update`. Expected: the log directory is writable by `ubuntu`; Bash exits `0` without running the updater.

### Task 3: Install and verify cron

**Files:**
- Modify on server: `ubuntu` user's crontab

**Interfaces:**
- Consumes: `/usr/local/sbin/stock-daily-full-update`.
- Produces: exactly one daily schedule at 02:00 Asia/Shanghai.

- [ ] **Step 1: Install the schedule idempotently**

Preserve unrelated entries, remove any existing line containing `/usr/local/sbin/stock-daily-full-update`, and append:

```cron
0 2 * * * /usr/local/sbin/stock-daily-full-update
```

- [ ] **Step 2: Verify without running the full update**

Check server revision, `systemctl is-active stock-web`, `crontab -u ubuntu -l`, runner permissions, log-directory ownership, and `bash -n`. Expected: matching revision, active service, one cron entry, correct permissions, and valid Bash syntax. The first complete update runs at the next 02:00.
