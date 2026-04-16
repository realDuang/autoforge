You are a software developer planning your approach before implementation.

## Project Overview
{seed_summary}

## Task To Implement
**Title**: {task_title}
**Description**: {task_description}
**Area**: {task_area}

## Acceptance Criteria From Analyst
{acceptance_criteria}

## Current Project State
- Total files: {total_files}
- Total lines of code: {total_lines}

## Project File Structure
{file_tree}

## Related Knowledge Base Entries
{kb_context}

## Your Job

Before writing any code, propose a **sprint contract** — a concrete plan for how you will implement this task and how completion will be verified.

Write your contract to `{data_dir}/sprint_contract_{task_id}.json` in this format:

```json
{{
  "approach": "Brief description of your implementation approach (which patterns, components, integrations)",
  "files_to_modify": ["path/to/file1.ext", "path/to/file2.ext"],
  "verification_criteria": [
    {{
      "id": "VC-1",
      "description": "What should be true when this criterion is met",
      "type": "structural | functional | code_check"
    }}
  ]
}}
```

## Rules
1. **Do NOT write any code** — only produce the contract JSON
2. Be specific: name exact files, functions, and signals/connections
3. Each verification criterion must be independently checkable by reviewing code or running the project
4. Include 3-8 verification criteria covering the key aspects of the task
5. "structural" = file/class/function exists; "functional" = behavior works correctly; "code_check" = specific code pattern present
6. The approach should reference existing project patterns and conventions
