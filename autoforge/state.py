"""Project state gathering for AutoForge."""
import os
import subprocess
from typing import Optional


def run_cmd(cmd: str, cwd: str, timeout: int = 30) -> str:
    """Run a shell command and return stdout."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, Exception):
        return ""


def count_files(workspace: str) -> int:
    count = 0
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        count += len([f for f in files if not f.startswith(".")])
    return count


def count_lines(workspace: str, extensions: Optional[set[str]] = None) -> int:
    if extensions is None:
        extensions = {
            ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".kt", ".scala",
            ".c", ".cpp", ".h", ".hpp", ".cs", ".go", ".rs", ".rb", ".php",
            ".swift", ".m", ".mm", ".lua", ".gd", ".sh", ".bash", ".ps1",
            ".json", ".yaml", ".yml", ".toml", ".xml", ".html", ".css",
            ".scss", ".sass", ".less", ".sql", ".graphql", ".proto",
            ".cfg", ".ini", ".conf", ".md", ".txt", ".rst",
        }
    total = 0
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if os.path.splitext(f)[1].lower() in extensions:
                try:
                    with open(os.path.join(root, f), "r", encoding="utf-8", errors="replace") as fh:
                        total += sum(1 for _ in fh)
                except (OSError, UnicodeDecodeError):
                    pass
    return total


def count_by_extension(workspace: str, ext: str) -> int:
    count = 0
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        count += len([f for f in files if f.endswith(ext)])
    return count


def get_file_tree(workspace: str, max_depth: int = 3, max_items: int = 200) -> str:
    """Generate a directory tree string."""
    lines = []
    item_count = 0

    for root, dirs, files in os.walk(workspace):
        dirs[:] = sorted([d for d in dirs if not d.startswith(".")])
        depth = root.replace(workspace, "").count(os.sep)
        if depth >= max_depth:
            dirs.clear()
            continue

        indent = "  " * depth
        folder_name = os.path.basename(root) or os.path.basename(workspace)
        lines.append(f"{indent}{folder_name}/")
        item_count += 1

        sub_indent = "  " * (depth + 1)
        for f in sorted(files):
            if not f.startswith("."):
                lines.append(f"{sub_indent}{f}")
                item_count += 1
                if item_count >= max_items:
                    lines.append(f"{sub_indent}... (truncated)")
                    return "\n".join(lines)

    return "\n".join(lines) if lines else "(empty workspace)"


def get_git_log(workspace: str, count: int = 10) -> str:
    return run_cmd(
        f'git --no-pager log --oneline -{count} --format="%h %s"', workspace
    )


def get_git_diff_stat(workspace: str) -> tuple[int, list[str]]:
    """Get total changed lines and list of modified files since last commit."""
    diff_output = run_cmd("git --no-pager diff --stat HEAD~1 HEAD 2>nul", workspace)
    if not diff_output:
        return 0, []

    lines = diff_output.strip().split("\n")
    modified_files = []
    total_changes = 0

    for line in lines:
        line = line.strip()
        if "|" in line:
            parts = line.split("|")
            fname = parts[0].strip()
            if fname:
                modified_files.append(fname)
            try:
                num_part = parts[1].strip().split()[0]
                total_changes += int(num_part)
            except (IndexError, ValueError):
                pass
        elif "changed" in line:
            # Summary line like "3 files changed, 100 insertions(+), 20 deletions(-)"
            import re
            nums = re.findall(r"(\d+) (?:insertion|deletion)", line)
            total_changes = sum(int(n) for n in nums)

    return total_changes, modified_files


def gather_project_state(workspace: str) -> dict:
    """Gather comprehensive project state."""
    return {
        "total_files": count_files(workspace),
        "total_lines": count_lines(workspace),
        "file_tree": get_file_tree(workspace),
        "git_log": get_git_log(workspace),
        "workspace": workspace,
    }
