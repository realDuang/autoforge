"""Prompt generation for AutoForge analyst and builder sessions."""
import os
from typing import Optional


def _read_file(path: str, max_chars: int = 8000) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars)
        if len(content) >= max_chars:
            content += "\n... (truncated)"
        return content
    except OSError:
        return "(file not found)"


def _format_completed_tasks(tasks: list[dict]) -> str:
    if not tasks:
        return "(none yet)"
    lines = []
    for t in tasks:
        lines.append(f"- [{t.get('area', '?')}] {t.get('title', '?')}")
    return "\n".join(lines)


def _format_areas(areas: list[str]) -> str:
    if not areas:
        return "(no area data yet — this is likely the first run)"
    return "\n".join(f"- {a}" for a in areas)


def _gather_knowledge_summary_text(knowledge_dir: str) -> str:
    """Read knowledge base files and produce a summary."""
    if not os.path.isdir(knowledge_dir):
        return "(knowledge base not yet created — you should create it)"

    lines = []
    for root, dirs, files in os.walk(knowledge_dir):
        dirs.sort()
        for fname in sorted(files):
            if fname.endswith(".md"):
                rel = os.path.relpath(os.path.join(root, fname), knowledge_dir)
                lines.append(f"- {rel}")
    if not lines:
        return "(knowledge base directory exists but is empty — populate it)"
    return "\n".join(lines)


def generate_analyst_prompt(
    seed_content: str,
    project_state: dict,
    knowledge_dir: str,
    knowledge_db_summary: dict,
    perspective: dict,
    recent_completed: list[dict],
    least_touched_areas: list[str],
    loop_count: int,
    data_dir: str = ".autoforge",
    phases: list[str] | None = None,
) -> str:
    """Generate the analyst session prompt."""

    kb_file_list = _gather_knowledge_summary_text(knowledge_dir)
    completed_text = _format_completed_tasks(recent_completed)
    areas_text = _format_areas(least_touched_areas)
    kb_stats = knowledge_db_summary
    kb_level_dist = kb_stats.get('by_level', {})
    data_dir_label = data_dir.replace("\\", "/")

    if phases is None:
        phases = ["BUILD", "TEST", "FIX"]
    phase_labels = {"BUILD": "新功能", "TEST": "编写测试", "FIX": "修复问题"}
    phase_text = "、".join(f"{p}（{phase_labels.get(p, p)}）" for p in phases if p != "EVOLVE")

    return f"""你是一个项目分析师。你的工作是分析当前项目状态并生成新的开发任务。
这是自动化编排器的第 {loop_count} 轮迭代。

## 项目描述
{seed_content}

## 当前项目状态
- 文件总数: {project_state.get('total_files', 0)}
- 代码总行数: {project_state.get('total_lines', 0)}
- 已完成任务总数: {len(recent_completed)} (最近)

## 项目文件结构
{project_state.get('file_tree', '(empty)')}

## 最近 Git 提交
{project_state.get('git_log', '(no commits yet)')}

## 知识库状态
- 总条目: {kb_stats.get('total', 0)}
- 已实现: {kb_stats.get('implemented', 0)}
- 未实现: {kb_stats.get('not_implemented', 0)}
- 层级分布: {kb_level_dist}

知识库文件:
{kb_file_list}

## 最近完成的任务（避免生成重复任务）
{completed_text}

## 当前分析视角: {perspective.get('label', '?')}
{perspective.get('desc', '')}

## 最需要关注的区域（长期被忽视）
{areas_text}

## 你的工作

1. 从「{perspective.get('label', '?')}」视角审视整个项目
2. 对比项目描述和知识库与当前实现，找出差距和改进点
3. 生成 5-10 个**全新的**开发任务
4. 将任务列表写入 `{data_dir_label}/next_tasks.json`，格式：
   ```json
   [
     {{
       "title": "任务标题（具体明确）",
       "description": "详细描述，包括具体要做什么、怎么做、验收标准",
       "area": "所属区域（如 character, combat, map, ui, skill, monster, item, quest, npc, audio, core, job, equip, resource, effect）",
       "priority": 5,
       "phase": "BUILD"
     }}
   ]
   ```
5. 如果发现知识库中缺少的特性细节，将补充内容写入 `{data_dir_label}/knowledge/` 下对应层级目录的 .md 文件中
6. 如果知识库还不存在或太薄，优先创建和充实它

## 规则
- **循序渐进**: 严格遵循项目描述中的实现阶段和优先级标注，不要跳到标记为「暂不实现」的系统
- **保持可运行**: 每个任务完成后项目必须仍然可以运行，不能引入编译错误或崩溃
- 每个任务必须**具体可执行**，一个 AI 会话内可完成（约30分钟工作量）
- 不要生成与「最近完成的任务」重复或高度相似的任务
- 优先关注「最需要关注的区域」
- priority 范围 1-10，1 最高优先级
- phase 取值: {phase_text}
- 任务描述要包含足够上下文，让执行者无需额外信息即可开始工作
"""


