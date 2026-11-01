#!/usr/bin/env python3
"""
s05_todo_write.py - TodoWrite

The model tracks its progress through a TodoManager. After three rounds
without an update, the harness adds a reminder alongside the tool results.

    +----------+      +-------+      +--------------+
    |   User   | ---> |  LLM  | ---> | Tools        |
    |  prompt  |      |       |      | + todo_write |
    +----------+      +---^---+      +------+-------+
                          |                 | update
                          |          +------v----------+
                          |          | TodoManager     |
                          |          | [ ] pending     |
                          |          | [>] in progress |
                          |          | [x] completed   |
                          |          +------+----------+
                          | tool_result     |
                          +-----------------+

              rounds_since_todo >= 3 -> add <reminder>
"""

import ast
import json
import os
import re
import subprocess
from pathlib import Path

try:
    import readline
    readline.parse_and_bind('set bind-tty-special-chars off')
except ImportError:
    pass

from anthropic import Anthropic
from dotenv import load_dotenv

# load_dotenv() 从找到的 .env 文件中加载配置；
# override=True 表示覆盖已有的同名环境变量。
load_dotenv(override=True)
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

# s05 change: SYSTEM prompt adds planning guidance
# 根据操作系统选择适合的说明
ENVIRONMENT_PROMPT = (
    "Windows: the bash tool runs through cmd.exe; use cmd.exe syntax, not Unix "
    "Bash or PowerShell syntax, and prefer dedicated file tools for file operations"
    if os.name == "nt"
    else "Unix-like: the bash tool runs the system shell"
)

# 在开始任何多步骤任务前，先使用 todo_write 制定步骤计划；执行过程中持续更新状态。
SYSTEM = (
    f"You are a coding agent at {WORKDIR}. Environment: {ENVIRONMENT_PROMPT}. "
    "Before starting any multi-step task, use todo_write to plan your steps. "
    "Update status as you go."
)


# -- Tool implementations from s02-s04 --
# 执行终端命令
def run_bash(command: str) -> str:
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, errors="replace", timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

# 读取文件，可限制返回行数
def run_read(path: str, limit: int | None = None) -> str:
    try:
        lines = (WORKDIR / path).resolve().read_text(encoding="utf-8").splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"

# 写入整个文件
def run_write(path: str, content: str) -> str:
    try:
        file_path = (WORKDIR / path).resolve()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"

# 只替换第一次匹配的文字
def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        file_path = (WORKDIR / path).resolve()
        text = file_path.read_text(encoding="utf-8")
        if old_text not in text:
            return f"Error: text not found in {path}"
        file_path.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"

# 按文件名模式查找路径
def run_glob(pattern: str) -> str:
    import glob as g
    try:
        matches = sorted({
            match for match in g.glob(
                pattern, root_dir=WORKDIR, recursive=True)
            if (WORKDIR / match).resolve().is_relative_to(WORKDIR)
        })
        shown = matches[:200]
        if len(matches) > 200:
            shown.append("... (more matches omitted; narrow the pattern)")
        return "\n".join(shown) if shown else "(no matches)"
    except Exception as e:
        return f"Error: {e}"


# -- New in s05: structured state the model updates --

