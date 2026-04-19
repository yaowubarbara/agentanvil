#!/usr/bin/env bash
# Orchestrate pushing AgentAnvil to GitHub from a China-based setup.
#
# Flow:
#   1. Runs scripts/check_clean.sh — aborts on BLOCK findings
#   2. Tars the repo (with .git) and SCPs to WSL at /mnt/c/Users/Barbara/Desktop/agentanvil
#   3. Prints a copy-paste-ready block of commands for Barbara to run IN WSL
#      that configure the Clash proxy on git and push to GitHub.
#
# Why this orchestration (instead of pushing from the dev server):
#   - Dev server (cloud) can't route to github.com reliably from China.
#   - Barbara's WSL sits behind her Clash instance at 172.30.224.1:7890,
#     which IS working for other git pushes.
#   - She already has git identity configured locally; just needs to point
#     the remote at a fresh repo and push.
#
# Prerequisite (one-time, Barbara to do on GitHub web UI):
#   1. Go to https://github.com/new
#   2. Repo name: agentanvil
#   3. Owner: yaowubarbara
#   4. Public
#   5. DO NOT initialize with README, .gitignore, or license (we have our own)
#   6. Click Create
#
# Then run this script on the dev server.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

BLUE='\033[0;34m'
GRN='\033[0;32m'
RED='\033[0;31m'
YEL='\033[0;33m'
DIM='\033[2m'
RST='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${RST}"
echo -e "${BLUE}║  AgentAnvil → GitHub (via WSL with Clash proxy)       ║${RST}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${RST}"
echo ""

# ─────────────────────────────────────────────────────────────────────
echo -e "${DIM}── [1/4] Running clean audit ──${RST}"
if ! bash "$REPO/scripts/check_clean.sh" > /tmp/clean-log 2>&1; then
    echo -e "${RED}✗ check_clean.sh flagged a BLOCK finding. Fix before pushing.${RST}"
    echo ""
    cat /tmp/clean-log
    exit 1
fi
echo -e "${GRN}✓ audit clean${RST}"

# ─────────────────────────────────────────────────────────────────────
echo -e "${DIM}── [2/4] Packaging repo (with .git, ~300KB) ──${RST}"
TARBALL=/tmp/agentanvil-push.tgz
tar czf "$TARBALL" \
    --exclude='node_modules' \
    --exclude='.next' \
    --exclude='target' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    -C /home/dev agentanvil
SIZE=$(du -h "$TARBALL" | cut -f1)
echo -e "${GRN}✓ $TARBALL ($SIZE)${RST}"

# ─────────────────────────────────────────────────────────────────────
echo -e "${DIM}── [3/4] Copying to WSL ──${RST}"
expect -c '
set timeout 60
spawn scp -o StrictHostKeyChecking=no -P 2222 /tmp/agentanvil-push.tgz barbaraarbara@localhost:/tmp/
expect {
    "assword:" { send "helloworld\r"; exp_continue }
    eof
}
' 2>&1 | tail -3

echo -e "${DIM}── [4/4] Extracting on WSL to ~/aa-push/agentanvil ──${RST}"
expect -c '
set timeout 30
spawn ssh -o StrictHostKeyChecking=no -p 2222 barbaraarbara@localhost "rm -rf ~/aa-push && mkdir -p ~/aa-push && tar xzf /tmp/agentanvil-push.tgz -C ~/aa-push && cd ~/aa-push/agentanvil && git log --oneline | head -5 && echo --- && git status"
expect {
    "assword:" { send "helloworld\r"; exp_continue }
    eof
}
' 2>&1 | tail -15

echo ""
echo -e "${GRN}✓ repo staged on WSL at ~/aa-push/agentanvil with full .git history${RST}"
echo ""

# ─────────────────────────────────────────────────────────────────────
echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${RST}"
echo -e "${BLUE}║  Now run these commands on your WSL                   ║${RST}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${RST}"
echo ""

cat <<'MANUAL'
# ────────────────────────────────────────────────────────────────
# STEP 0 — First-time only: create the empty repo on GitHub
# ────────────────────────────────────────────────────────────────
#   Open: https://github.com/new
#   Name: agentanvil
#   Owner: yaowubarbara
#   Visibility: Public
#   DO NOT initialize with anything — leave all checkboxes unticked
#   Click Create repository
#
# ────────────────────────────────────────────────────────────────
# STEP 1 — ssh into WSL (from a Windows terminal)
# ────────────────────────────────────────────────────────────────

# On your Windows machine, open PowerShell or cmd and run:
#     wsl

# Or if you prefer ssh from Mac:
#     ssh -p 2222 barbaraarbara@localhost
#     (password: helloworld)

# ────────────────────────────────────────────────────────────────
# STEP 2 — cd to the staged copy
# ────────────────────────────────────────────────────────────────

cd ~/aa-push/agentanvil

# ────────────────────────────────────────────────────────────────
# STEP 3 — configure the Clash proxy for this repo only
# ────────────────────────────────────────────────────────────────

# Your Clash instance is at 172.30.224.1:7890 (per your MEMORY.md).
# Set it on this repo only — won't affect global git config.

git config --local http.proxy  http://172.30.224.1:7890
git config --local https.proxy http://172.30.224.1:7890

# ────────────────────────────────────────────────────────────────
# STEP 4 — configure identity (once per repo)
# ────────────────────────────────────────────────────────────────

git config --local user.name  "yaowubarbara"
git config --local user.email "113857460+yaowubarbara@users.noreply.github.com"

# ────────────────────────────────────────────────────────────────
# STEP 5 — add remote + rename branch + push
# ────────────────────────────────────────────────────────────────

# If origin already exists from a previous attempt, remove it first:
git remote remove origin 2>/dev/null || true

# Add the new origin (HTTPS, works through Clash)
git remote add origin https://github.com/yaowubarbara/agentanvil.git

# Rename master -> main (GitHub default)
git branch -M main

# Push — you'll be prompted for username + password.
# Username: yaowubarbara
# Password: your GitHub Personal Access Token (NOT your GitHub password!)
#           https://github.com/settings/tokens → Generate new (classic)
#           Scopes: repo (full control)
git push -u origin main

# ────────────────────────────────────────────────────────────────
# STEP 6 — verify
# ────────────────────────────────────────────────────────────────

# Visit https://github.com/yaowubarbara/agentanvil
# You should see 11 commits, the README with badges, and the mermaid
# architecture diagram rendered inline.

# ────────────────────────────────────────────────────────────────
# (Optional) troubleshooting
# ────────────────────────────────────────────────────────────────

# If push fails with "Could not resolve host":
#   your proxy isn't up — check:
#     curl -v -x http://172.30.224.1:7890 https://github.com/ -o /dev/null
#
# If push fails with "Authentication failed":
#   your Personal Access Token is wrong or expired. Regenerate at
#     https://github.com/settings/tokens
#
# If push fails with "Updates were rejected (non-fast-forward)":
#   the GitHub repo is not empty. Delete it (Settings → Danger Zone)
#   or force push: git push -u origin main --force
MANUAL

echo ""
echo -e "${YEL}Tip:${RST} save a GitHub Personal Access Token once — git credential helper"
echo -e "     will remember it for future pushes (BOSS 直聘 面试官能看到你的 repo 下次"
echo -e "     会自动用)."