def generate_builder_prompt(
    seed_content: str,
    task: dict,
    project_state: dict,
    knowledge_dir: str,
    related_knowledge_files: list[str],
    data_dir: str = ".autoforge",
    task_result_filename: str = "task_result.md",
    build_command: str = "",
) -> str:
    """Generate the builder session prompt."""

    # Read relevant knowledge entries
    kb_context_parts = []
    for kf in related_knowledge_files[:5]:  # limit to 5 files
        full_path = os.path.join(knowledge_dir, kf)
        if os.path.isfile(full_path):
            content = _read_file(full_path, max_chars=3000)
            kb_context_parts.append(f"### {kf}\n{content}")
    kb_context = "\n\n".join(kb_context_parts) if kb_context_parts else "(no related knowledge entries)"

    # Get seed summary (first 1500 chars — includes tech stack + resource info)
    seed_summary = seed_content[:1500]
    if len(seed_content) > 1500:
        seed_summary += "\n..."

    task_area = task.get("area", "general")
    data_dir_label = data_dir.replace("\\", "/")

    prompt_text = f"""你是一名软件开发者，正在参与以下项目的开发。

## 项目概述
{seed_summary}

## 你的当前任务
**标题**: {task.get('title', '?')}
**描述**: {task.get('description', '?')}
**区域**: {task_area}
**优先级**: {task.get('priority', 5)}

## 项目当前状态
- 文件总数: {project_state.get('total_files', 0)}
- 代码总行数: {project_state.get('total_lines', 0)}

## 项目文件结构
{project_state.get('file_tree', '(empty)')}

## 相关知识库条目
{kb_context}

## 最近 Git 提交
{project_state.get('git_log', '(no commits yet)')}

## 规则
1. **只做上述指定的任务**，不要修改与任务无关的文件
2. 当前工作目录就是项目根目录
3. 遵循项目现有的代码风格和目录结构
4. **完成后项目必须可运行**: 确保没有编译错误
5. 将工作总结写入 `{data_dir_label}/{task_result_filename}`，包括：
   - 做了什么
   - 创建/修改了哪些文件
   - 是否遇到问题
   - 验证结果
6. 如果遇到无法解决的阻塞问题，在 {task_result_filename} 中说明原因
7. 代码要有合理的注释，但不要过度注释
"""
    if build_command:
        prompt_text += f"""8. **⚠ 编译检查（必须）**：完成代码修改后，必须运行 `{build_command}` 确认 0 个编译错误。如果有编译错误，必须修复后再结束任务。
"""

    return prompt_text


def find_related_knowledge_files(knowledge_dir: str, area: str) -> list[str]:
    """Find knowledge base files related to a given area."""
    if not os.path.isdir(knowledge_dir):
        return []

    related = []
    area_lower = area.lower()

    for root, dirs, files in os.walk(knowledge_dir):
        dirs.sort()
        for fname in sorted(files):
            if not fname.endswith(".md"):
                continue
            rel = os.path.relpath(os.path.join(root, fname), knowledge_dir)
            fname_lower = fname.lower()
            # Match by area keyword in filename
            if area_lower in fname_lower or any(
                kw in fname_lower
                for kw in _area_keywords(area_lower)
            ):
                related.append(rel)

    # If nothing matched, return overview files
    if not related:
        for root, dirs, files in os.walk(knowledge_dir):
            for fname in sorted(files):
                if fname.endswith(".md") and ("overview" in fname.lower() or "L1" in fname):
                    related.append(
                        os.path.relpath(os.path.join(root, fname), knowledge_dir)
                    )
    return related[:10]


def _area_keywords(area: str) -> list[str]:
    """Map area names to related search keywords."""
    mapping = {
        "character": ["char", "player", "stat", "level", "exp"],
        "combat": ["fight", "attack", "damage", "battle", "hit"],
        "map": ["map", "tile", "platform", "portal", "world"],
        "ui": ["ui", "hud", "interface", "menu", "window", "gui"],
        "skill": ["skill", "ability", "spell", "buff"],
        "monster": ["monster", "mob", "enemy", "boss", "spawn"],
        "item": ["item", "equip", "inventory", "potion", "scroll"],
        "quest": ["quest", "mission", "objective", "reward"],
        "npc": ["npc", "dialog", "shop", "vendor"],
        "audio": ["audio", "sound", "music", "bgm", "sfx"],
        "core": ["core", "engine", "system", "base", "util"],
        "job": ["job", "class", "warrior", "mage", "archer", "thief"],
        "validation": ["validation", "validate", "verify", "test", "quality", "check"],
    }
    return mapping.get(area, [area])
