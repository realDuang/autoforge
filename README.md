# AutoForge

中文 | [English](README.en.md)

AI Agent 编排工程框架 —— 驱动编码 Agent 在持续自主开发循环中运行。只需提供一个项目描述文件 `seed.md`，AutoForge 会驱动无限的"分析 → 构建"流水线 —— 自动生成任务、执行代码变更、运行质量门禁、并持续演进代码库，无需人工干预。

## 核心特性

- **多 Agent 后端** —— 内置 `claude_code`（Claude Code CLI）和 `ghcp`（GitHub Copilot CLI），也可通过 `AgentBackend` 接口自定义扩展
- **无限自主循环** —— 带崩溃恢复的 while-true 编排，支持 Ctrl+C 优雅关闭和 `--max-loops N` 有界运行
- **抗收敛机制** —— 9 视角轮转、任务指纹去重、区域注意力均衡、自动收敛检测与强制逃逸
- **确定性质量门禁** —— 生命周期钩子（`post_build`、`pre_merge`、`post_merge`）运行 shell 命令，不依赖 Agent 提示词
- **Writer-Reviewer 模式** —— 可选的对抗性审查阶段，独立上下文的 Reviewer Agent（可使用不同模型/后端）
- **Sprint Contract** —— 在编码前先由 Agent 规划实现方案并由 Reviewer 审查，被拒则带反馈修订
- **权限沙箱** —— 按角色分级的权限控制，自动转换为后端原生参数
- **并行构建** —— 基于 git worktree 的并行执行，merge 锁和区域级并发控制
- **阶段级配置** —— 为不同阶段（BUILD/TEST/FIX/EVOLVE）配置不同模型、后端或权限
- **Session 指标** —— 每次 session 的性能追踪，`--stats` 仪表盘查看
- **i18n 提示词模板** —— 内置中英文模板，支持 `templates_dir` 自定义覆盖

## 工作原理

```
┌────────────────────────────────────────────────────────────────┐
│                      编排循环（ORCHESTRATOR）                    │
│                                                                │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌─────────┐  │
│  │ 分析师   │───▶│ 构建者   │───▶│ 审查者   │───▶│ 钩子    │  │
│  │ 生成任务 │    │ 执行任务 │    │（可选）  │    │ 质量门禁│  │
│  └──────────┘    └──────────┘    │ 批准/拒绝│    └─────────┘  │
│       ▲                          └──────────┘         │       │
│       │                                               │       │
│       └───────────────────────────────────────────────┘       │
│                                                                │
│  阶段轮转:  BUILD → TEST → FIX → EVOLVE → BUILD → ...        │
│  视角轮转:  P1 → P2 → ... → P9 → P1 → ...                   │
└────────────────────────────────────────────────────────────────┘
```

**循环 1（EVOLVE）:** 分析师通过轮转视角（功能缺口、Bug 猎人、测试覆盖、性能审计、代码质量等）检查项目状态、知识库和种子描述，生成一批优先级排序的任务写入 `next_tasks.json`。

**循环 2+（BUILD/TEST/FIX）:** 构建者从最少关注的区域中选择最高优先级任务，通过 Agent CLI 执行，然后运行质量钩子。如果启用了审查者，会进行对抗性审查。通过的任务被提交，失败的任务被重试或跳过。

**收敛逃逸:** 当 git diff 缩减、同一文件被反复修改、或代码量停滞时，AutoForge 自动轮转视角并强制进入 EVOLVE 阶段生成新任务。

## 快速开始

### 前置条件

