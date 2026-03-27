# AutoForge — 无限自主进化开发框架

一个通用的、任务无关的无限自主开发框架。通过 Copilot CLI 的 autopilot 模式，让 AI 在无人干预下持续推进任何软件项目，且永不收敛。

## 核心特性

- **无限运行**: while-true 编排循环 + 崩溃自恢复
- **永不收敛**: 多视角轮换 + 任务指纹去重 + 收敛检测 + 区域注意力平衡
- **自我进化**: AI 自主扩充知识库 → 生成新任务 → 执行任务 → 循环
- **任务无关**: 只需提供一个 `seed.md` 种子文件即可驱动任何项目
- **目录隔离**: `workspace_dir` 和 `data_dir` 完全可配置，不污染其他位置
- **始终可运行**: 每个任务完成后项目必须仍然可以编译和运行

## 架构

```
双会话循环:
  ┌──────────┐      ┌──────────┐
  │ ANALYST  │─────▶│ BUILDER  │
  │ 分析+生成 │      │ 执行任务  │
  └──────────┘      └──────────┘

四相位旋转:
  BUILD → TEST → FIX → EVOLVE → BUILD → ...

九视角轮换:
  功能缺口 → Bug猎人 → 测试覆盖 → 性能审计 →
  代码质量 → 内容完整性 → 交互体验 → 系统集成 → 资源管线 → ...
```

## 目录结构

```
autoforge/                         # 框架代码
├── autoforge/                     # Python 包
│   ├── orchestrator.py            # 主编排循环
│   ├── config.py                  # 配置加载
│   ├── db.py                      # SQLite 状态数据库
│   ├── state.py                   # 项目状态收集
│   ├── convergence.py             # 收敛检测
│   ├── prompts.py                 # Prompt 生成
│   ├── runner.py                  # Copilot CLI 调用
│   └── quality_gate.py            # 质量门禁
├── autoforge_config.template.json # 配置模板（复制为 autoforge_config.json 使用）
├── start.ps1                      # PowerShell 启动脚本
└── start.bat                      # Windows 批处理启动

# 以下文件由用户创建，不纳入版本管理：
# autoforge_config.json            # 实际配置（从模板复制）
# seed.md                          # 种子文件（项目描述）

workspace_dir (用户配置):          # 实际项目代码
├── project.godot
├── Scripts/
├── Scenes/
└── ...

data_dir (用户配置):               # AutoForge 运行时数据
├── state.db                       # SQLite 状态数据库
├── knowledge/                     # 自增长知识库
│   ├── L2_features/
│   ├── L3_details/
│   └── L4_edge_cases/
├── prompts/                       # Prompt 存档（可调试）
├── logs/                          # 运行日志
├── next_tasks.json                # 分析师输出（临时）
└── task_result.md                 # 执行者输出（临时）
```

## 快速开始

### 1. 前置要求

- Python 3.10+
- [Copilot CLI](https://docs.github.com/copilot/how-tos/copilot-cli) (`copilot` 命令可用)
- Git

### 2. 配置

```powershell
cd D:\workspace\autoforge

# 从模板创建配置文件
Copy-Item autoforge_config.template.json autoforge_config.json

# 编辑配置：设定 workspace_dir、data_dir、copilot.model 等
notepad autoforge_config.json

# 创建种子文件：描述你的项目
notepad seed.md
```

配置文件只需设定框架运行参数，不包含任何项目特定内容：

```json
{
  "copilot": {
    "model": "claude-opus-4.6-1m"
  },
  "workspace_dir": "D:\\workspace\\MyProject",
  "seed_file": "./seed.md"
}
```

所有项目特定信息（技术栈、资源路径、功能规格等）都写在 `seed.md` 中。

### 3. 初始化

```powershell
python -m autoforge --init
```

### 4. 启动

```powershell
# 带崩溃恢复的无限循环（推荐）
.\start.ps1 -Loop

# 单次运行
.\start.ps1

# 直接 Python
python -m autoforge
```

### 5. 观察进度

```powershell
# 查看运行日志（data_dir 中）
Get-Content D:\workspace\MyProject\.autoforge\logs\*.log -Tail 50

# 查看 git 提交历史（workspace_dir 中）
cd D:\workspace\MyProject && git --no-pager log --oneline -20
```

## 配置项参考

以下为 `autoforge_config.json` 中可用的配置项：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `workspace_dir` | 项目代码工作目录 | `./workspace` |
| `data_dir` | 运行时数据目录（DB/知识库/日志） | `{workspace_dir}/.autoforge` |
| `seed_file` | 种子文件路径 | `./seed.md` |
| `copilot.path` | Copilot CLI 可执行文件路径 | `copilot` |
| `copilot.model` | AI 模型 | `claude-sonnet-4-20250514` |
| `copilot.effort` | 推理强度 | `high` |
| `copilot.timeout_minutes` | 单次会话超时 | `30` |
| `tasks.tasks_per_phase` | 每阶段执行任务数 | `5` |
| `tasks.max_retries` | 任务最大重试次数 | `3` |
| `tasks.cooldown_seconds` | 轮次间冷却时间 | `10` |
| `convergence.check_window` | 收敛检测窗口大小 | `5` |

## 种子文件 (seed.md) 编写指南

`seed.md` 是驱动整个项目的唯一输入，应包含：

1. **技术栈** — 引擎、语言、目标平台
2. **项目目标** — 要构建什么
3. **实现阶段** — 标注各功能的优先级和阶段，标记暂不实现的部分
4. **功能规格** — 越详细越好，分系统/模块描述
5. **资源信息** — 外部资源路径、数据来源（如有）
6. **约束规则** — 任何必须遵守的底线要求

**关键原则**: 种子文件中应标注实现阶段，确保 AI 循序渐进，每阶段产出可运行版本。

## 反收敛机制

| 层级 | 机制 | 原理 |
|------|------|------|
| 1 | 任务指纹去重 | SHA256 哈希，已完成任务永不重复 |
| 2 | 视角轮换 | 9种分析视角循环，天然产生不同类型任务 |
| 3 | 区域注意力平衡 | 追踪每个区域的关注度，优先选择被忽视的区域 |
| 4 | 知识库自增长 | AI 持续扩充规格文档，任务源不断膨胀 |
| 5 | 收敛检测 | 监控 diff 大小、文件重叠率、代码量变化 |
| 6 | 强制跳出 | 检测到收敛 → 切换视角 → 切换区域 → 进入 EVOLVE |

## License

MIT