class TodoManager:
    """管理任务列表的对象"""
    # 数据：当前有哪些任务。
    # 操作：更新任务、把任务转换成可读文字。
    def __init__(self):
        # 保存的任务列表
        self.items: list[dict] = []

    def update(self, todos: list | str) -> str:
        """接收新清单，校验后替换旧清单"""
        # 可以直接传 Python 列表
        # 或者传一个包含列表的字符串
        if isinstance(todos, str):
            try:
                # 如果 todos 是字符串，先尝试把它当 JSON 解析。
                # 例如 '[{"content": "读取文件", "status": "pending"}]'
                todos = json.loads(todos)
            except json.JSONDecodeError:
                try:
                    # 如果 JSON 解析失败，再尝试按 Python 字面量格式解析。
                    # 例如 "[{'content': '读取文件', 'status': 'pending'}]"
                    # 它不是合法 JSON，但可以由 ast.literal_eval() 解析。
                    todos = ast.literal_eval(todos)
                except (SyntaxError, ValueError) as e:
                    raise ValueError("todos must be a list or JSON array string") from e

        # 解析成功不代表类型正确，所以还要检查 todos 是否是列表。
        # 检查最外层必须是列表
        if not isinstance(todos, list):
            raise ValueError("todos must be a list")

        # 限制任务数量，最多 20 条。
        if len(todos) > 20:
            raise ValueError("Max 20 todos allowed")

        # 逐条检查任务内容
        validated = []          # 保存通过校验、整理后的任务。
        in_progress_count = 0   # 统计进行中的任务数量。

        for index, todo in enumerate(todos):
            # 每条任务必须是字典对象
            if not isinstance(todo, dict):
                raise ValueError(f"todos[{index}] must be an object")

            # 提取内容和状态
            content = str(todo.get("content", "")).strip()
            status = str(todo.get("status", "pending")).lower()

            # 检查内容不能为空
            if not content:
                raise ValueError(f"todos[{index}] requires content")

            # 检查状态必须是以下三种之一
            # 待开始、进行中、已完成    
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"todos[{index}] has invalid status '{status}'")

            # 统计进行中的任务数量
            if status == "in_progress":
                in_progress_count += 1

            # 保存校验后的任务
            validated.append({"content": content, "status": status})

        # 检查进行中的任务数量不能超过 1
        if in_progress_count > 1:
            raise ValueError("Only one todo can be in_progress at a time")

        # 全部检查通过后，替换对象中保存的任务
        # 这是整体替换，不是追加或局部修改。更新某条状态时，应传入希望保留的完整清单。
        self.items = validated

        return self.render()

    def render(self) -> str:
        """把结构化数据转换成可读清单"""
        # 没有任务时返回提示
        if not self.items:
            return "No todos."

        # 有任务时，逐条选择显示标记
        lines = []

        # 先建立映射，再按状态取对应值
        for todo in self.items:
            marker = {
                "pending": "[ ]",
                "in_progress": "[>]",
                "completed": "[x]",
            }[todo["status"]]
            lines.append(f"{marker} {todo['content']}")

        # 统计完成数量
        done = sum(todo["status"] == "completed" for todo in self.items)

        # 在清单末尾显示完成统计 (1/3 completed)
        lines.append(f"\n({done}/{len(self.items)} completed)")

        # 返回最终的多行字符串
        return "\n".join(lines)


# 创建一个共享的清单管理对象。在同一个进程里，每次调用工具都操作这个对象。
TODO = TodoManager()


# 给 Agent 调用的工具函数
def run_todo_write(todos: list | str) -> str:
    try:
        # 接收 todos，TODO.update() 解析并校验
        output = TODO.update(todos)
    except ValueError as e:
        return f"Error: {e}"
    print(f"\n\033[33m## Current Tasks\033[0m\n{output}")
    return output

TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to a file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in a file once.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "glob", "description": "Find files matching a glob pattern; ** matches recursively.",
     "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}},
    
    # s05: new tool
    # 指定新的工具和调用参数格式
    {"name": "todo_write", "description": "Create and manage a task list for your current coding session.",
     "input_schema": {"type": "object", "properties": {"todos": {"type": "array", "maxItems": 20, "items": {"type": "object", "properties": {"content": {"type": "string", "minLength": 1}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}}, "required": ["content", "status"]}}}, "required": ["todos"]}},
]


# 已经有 schema，为什么 update() 还要校验
# schema 描述工具接口，帮助模型和服务生成、处理参数。
# Python 校验维护程序自身的数据规则，不能只依赖外部输入符合要求。


# 函数分发表
TOOL_HANDLERS = {
    "bash": run_bash, "read_file": run_read, "write_file": run_write,
    "edit_file": run_edit, "glob": run_glob, "todo_write": run_todo_write,
}


# -- Hook system from s04 --

HOOKS = {"UserPromptSubmit": [], "PreToolUse": [], "PostToolUse": [], "Stop": []}

def register_hook(event: str, callback):
    HOOKS[event].append(callback)

def trigger_hooks(event: str, *args):
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:
            return result
    return None

DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if="]
DESTRUCTIVE_COMMAND_WORD = re.compile(
    r"(?i)(?:^|[;&|()\n])\s*(?:rm|del)(?=\s|$|[;&|()])"
)
DESTRUCTIVE = ["rm ", "> /etc/", "chmod 777"]


def contains_destructive_command(command: str) -> bool:
    return bool(DESTRUCTIVE_COMMAND_WORD.search(command))


