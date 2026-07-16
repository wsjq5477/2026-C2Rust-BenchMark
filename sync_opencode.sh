#!/usr/bin/env bash
# Mirror the 02_02 contest source layout into its OpenCode runtime layout.
# Run from any directory: this script always uses the repository root.

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$ROOT/02_02"
WORK="$PROJECT/work"
TARGET="$ROOT/.opencode"

SKILLS_SOURCE="$WORK/skills"
AGENTS_SOURCE="$WORK/agents"
SUBAGENTS_SOURCE="$WORK/subagent"
SKILLS_TARGET="$TARGET/skills"
AGENTS_TARGET="$TARGET/agents"
AGENT_MANIFEST="$TARGET/.flashdb-work-agent-manifest"

for source in "$SKILLS_SOURCE" "$AGENTS_SOURCE" "$SUBAGENTS_SOURCE"; do
    if [[ ! -d "$source" ]]; then
        printf 'missing required source directory: %s\n' "$source" >&2
        exit 1
    fi
done

# Preserve unrelated project-level OpenCode configuration, plugins, skills, and
# agents.  Files with the same name as a work source are refreshed below.
mkdir -p "$SKILLS_TARGET" "$AGENTS_TARGET"

# Remove only agent files copied by the previous run of this script.  This
# keeps renamed work agents from lingering while preserving user-owned agents.
if [[ -f "$AGENT_MANIFEST" ]]; then
    while IFS= read -r name; do
        [[ "$name" == *.md && "$name" != */* ]] || continue
        rm -f "$AGENTS_TARGET/$name"
    done < "$AGENT_MANIFEST"
fi
: > "$AGENT_MANIFEST"

# Skills preserve their <skill-name>/SKILL.md directory layout.
cp -a "$SKILLS_SOURCE/." "$SKILLS_TARGET/"

# OpenCode stores primary agents and subagents in the same runtime directory;
# their frontmatter mode distinguishes primary from subagent.
declare -A agent_sources=()
agent_count=0
for source in "$AGENTS_SOURCE" "$SUBAGENTS_SOURCE"; do
    shopt -s nullglob
    for file in "$source"/*.md; do
        name="$(basename -- "$file")"
        if [[ -v "agent_sources[$name]" ]]; then
            printf 'agent filename collision: %s (%s and %s)\n' \
                "$name" "${agent_sources[$name]}" "$file" >&2
            exit 1
        fi
        agent_sources["$name"]="$file"
        cp -a "$file" "$AGENTS_TARGET/$name"
        printf '%s\n' "$name" >> "$AGENT_MANIFEST"
        ((agent_count += 1))
    done
    shopt -u nullglob
done

skill_count="$(find "$SKILLS_SOURCE" -type f -name SKILL.md -print | wc -l | tr -d '[:space:]')"
printf 'mirrored %s skills and %s agents to %s\n' "$skill_count" "$agent_count" "$TARGET"
