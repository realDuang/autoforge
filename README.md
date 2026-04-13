# AutoForge

An AI agent harness engineering framework that orchestrates coding agents in a continuous, autonomous development loop. Point it at any software project with a `seed.md` description, and AutoForge drives an infinite Analyst → Builder pipeline — generating tasks, executing them, enforcing quality gates, and evolving the codebase without human intervention.

## Features

- **Multi-agent backend** — ships with `claude_code` (Claude Code CLI) and `ghcp` (GitHub Copilot CLI); add your own via the `AgentBackend` interface
- **Infinite autonomous loop** — while-true orchestration with crash recovery, graceful shutdown (Ctrl+C), and `--max-loops N` for bounded runs
- **Anti-convergence** — 9-perspective rotation, task fingerprint dedup, area attention balancing, and automatic convergence detection with forced escape
- **Deterministic quality gates** — lifecycle hooks (`post_build`, `pre_merge`, `post_merge`) run shell commands guaranteed, independent of agent prompts
- **Writer-Reviewer pattern** — optional adversarial review stage with a clean-context reviewer agent (can use a different model/backend)
- **Permission sandboxing** — graduated permission levels per role, translated to backend-native flags
- **Parallel builders** — git-worktree-based parallel execution with merge locking and area-level concurrency control
- **Per-phase configuration** — different models, backends, or permissions for each phase (BUILD/TEST/FIX/EVOLVE)
- **Session metrics** — per-session performance tracking with `--stats` dashboard
- **i18n prompt templates** — built-in English and Chinese templates, user-customizable via `templates_dir`

## How It Works

```
┌────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR LOOP                           │
│                                                                │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌─────────┐  │
│  │ ANALYST  │───▶│ BUILDER  │───▶│ REVIEWER │───▶│  HOOKS  │  │
│  │ Generate │    │ Execute  │    │ (opt.)   │    │ Quality │  │
│  │ Tasks    │    │ Task     │    │ Approve/ │    │ Gates   │  │
│  └──────────┘    └──────────┘    │ Reject   │    └─────────┘  │
│       ▲                          └──────────┘         │       │
│       │                                               │       │
│       └───────────────────────────────────────────────┘       │
│                                                                │
│  Phase rotation:  BUILD → TEST → FIX → EVOLVE → BUILD → ...  │
│  Perspective rotation:  P1 → P2 → ... → P9 → P1 → ...       │
└────────────────────────────────────────────────────────────────┘
```

**Loop 1 (EVOLVE):** The Analyst examines the project state, knowledge base, and seed description through a rotating perspective (Feature Gap, Bug Hunt, Test Coverage, Performance, Code Quality, etc.), then generates a batch of prioritized tasks written to `next_tasks.json`.

**Loop 2+ (BUILD/TEST/FIX):** The Builder picks the highest-priority task from the least-touched area, executes it via the agent CLI, then runs quality hooks. If the optional Reviewer is enabled, it performs an adversarial review. Passed tasks are committed; failed tasks are retried or skipped.

**Convergence escape:** If git diffs shrink, the same files keep being modified, or code size stagnates, AutoForge rotates the perspective and forces an EVOLVE phase to generate fresh tasks.

## Quick Start

### Prerequisites

