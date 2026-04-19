#!/usr/bin/env bash
# Audit the repo for Claude / Anthropic / API-key traces before pushing public.
#
# Classification:
#   🔴 BLOCK   — must be removed before push (secrets, auto-generated taglines)
#   🟡 WARN    — review by hand; likely OK but worth eyeballing
#   🟢 OK      — legitimate mentions (adapter name, package name, docs) — ignored
#
# Exit code:
#   0  clean or only-warn
#   1  at least one BLOCK finding

set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

RED='\033[0;31m'
YEL='\033[0;33m'
GRN='\033[0;32m'
DIM='\033[2m'
RST='\033[0m'

section() { echo -e "\n${DIM}── $1 ──${RST}"; }

# Paths we always skip (either generated, legitimate, or external vendor code)
SKIP_PATHS=(
    "--exclude-dir=node_modules"
    "--exclude-dir=.next"
    "--exclude-dir=target"
    "--exclude-dir=.git"
    "--exclude-dir=__pycache__"
    "--exclude-dir=traces"
    "--exclude=*.pyc"
    "--exclude=*.lock"
    "--exclude=package-lock.json"
)

# Legitimate locations — grep findings in these files are NOT flags.
# (the Claude Code adapter, its tests, its docs, package.json deps, etc.)
is_legit_path() {
    local f="$1"
    case "$f" in
        # Claude Code adapter, tests, fixtures, examples — all legitimate
        agentanvil/adapter/claude_code.py)                return 0 ;;
        agentanvil/adapter/minimal.py)                    return 0 ;;  # uses anthropic SDK
        agentanvil/cli.py)                                return 0 ;;  # provider="anthropic" param
        agentanvil/evaluator.py)                          return 0 ;;  # LLMJudge uses anthropic SDK
        agentanvil/trajectory.py)                         return 0 ;;  # docstring lists scaffolds
        tests/fixtures/claude_code_sample.jsonl)          return 0 ;;
        tests/test_protocol_conformance.py)               return 0 ;;
        tests/test_evaluator.py)                          return 0 ;;
        examples/seed_demo_traces.py)                     return 0 ;;
        examples/run_jordan_count.py)                     return 0 ;;
        examples/supervise_demo.py)                       return 0 ;;
        # Docs + config + README
        README.md)                                        return 0 ;;
        ROADMAP.md)                                       return 0 ;;
        docs/ADAPTERS.md)                                 return 0 ;;
        docs/DEPLOYMENT.md)                               return 0 ;;
        docs/DESIGN.md)                                   return 0 ;;
        docs/TRAJECTORY_PROTOCOL.md)                      return 0 ;;
        docs/VERIFIERS.md)                                return 0 ;;
        job_applications/*.md)                            return 0 ;;
        pyproject.toml)                                   return 0 ;;
        .gitignore)                                       return 0 ;;
        # The audit script itself grep-matches its own patterns
        scripts/check_clean.sh)                           return 0 ;;
        scripts/record_demo_gif.sh)                       return 0 ;;
        scripts/push_github.sh)                           return 0 ;;
    esac
    return 1
}

# Filter grep output: given "path:line:match" lines, split into legit vs suspicious
partition() {
    local legit_count=0 sus_count=0
    local sus_list=""
    while IFS= read -r line; do
        local path="${line%%:*}"
        if is_legit_path "$path"; then
            legit_count=$((legit_count + 1))
        else
            sus_count=$((sus_count + 1))
            sus_list+="$line"$'\n'
        fi
    done
    echo "$legit_count" "$sus_count"
    if [ -n "$sus_list" ]; then
        echo "---"
        printf "%s" "$sus_list"
    fi
}

any_block=0
any_warn=0

# ─────────────────────────────────────────────────────────────────────
section "🔴 BLOCK · Anthropic API keys (MUST remove before push)"
keys=$(grep -rnoE "${SKIP_PATHS[@]}" 'sk-ant-[A-Za-z0-9_-]{40,}' 2>/dev/null || true)
if [ -n "$keys" ]; then
    echo -e "${RED}FOUND API KEY(S):${RST}"
    echo "$keys"
    any_block=1
else
    echo -e "${GRN}none${RST}"
fi

# ─────────────────────────────────────────────────────────────────────
section "🔴 BLOCK · Claude Code auto-generated taglines"
# Tight patterns: only the canonical Claude Code / Anthropic auto-appended lines.
# Must be preceded by "by" or "with" or be a markdown link → avoids Mermaid's CC[Claude Code].
taglines_raw=$(grep -rn "${SKIP_PATHS[@]}" -E \
    '(Co-Authored-By:.*[Cc]laude|🤖 Generated with \[Claude|Generated with .Claude Code|\[Claude Code\]\(https)' \
    2>/dev/null || true)
taglines=""
if [ -n "$taglines_raw" ]; then
    while IFS= read -r line; do
        path="${line%%:*}"
        if ! is_legit_path "$path"; then
            taglines+="$line"$'\n'
        fi
    done <<< "$taglines_raw"
fi
if [ -n "$taglines" ]; then
    echo -e "${RED}FOUND auto-generated taglines:${RST}"
    printf "%s" "$taglines"
    any_block=1
else
    echo -e "${GRN}none${RST}"
fi

# ─────────────────────────────────────────────────────────────────────
section "🔴 BLOCK · Claude tagline in commit messages"
# Match only the UNIQUELY-identifying tagline markers, not documentation-of-markers.
# Real taglines have these structures (anything else is fine):
#   "Co-Authored-By: Claude <someone@anthropic.com>"
#   "Co-Authored-By: Claude Opus ... <noreply@anthropic.com>"
#   "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
commit_taglines=$(git log --pretty='%H%n%s%n%b%n---end---' 2>/dev/null | grep -iE \
    'Co-Authored-By:[[:space:]]+[A-Za-z ]*Claude[^<]*<[^>]*@(anthropic\.com|anthropic)>|🤖 Generated with \[Claude|claude\.com/claude-code' \
    || true)
if [ -n "$commit_taglines" ]; then
    echo -e "${RED}FOUND commit messages with Claude tagline:${RST}"
    echo "$commit_taglines"
    any_block=1
else
    echo -e "${GRN}commits are clean${RST}"
fi

# ─────────────────────────────────────────────────────────────────────
section "🟡 WARN · every 'claude' occurrence, excluding legit files"
claude_findings=$(grep -rn "${SKIP_PATHS[@]}" -iE '\bclaude\b' 2>/dev/null || true)
parts=$(printf "%s" "$claude_findings" | partition)
legit=$(echo "$parts" | head -1 | awk '{print $1}')
sus=$(echo "$parts" | head -1 | awk '{print $2}')
echo -e "${DIM}${legit:-0} legit hits (scaffold name in known files) — ignored${RST}"
if [ -n "${sus:-}" ] && [ "${sus:-0}" != "0" ]; then
    echo -e "${YEL}${sus} suspicious hits (review below):${RST}"
    echo "$parts" | tail -n +3
    any_warn=1
else
    echo -e "${GRN}no suspicious hits${RST}"
fi

# ─────────────────────────────────────────────────────────────────────
section "🟡 WARN · every 'anthropic' occurrence, excluding legit files"
anthropic_findings=$(grep -rn "${SKIP_PATHS[@]}" -iE '\banthropic\b' 2>/dev/null || true)
parts=$(printf "%s" "$anthropic_findings" | partition)
legit=$(echo "$parts" | head -1 | awk '{print $1}')
sus=$(echo "$parts" | head -1 | awk '{print $2}')
echo -e "${DIM}${legit:-0} legit hits — ignored${RST}"
if [ -n "${sus:-}" ] && [ "${sus:-0}" != "0" ]; then
    echo -e "${YEL}${sus} suspicious hits (review below):${RST}"
    echo "$parts" | tail -n +3
    any_warn=1
else
    echo -e "${GRN}no suspicious hits${RST}"
fi

# ─────────────────────────────────────────────────────────────────────
section "🟡 WARN · other giveaway phrases"
giveaways=$(grep -rn "${SKIP_PATHS[@]}" -iE 'generated by (claude|an ai)|this (script|file) was written by (claude|an ai)|courtesy of (claude|anthropic)' 2>/dev/null || true)
if [ -n "$giveaways" ]; then
    echo -e "${YEL}found:${RST}"
    echo "$giveaways"
    any_warn=1
else
    echo -e "${GRN}none${RST}"
fi

# ─────────────────────────────────────────────────────────────────────
section "🟢 VERDICT"
if [ $any_block -ne 0 ]; then
    echo -e "${RED}BLOCK — fix findings above before pushing public.${RST}"
    exit 1
elif [ $any_warn -ne 0 ]; then
    echo -e "${YEL}WARN only — review the hits above but repo is safe to push if all legitimate.${RST}"
    echo -e "${DIM}(commits + secrets are clean; remaining items are content you should eyeball)${RST}"
    exit 0
else
    echo -e "${GRN}CLEAN — safe to push${RST}"
    exit 0
fi
