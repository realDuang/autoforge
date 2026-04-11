"""Configuration loader for AutoForge."""
import json
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentConfig:
    backend: str = "claude_code"
    path: str = "claude"
    model: str = ""  # Empty = use backend's default model
    effort: str = "high"
    timeout_minutes: int = 30
    extra_args: list[str] = field(default_factory=list)

    def to_backend_config(self) -> dict:
        """Convert to a dict suitable for AgentBackend.__init__."""
        return {
            "path": self.path,
            "model": self.model,
            "effort": self.effort,
            "timeout_minutes": self.timeout_minutes,
            "extra_args": self.extra_args,
        }



@dataclass
class Perspective:
    id: str
    name: str
    label: str
    desc: str


@dataclass
class ConvergenceConfig:
    check_window: int = 5
    min_diff_lines: int = 50
    max_file_overlap_ratio: float = 0.8
    stagnation_line_threshold: int = 10


@dataclass
class TasksConfig:
    max_retries: int = 3
    tasks_per_phase: int = 5
    cooldown_seconds: int = 10
    build_command: str = ""  # Shell command to verify build (empty = skip). Examples: "make", "npm run build", "cargo check"
    build_timeout: int = 120
    quality_commands: list[dict] = field(default_factory=list)  # Additional quality checks: [{"name": str, "command": str, "timeout": int}]


@dataclass
class ParallelConfig:
    max_builders: int = 1
    worktree_dir: str = ""
    prefetch_analyst: bool = False
    conflict_timeout_minutes: int = 10


@dataclass
class ReviewerConfig:
    enabled: bool = False
    model: str = ""  # Empty = use same model as builder
    max_review_cycles: int = 2
    backend: str = ""  # Empty = use same backend as builder


@dataclass
class AutoForgeConfig:
    agent: AgentConfig
    phases: list[str]
    perspectives: list[Perspective]
    convergence: ConvergenceConfig
    tasks: TasksConfig
    parallel: ParallelConfig
    workspace_dir: str
    data_dir: str
    seed_file: str
    base_dir: str  # resolved absolute path of autoforge root
    language: str = "en"
    templates_dir: str = ""
    hooks: dict = field(default_factory=dict)  # {"post_build": [...], "pre_merge": [...]}
    reviewer: ReviewerConfig = field(default_factory=ReviewerConfig)
    permissions: dict = field(default_factory=dict)  # {"analyst": "readonly", "builder": "full", "reviewer": "readonly"}
    knowledge: dict = field(default_factory=dict)  # {"area_keywords": {"combat": ["fight", "attack"]}, "auto_discover": true}
    phase_config: dict = field(default_factory=dict)  # {"BUILD": {"model": "opus-4"}, "TEST": {"model": "sonnet-4"}}

    @classmethod
    def _resolve_path(cls, path: str, base: str) -> str:
        if not path:
            return ""
        if not os.path.isabs(path):
            return os.path.normpath(os.path.join(base, path))
        return os.path.normpath(path)

    @classmethod
    def load(cls, config_path: str) -> "AutoForgeConfig":
        base_dir = os.path.dirname(os.path.abspath(config_path))

        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        agent_raw = raw.get("agent", {})
        agent = AgentConfig(**{k: v for k, v in agent_raw.items() if k in AgentConfig.__dataclass_fields__})

        perspectives = [Perspective(**p) for p in raw.get("perspectives", [])]
        convergence = ConvergenceConfig(**raw.get("convergence", {}))
        tasks = TasksConfig(**raw.get("tasks", {}))

        parallel_raw = raw.get("parallel", {})
        worktree_dir_raw = parallel_raw.pop("worktree_dir", "")
        parallel = ParallelConfig(**parallel_raw)
        if worktree_dir_raw:
            parallel.worktree_dir = cls._resolve_path(worktree_dir_raw, base_dir)

        workspace_dir = cls._resolve_path(raw.get("workspace_dir", "./workspace"), base_dir)
        seed_file = cls._resolve_path(raw.get("seed_file", "./seed.md"), base_dir)

        # data_dir: where all AutoForge runtime data lives (DB, knowledge, logs, prompts)
        # Defaults to {workspace_dir}/.autoforge if not specified
        data_dir_raw = raw.get("data_dir", "")
        if data_dir_raw:
            data_dir = cls._resolve_path(data_dir_raw, base_dir)
        else:
            data_dir = os.path.join(workspace_dir, ".autoforge")

        return cls(
            agent=agent,
            phases=raw.get("phases", ["BUILD", "TEST", "FIX", "EVOLVE"]),
            perspectives=perspectives,
            convergence=convergence,
            tasks=tasks,
            parallel=parallel,
            workspace_dir=workspace_dir,
            data_dir=data_dir,
            seed_file=seed_file,
            base_dir=base_dir,
            language=raw.get("language", "en"),
            templates_dir=cls._resolve_path(raw.get("templates_dir", ""), base_dir),
            hooks=raw.get("hooks", {}),
            reviewer=ReviewerConfig(**{k: v for k, v in raw.get("reviewer", {}).items() if k in ReviewerConfig.__dataclass_fields__}),
            permissions=raw.get("permissions", {}),
            knowledge=raw.get("knowledge", {}),
            phase_config=raw.get("phase_config", {}),
        )

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, "state.db")

    @property
    def knowledge_dir(self) -> str:
        return os.path.join(self.data_dir, "knowledge")

    @property
    def prompts_dir(self) -> str:
        return os.path.join(self.data_dir, "prompts")

    @property
    def logs_dir(self) -> str:
        return os.path.join(self.data_dir, "logs")

    @property
    def next_tasks_path(self) -> str:
        return os.path.join(self.data_dir, "next_tasks.json")

    @property
    def task_result_path(self) -> str:
        return os.path.join(self.data_dir, "task_result.md")

    def task_result_path_for(self, task_id: str) -> str:
        """Get a unique task result file path for parallel execution."""
        return os.path.join(self.data_dir, f"task_result_{task_id}.md")