- Python 3.10+
- 以下任一 Agent CLI:
  - [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — `claude` CLI
  - [GitHub Copilot CLI](https://docs.github.com/copilot) — `copilot` CLI
- Git

### 安装

```bash
# 克隆
git clone https://github.com/realDuang/autoforge.git
cd autoforge

# 复制并编辑配置
cp autoforge_config.template.json autoforge_config.json

# 创建项目描述文件
cat > seed.md << 'EOF'
# 我的项目
一个实现 X、Y、Z 功能的 Web 应用。

## 技术栈
- Node.js, React, PostgreSQL

## 功能清单
- 用户认证 [未实现]
- 控制面板 [进行中]
- API 接口 [进行中]
EOF

# 初始化（创建目录和数据库）
python -m autoforge --init

# 运行（Ctrl+C 优雅停止）
python -m autoforge
```

### 使用 GitHub Copilot

```json
{
  "agent": {
    "backend": "ghcp",
    "path": "copilot",
    "model": "gpt-4.1"
  }
}
```

### 有界运行

```bash
# 运行到第 3 轮后退出
python -m autoforge --max-loops 3

# 查看性能仪表盘
python -m autoforge --stats
```

## 配置

最小配置（其他字段均有默认值）:

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

### 完整参考

| 参数 | 说明 | 默认值 |
|------|------|--------|
| **Agent** | | |
| `agent.backend` | 后端名称（`claude_code`、`ghcp` 或自定义） | `claude_code` |
| `agent.path` | CLI 可执行文件路径 | `claude` |
| `agent.model` | 模型标识（空=后端默认） | `""` |
| `agent.effort` | 推理力度 | `high` |
| `agent.timeout_minutes` | Session 最大时长 | `30` |
| `agent.extra_args` | 额外 CLI 参数 | `[]` |
| **项目** | | |
| `workspace_dir` | 目标项目目录 | `./workspace` |
| `seed_file` | 项目描述文件 | `./seed.md` |
| `data_dir` | 运行时数据目录 | `{workspace_dir}/.autoforge` |
| `language` | 提示词模板语言（`en`/`zh`） | `en` |
| `templates_dir` | 自定义提示词模板路径 | （内置） |
| **阶段与视角** | | |
| `phases` | 阶段轮转顺序 | `["BUILD","TEST","FIX","EVOLVE"]` |
| `perspectives` | 分析视角（id, name, label, desc） | 内置 9 个 |
| **任务** | | |
| `tasks.tasks_per_phase` | 阶段推进前需完成的任务数 | `5` |
| `tasks.max_retries` | 跳过前最大重试次数 | `3` |
| `tasks.cooldown_seconds` | 循环间隔 | `10` |
| `tasks.build_command` | 兼容旧版的构建验证命令 | `""` |
| `tasks.quality_commands` | 兼容旧版的质量检查命令 | `[]` |
| `tasks.clean_dirs` | 每个钩子执行前清理的目录（worktree 缓存） | `[]` |
| **质量钩子** | | |
| `hooks.post_build` | 构建后钩子 | `[]` |
| `hooks.pre_merge` | 合并前钩子 | `[]` |
| `hooks.post_merge` | 合并后钩子 | `[]` |
| **审查者** | | |
| `reviewer.enabled` | 启用对抗性审查 | `false` |
| `reviewer.model` | 审查模型（空=与构建者相同） | `""` |
| `reviewer.backend` | 审查后端（空=与构建者相同） | `""` |
| `reviewer.max_review_cycles` | 最大审查轮次 | `2` |
| **权限** | | |
| `permissions.analyst` | 分析师权限配置 | （默认完全访问） |
| `permissions.builder` | 构建者权限配置 | （默认完全访问） |
| `permissions.reviewer` | 审查者权限配置 | （默认完全访问） |
| **并行** | | |
| `parallel.max_builders` | 并发构建者数量 | `1` |
| `parallel.worktree_dir` | Worktree 根目录 | （自动） |
| `parallel.prefetch_analyst` | 构建期间后台预取分析任务 | `false` |
| `parallel.symlink_dirs` | 从主仓库 symlink 到 worktree 的目录 | `[]` |
| **收敛检测** | | |
| `convergence.check_window` | 检测窗口（最近指标数） | `5` |
| `convergence.min_diff_lines` | 触发阈值的最小 diff 行数 | `50` |
| `convergence.max_file_overlap_ratio` | 文件重叠度阈值 | `0.8` |
| **阶段覆盖** | | |
| `phase_config.{PHASE}.model` | 特定阶段的模型覆盖 | （Agent 默认） |
| `phase_config.{PHASE}.backend` | 特定阶段的后端覆盖 | （Agent 默认） |
| **Contract** | | |
| `contract.enabled` | 启用 Sprint Contract（编码前先规划方案） | `false` |

### 质量钩子

钩子在流水线阶段确定性地运行 shell 命令。不同于提示词指令，钩子保证执行。

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

- `required: true` — 失败则中止流水线步骤（任务标记为失败）
- `required: false` — 失败记录为警告，流水线继续

旧版 `tasks.build_command` 和 `tasks.quality_commands` 会自动转换为 `post_build` 钩子以保持兼容。

### Sprint Contract

启用后，每个任务在编码前会先经过规划-审查流程：

```
1. 分析师生成任务（含验收标准）
2. 构建者提出实施方案（Sprint Contract: 方法 + 验证标准）
3. 审查者审查方案
   ├─ 批准 → 构建者按方案实施
   └─ 要求修改 → 反馈给构建者修订方案 → 构建者按修订方案实施
4. 构建者根据方案执行任务
```

```json
{
  "contract": {
    "enabled": true
  }
}
```

### 权限沙箱

配置 `permissions` 时，每个角色获得一个受限配置文件，自动转换为后端原生参数：

```json
{
  "permissions": {
    "analyst": {"mode": "readonly"},
    "builder": {"mode": "full"},
    "reviewer": {"mode": "readonly", "allowed_tools": ["Read", "Glob", "Grep", "Bash"]}
  }
}
```

| 模式 | Claude Code | GitHub Copilot |
|------|-------------|----------------|
| `full` | `--dangerously-skip-permissions` | `--yolo` |
| `edit` | `--allowedTools Read,Edit,...` | `--available-tools Read,Edit,...` |
| `readonly` | `--allowedTools Read,Glob,Grep` | `--available-tools Read,Glob,Grep` |

未配置 `permissions` 时，所有角色默认完全访问（向后兼容）。

### 阶段级配置

为不同阶段使用不同模型或后端：

```json
{
  "phase_config": {
    "BUILD": {"model": "claude-opus-4-6"},
    "TEST": {"model": "claude-sonnet-4-6"},
    "FIX": {"model": "claude-sonnet-4-6"}
  }
}
```

## 抗收敛机制

| 层级 | 机制 | 说明 |
|------|------|------|
| 任务指纹 | SHA256 去重 | 相同任务永远不会被重复创建 |
| 视角轮转 | 9 个分析视角 | 每次分析使用不同的审视角度 |
| 区域注意力 | 时间戳追踪 | 优先处理最久未关注的区域 |
| 知识增长 | 自扩展规格 | AI 自动扩充知识库，膨胀任务来源 |
| 收敛检测 | 指标监控 | 检测 diff 缩减、文件重叠、代码停滞 |
| 强制逃逸 | 自动干预 | 检测触发时轮转视角 + 强制 EVOLVE 阶段 |

## 自定义 Agent 后端

实现 `AgentBackend` 接口并注册：

```python
from autoforge.agents import AgentBackend, SessionResult, register_backend

class MyBackend(AgentBackend):
    @property
    def name(self) -> str:
        return "my_backend"

    def check_available(self) -> bool:
        # 检查你的 CLI/SDK 是否可用
        ...

    def run_session(self, prompt, working_dir, timeout_minutes=30,
                    prompt_save_path=None, permission_profile=None) -> SessionResult:
        # 运行 Agent 并返回结果
        ...

register_backend("my_backend", MyBackend)
```

在配置中使用：
```json
{"agent": {"backend": "my_backend"}}
```

## 项目结构

```
autoforge/
├── agents/
│   ├── __init__.py          # 后端注册表
│   ├── base.py              # AgentBackend 抽象类 + SessionResult
│   ├── claude_code.py       # Claude Code CLI 后端
│   └── ghcp.py              # GitHub Copilot CLI 后端
├── templates/
│   ├── en/                  # 英文提示词模板
│   └── zh/                  # 中文提示词模板
├── orchestrator.py          # 主循环 + CLI 入口
├── config.py                # 配置数据类 + 加载器
├── db.py                    # SQLite 状态数据库
├── hooks.py                 # 确定性生命周期钩子
├── reviewer.py              # Writer-Reviewer 模式
├── permissions.py           # 权限配置
├── metrics.py               # Session 指标追踪
├── prompts.py               # 基于模板的提示词生成
├── convergence.py           # 收敛检测
├── parallel.py              # Git worktree 并行执行
├── state.py                 # 项目状态采集
└── runner.py                # 关闭协调
```

## 许可证

MIT
