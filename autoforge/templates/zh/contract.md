你是一名软件开发者，在动手实现之前先规划你的方案。

## 项目概述
{seed_summary}

## 待实现的任务
**标题**: {task_title}
**描述**: {task_description}
**区域**: {task_area}

## 分析师给出的验收标准
{acceptance_criteria}

## 项目当前状态
- 文件总数: {total_files}
- 代码总行数: {total_lines}

## 项目文件结构
{file_tree}

## 相关知识库条目
{kb_context}

## 你的工作

在编写任何代码之前，先提出一份 **Sprint 合同** — 一个具体的实现计划，说明你将如何实现此任务以及如何验证完成情况。

将合同写入 `{data_dir}/sprint_contract_{task_id}.json`，格式：

```json
{{
  "approach": "简述你的实现方案（使用什么模式、组件、集成方式）",
  "files_to_modify": ["path/to/file1.ext", "path/to/file2.ext"],
  "verification_criteria": [
    {{
      "id": "VC-1",
      "description": "满足此标准时应该为真的条件",
      "type": "structural | functional | code_check"
    }}
  ]
}}
```

## 规则
1. **不要编写任何代码** — 只输出合同 JSON
2. 要具体：指明确切的文件、函数和信号/连接
3. 每条验证标准必须可以通过审查代码或运行项目来独立检验
4. 包含 3-8 条验证标准，覆盖任务的关键方面
5. "structural" = 文件/类/函数存在；"functional" = 行为正确运作；"code_check" = 特定代码模式存在
6. 方案应参考项目现有的模式和惯例