- Python 3.10+
- One of:
  - [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — `claude` CLI
  - [GitHub Copilot CLI](https://docs.github.com/copilot) — `copilot` CLI
- Git

### Setup

```bash
# Clone
git clone https://github.com/realDuang/autoforge.git
cd autoforge

# Copy and edit config
cp autoforge_config.template.json autoforge_config.json

# Create your project description
cat > seed.md << 'EOF'
# My Project
A web app that does X, Y, Z.

## Tech Stack
- Node.js, React, PostgreSQL

## Features
- User auth [NOT YET]
- Dashboard [IN PROGRESS]
- API endpoints [IN PROGRESS]
EOF

# Initialize (creates directories and database)
python -m autoforge --init

# Run (Ctrl+C to stop gracefully)
python -m autoforge
```

### Using GitHub Copilot instead of Claude Code

```json
{
  "agent": {
    "backend": "ghcp",
    "path": "copilot",
    "model": "gpt-4.1"
  }
}
```

### Bounded runs

```bash
# Run exactly 3 loops (1 analyst + 2 builder), then exit
python -m autoforge --max-loops 3

# View performance dashboard
python -m autoforge --stats
```

## Configuration

Minimal config (all other fields have sensible defaults):

```json
{
  "agent": {
    "backend": "claude_code",
    "model": "claude-sonnet-4-20250514"
  },
  "workspace_dir": "./my-project",
  "seed_file": "./seed.md"
}
```

### Full Reference

| Parameter | Description | Default |
|-----------|-------------|---------|
| **Agent** | | |
| `agent.backend` | Backend name (`claude_code`, `ghcp`, or custom) | `claude_code` |
| `agent.path` | CLI executable path | `claude` |
| `agent.model` | Model identifier (empty = backend default) | `""` |
| `agent.effort` | Reasoning effort level | `high` |
| `agent.timeout_minutes` | Max session duration | `30` |
| `agent.extra_args` | Additional CLI arguments | `[]` |
| **Project** | | |
| `workspace_dir` | Target project directory | `./workspace` |
| `seed_file` | Project description file | `./seed.md` |
| `data_dir` | Runtime data directory | `{workspace_dir}/.autoforge` |
| `language` | Prompt template language (`en`/`zh`) | `en` |
| `templates_dir` | Custom prompt templates path | (built-in) |
| **Phases & Perspectives** | | |
| `phases` | Phase rotation order | `["BUILD","TEST","FIX","EVOLVE"]` |
| `perspectives` | Analysis viewpoints (id, name, label, desc) | 9 built-in |
| **Tasks** | | |
| `tasks.tasks_per_phase` | Tasks to complete before phase advance | `5` |
| `tasks.max_retries` | Max retries before skipping a task | `3` |
| `tasks.cooldown_seconds` | Pause between loops | `10` |
| `tasks.build_command` | Legacy build verification command | `""` |
| `tasks.quality_commands` | Legacy quality check commands | `[]` |
| **Quality Hooks** | | |
| `hooks.post_build` | Hooks after builder session | `[]` |
| `hooks.pre_merge` | Hooks before worktree merge | `[]` |
| `hooks.post_merge` | Hooks after merge to main | `[]` |
| **Reviewer** | | |
| `reviewer.enabled` | Enable adversarial review | `false` |
| `reviewer.model` | Reviewer model (empty = same as builder) | `""` |
| `reviewer.backend` | Reviewer backend (empty = same as builder) | `""` |
| `reviewer.max_review_cycles` | Max review iterations | `2` |
| **Permissions** | | |
| `permissions.analyst` | Analyst permission profile | (full by default) |
| `permissions.builder` | Builder permission profile | (full by default) |
| `permissions.reviewer` | Reviewer permission profile | (full by default) |
| **Parallel** | | |
| `parallel.max_builders` | Concurrent builder workers | `1` |
| `parallel.worktree_dir` | Worktree base directory | (auto) |
| `parallel.prefetch_analyst` | Run analyst in background during builds | `false` |
| **Convergence** | | |
| `convergence.check_window` | Recent metrics window for detection | `5` |
| `convergence.min_diff_lines` | Minimum diff lines before triggering | `50` |
| `convergence.max_file_overlap_ratio` | File overlap threshold | `0.8` |
| **Per-Phase Overrides** | | |
| `phase_config.{PHASE}.model` | Model override for a specific phase | (agent default) |
| `phase_config.{PHASE}.backend` | Backend override for a specific phase | (agent default) |
| **Contract** | | |
| `contract.enabled` | Enable sprint contract negotiation before each task | `true` |

### Hooks

Hooks run shell commands deterministically at pipeline stages. Unlike prompt-based instructions, hooks are guaranteed to execute.

```json
{
  "hooks": {
    "post_build": [
      {"name": "build", "command": "npm run build", "timeout": 120, "required": true},
      {"name": "lint", "command": "npm run lint", "required": false}
    ],
    "pre_merge": [
      {"name": "test", "command": "npm test", "required": true}
    ]
  }
}
```

- `required: true` — failure aborts the pipeline step (task marked failed)
- `required: false` — failure logged as warning, pipeline continues

Legacy `tasks.build_command` and `tasks.quality_commands` are auto-converted to `post_build` hooks for backward compatibility.

### Permission Sandboxing

When `permissions` is configured, each role gets a restricted profile translated to backend-native flags:

```json
{
  "permissions": {
    "analyst": {"mode": "readonly"},
    "builder": {"mode": "full"},
    "reviewer": {"mode": "readonly", "allowed_tools": ["Read", "Glob", "Grep", "Bash"]}
  }
}
```

| Mode | Claude Code | GitHub Copilot |
|------|-------------|----------------|
| `full` | `--dangerously-skip-permissions` | `--yolo` |
| `edit` | `--allowedTools Read,Edit,...` | `--available-tools Read,Edit,...` |
| `readonly` | `--allowedTools Read,Glob,Grep` | `--available-tools Read,Glob,Grep` |

When `permissions` is omitted entirely, all roles default to full access (backward compatible).

### Per-Phase Configuration

Use different models or backends per phase:

```json
{
  "phase_config": {
    "BUILD": {"model": "claude-opus-4-6"},
    "TEST": {"model": "claude-sonnet-4-6"},
    "FIX": {"model": "claude-sonnet-4-6"}
  }
}
```

### Writer-Reviewer Pattern

Enable adversarial review with an independent reviewer agent:

```json
{
  "reviewer": {
    "enabled": true,
    "model": "claude-opus-4-6",
    "max_review_cycles": 2
  }
}
```

The reviewer runs in a clean context (no builder conversation history), examines the git diff, and returns one of:
- **APPROVE** — task passes
- **REQUEST_CHANGES** — task retried with reviewer feedback
- **REJECT** — task marked failed

### Sprint Contract

Before each task, the builder proposes a sprint contract — an implementation plan with verification criteria — which is reviewed before coding begins:

```
1. Analyst generates task with acceptance criteria
2. Builder proposes sprint contract (approach + verification criteria)
3. Reviewer approves the contract
4. Builder implements against the contract
5. Reviewer evaluates the diff against contract criteria item-by-item
```

This is enabled by default. To disable:

```json
{
  "contract": {
    "enabled": false
  }
}
```

When the reviewer is also enabled, the final review evaluates each verification criterion from the contract, providing structured pass/fail results instead of subjective assessment.

## Anti-Convergence

| Layer | Mechanism | Description |
|-------|-----------|-------------|
| Task fingerprinting | SHA256 dedup | Identical tasks are never created twice |
| Perspective rotation | 9 viewpoints | Each analyst run uses a different analysis angle |
| Area attention | Touch tracking | Prioritizes least-recently-worked areas |
| Knowledge growth | Self-expanding specs | AI grows the knowledge base, inflating the task source |
| Convergence detection | Metric monitoring | Detects shrinking diffs, file overlap, code stagnation |
| Forced escape | Auto-intervention | Detection triggers perspective rotation + EVOLVE phase |

## Custom Agent Backends

Implement `AgentBackend` and register it:

```python
from autoforge.agents import AgentBackend, SessionResult, register_backend

class MyBackend(AgentBackend):
    @property
    def name(self) -> str:
        return "my_backend"

    def check_available(self) -> bool:
        # Check if your CLI/SDK is available
        ...

    def run_session(self, prompt, working_dir, timeout_minutes=30,
                    prompt_save_path=None, permission_profile=None) -> SessionResult:
        # Run the agent and return results
        ...

register_backend("my_backend", MyBackend)
```

Then use it in config:
```json
{"agent": {"backend": "my_backend"}}
```

## Project Structure

```
autoforge/
├── agents/
│   ├── __init__.py          # Backend registry
│   ├── base.py              # AgentBackend ABC + SessionResult
│   ├── claude_code.py       # Claude Code CLI backend
│   └── ghcp.py              # GitHub Copilot CLI backend
├── templates/
│   ├── en/                  # English prompt templates
│   └── zh/                  # Chinese prompt templates
├── orchestrator.py          # Main loop + CLI entry point
├── config.py                # Configuration dataclasses + loader
├── db.py                    # SQLite state database
├── hooks.py                 # Deterministic lifecycle hooks
├── reviewer.py              # Writer-Reviewer pattern
├── permissions.py           # Permission profiles
├── metrics.py               # Session metrics tracking
├── prompts.py               # Template-based prompt generation
├── convergence.py           # Convergence detection
├── parallel.py              # Git worktree parallel execution
├── state.py                 # Project state gathering
└── runner.py                # Shutdown coordination
```

## License

MIT