def permission_hook(block):
    """PreToolUse: s03 permission logic, registered as an s04 hook."""
    # 针对 bash 工具的检查
    if block.name == "bash":
        command = block.input.get("command", "")

        # 检查命令是否在 deny list 中
        for pattern in DENY_LIST:
            if pattern in command:
                print(f"\n\033[31m[blocked] '{pattern}'\033[0m")
                return "Permission denied by deny list"

        # 是否包含潜在破坏性命令
        if contains_destructive_command(command) or any(
            keyword in command for keyword in DESTRUCTIVE
        ):
            print(f"\n\033[33m[permission] Potentially destructive command\033[0m")
            print(f"   Tool: {block.name}({block.input})")

            # 询问用户是否允许执行潜在破坏性命令
            choice = input("   Allow? [y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                return "Permission denied by user"

    # 针对文件操作工具的检查
    if block.name in ("read_file", "write_file", "edit_file"):
        path = block.input.get("path", "")

        # 检查路径是否在工作目录之外
        if not (WORKDIR / path).resolve().is_relative_to(WORKDIR):
            print(f"\n\033[33m[permission] Access outside workspace\033[0m")
            print(f"   Tool: {block.name}({block.input})")

            # 询问用户是否允许访问工作目录之外的路径
            choice = input("   Allow? [y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                return "Permission denied by user"

    # 如果没有阻止条件，返回 None 表示允许执行
    return None

# 打印工具调用日志，显示工具名称和前两个参数的预览
def log_hook(block):
    """PreToolUse: log every tool call."""
    args_preview = str(list(block.input.values())[:2])[:60]
    print(f"\033[90m[HOOK] {block.name}({args_preview})\033[0m")
    return None

# 检查工具输出是否过大，如果超过 100000 字符，打印警告
def large_output_hook(block, output):
    """PostToolUse: warn on large output."""
    if len(str(output)) > 100000:
        print(f"\033[33m[HOOK] Large output from {block.name}: {len(str(output))} chars\033[0m")
    return None

# 在用户提交提示时，打印当前工作目录
def context_inject_hook(query: str):
    """UserPromptSubmit: log working directory."""
    print(f"\033[90m[HOOK] UserPromptSubmit: working in {WORKDIR}\033[0m")
    return None

# 在会话结束时，统计工具调用次数并打印
def summary_hook(messages: list):
    """Stop: print tool call count."""
    tool_count = sum(1 for m in messages
                     for b in (m.get("content") if isinstance(m.get("content"), list) else [])
                     if isinstance(b, dict) and b.get("type") == "tool_result")
    print(f"\033[90m[HOOK] Stop: session used {tool_count} tool calls\033[0m")
    return None


# 注册钩子函数到相应的事件
register_hook("UserPromptSubmit", context_inject_hook)
register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook)
register_hook("PostToolUse", large_output_hook)
register_hook("Stop", summary_hook)


# -- Agent loop with the reminder counter --

def agent_loop(messages: list):
    # 为当前任务创建一个计数器
    # 距离上一次调用 todo_write，已经连续处理了多少轮工具调用。
    # 每次你提出新问题，重新调用 agent_loop(history) 时，它都会从 0 开始，不会跨用户提问累计。
    rounds_since_todo = 0

    while True:
        # 把当前历史和工具定义发给模型，再保存模型回复。
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})

        # 只筛选出需要执行的工具调用，普通文本不会被当作命令执行。
        tool_calls = [
            block for block in response.content if block.type == "tool_use"
        ]

        # 如果没有工具调用，检查是否可以结束
        if not tool_calls:
            force = trigger_hooks("Stop", messages)
            if force:
                messages.append({"role": "user", "content": force})
                continue
            return

        results = []        # 保存本轮所有工具结果
        used_todo = False   # 标记本轮是否调用了 todo_write 工具   

        for block in tool_calls:
            blocked = trigger_hooks("PreToolUse", block)
            # 如果 PreToolUse Hook 返回拦截原因，就把原因作为工具结果，不执行工具。
            if blocked:
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": str(blocked)})
                continue

            # 找到执行函数，并捕获工具执行异常
            handler = TOOL_HANDLERS.get(block.name)
            try:
                output = handler(**block.input) if handler else f"Unknown: {block.name}"
            except Exception as e:
                output = f"Error: {e}"

            # 工具执行完成后，触发输出检查
            trigger_hooks("PostToolUse", block, output)

            # 只要处理到名为 todo_write 的调用，就把本轮标记为使用过 todo。
            if block.name == "todo_write":
                used_todo = True

            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": str(output)})

        # 本轮结束后，更新计数器
        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1

        # 连续三轮没更新，就在工具结果后追加提醒，一个普通文本内容块
        if rounds_since_todo >= 3:
            results.append({"type": "text",
                            "text": "<reminder>Update your todos.</reminder>"})
            rounds_since_todo = 0

        # 把工具结果和提醒一起交给下一轮模型。
        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    print("s05: TodoWrite - plan before execution")
    print("Enter a question, press Enter to send. Type q to quit.\n")

    history = []
    while True:
        try:
            # \001/\002 tell Readline the ANSI escapes have zero display width.
            query = input("\001\033[36m\002s05 >> \001\033[0m\002")
        except (EOFError, KeyboardInterrupt):
            break
        if not query.strip():
            continue
        if query.strip().lower() in ("q", "exit"):
            break

        trigger_hooks("UserPromptSubmit", query)
        history.append({"role": "user", "content": query})
        agent_loop(history)
        for block in history[-1]["content"]:
            if getattr(block, "type", None) == "text":
                print(block.text)
                
        print()
        print("======== the history ========")
        print(history)
        print("=============================")