#!/usr/bin/env python3
"""
s04_hooks.py - Hooks

Hooks run callbacks at fixed points in the agent loop:

    User prompt
         |
         v
    UserPromptSubmit
         |
         v
    +----------+      +-------+      +------------+      +-------+
    | messages | ---> |  LLM  | ---> | PreToolUse | ---> | Tool  |
    +----------+      +---+---+      | permission |      +---+---+
         ^                | stop     | log        |          |
         |                v          +------------+          v
         |            Stop hook                         PostToolUse
         |                                               |
         +---------------- tool_result ------------------+
"""

import os
import re
import subprocess
from pathlib import Path

try:
    import readline
    readline.parse_and_bind('set bind-tty-special-chars off')
    readline.parse_and_bind('set input-meta on')
    readline.parse_and_bind('set output-meta on')
    readline.parse_and_bind('set convert-meta off')
except ImportError:
    pass

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

ENVIRONMENT_PROMPT = (
    "Windows: the bash tool runs through cmd.exe; use cmd.exe syntax, not Unix "
    "Bash or PowerShell syntax, and prefer dedicated file tools for file operations"
    if os.name == "nt"
    else "Unix-like: the bash tool runs the system shell"
)
SYSTEM = (
    f"You are a coding agent at {WORKDIR}. Environment: {ENVIRONMENT_PROMPT}. "
    "Use tools to solve tasks. Act, don't explain."
)


# -- From s02-s03: tool implementations --

def run_bash(command: str) -> str:
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, errors="replace", timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

def run_read(path: str, limit: int | None = None) -> str:
    try:
        file_path = (WORKDIR / path).resolve()
        lines = file_path.read_text(encoding="utf-8").splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"

def run_write(path: str, content: str) -> str:
    try:
        file_path = (WORKDIR / path).resolve()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"

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
]

TOOL_HANDLERS = {
    "bash": run_bash, "read_file": run_read, "write_file": run_write,
    "edit_file": run_edit, "glob": run_glob,
}


# -- New in s04: hook system (s03 permission logic now uses hooks) --
# Hook（钩子）系统：在程序运行的特定时刻，自动调用你提前登记好的函数。

# HOOKS：保存每个时机需要执行哪些函数
# UserPromptSubmit：用户输入后，发送给 LLM 前
# PreToolUse：LLM 生成工具调用前
# PostToolUse：工具调用后，结果返回给 LLM 前
# Stop：循环结束前
HOOKS = {"UserPromptSubmit": [], "PreToolUse": [], "PostToolUse": [], "Stop": []}

# 把函数登记到某个事件，登记之后，列表里存放的是函数
def register_hook(event: str, callback):
    # 注册时没有括号，是因为我们要保存函数，等事件发生时再加上括号表示调用。
    # callback 就是这种 传进去、稍后被调用的函数，通常叫回调函数。
    HOOKS[event].append(callback)

# 按顺序执行已登记的函数
def trigger_hooks(event: str, *args):
    # *args 用于接收数量不固定的位置参数
    # 因此，同一个触发函数可以服务于不同参数数量的事件。
    # 不过，同一个事件下登记的函数，都必须能接收该事件传入的参数。
    for callback in HOOKS[event]:
        result = callback(*args)
        # Hook 返回值为 None 则 继续执行下一个 Hook
        # Hook 返回值不为 None 则 终止执行后续 Hook，并返回该值
        if result is not None:  # A hook result blocks this tool call.
            return result
    return None


# s03 permission check logic, now wrapped as a hook
DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if="]
DESTRUCTIVE_COMMAND_WORD = re.compile(
    r"(?i)(?:^|[;&|()\n])\s*(?:rm|del)(?=\s|$|[;&|()])"
)
DESTRUCTIVE = ["rm ", "> /etc/", "chmod 777"]

# 检查命令中是否包含破坏性命令的关键字
# 如果包含，则返回 True，否则返回 False
def contains_destructive_command(command: str) -> bool:
    return bool(DESTRUCTIVE_COMMAND_WORD.search(command))

# 把 s03 的权限检查放进 Hook
def permission_hook(block):
    """PreToolUse: s03 check_permission() logic moved here."""
    # 针对 bash 检查硬性禁止项
    if block.name == "bash":
        command = block.input.get("command", "")
        for pattern in DENY_LIST:
            # 命中后直接返回拒绝原因，不询问用户。
            if pattern in command:
                print(f"\n\033[31m[blocked] '{pattern}'\033[0m")
                return "Permission denied by deny list"

        # 其次，对可能有破坏性的命令进行确认
        if contains_destructive_command(command) or any(
            kw in command for kw in DESTRUCTIVE
        ):
            print(f"\n\033[33m[permission] Potentially destructive command\033[0m")
            print(f"   Tool: {block.name}({block.input})")

            # 需要用户确认；用户拒绝时返回字符串。
            choice = input("   Allow? [y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                return "Permission denied by user"

    # 对文件工具检查路径
    if block.name in ("read_file", "write_file", "edit_file"):
        path = block.input.get("path", "")

        # 访问工作目录外的文件，需要用户确认。
        if not (WORKDIR / path).resolve().is_relative_to(WORKDIR):
            print(f"\n\033[33m[permission] Access outside workspace\033[0m")
            print(f"   Tool: {block.name}({block.input})")

            # 需要用户确认；用户拒绝时返回字符串。
            choice = input("   Allow? [y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                return "Permission denied by user"

    # 如果没有命中限制，或者用户允许，就走到这里，返回 None 表示允许执行。
    # 现在 None 代表 我没有拦截理由，继续。
    return None

# 打印工具调用的简短日志
# 权限 Hook 排在日志 Hook 前面，因此，被权限 Hook 拒绝的请求不会经过这个日志函数
def log_hook(block):
    """PreToolUse: log every tool call."""
    # 取出工具调用的参数值（字典的值），转成列表后取前两个，转成字符串后截取前 60 个字符
    args_preview = str(list(block.input.values())[:2])[:60]

    # 一个示例：[HOOK] write_file(['hello.py', 'print("你好呀")'])
    print(f"\033[90m[HOOK] {block.name}({args_preview})\033[0m")

    # 最后返回 None，说明日志功能不拦截调用。
    return None

# 工具执行后检查输出长度
def large_output_hook(block, output):
    """PostToolUse: warn on large output."""
    # 如果输出转换成字符串后，超过 100,000 个字符，就打印提醒。
    if len(str(output)) > 100000:
        print(f"\033[33m[HOOK] Large output from {block.name}: {len(str(output))} chars\033[0m")
    return None

# UserPromptSubmit hook: log user input before it reaches the LLM
# 目前只是打印工作目录，终端显示：[HOOK] UserPromptSubmit: working in /你的项目目录
def context_inject_hook(query: str):
    print(f"\033[90m[HOOK] UserPromptSubmit: working in {WORKDIR}\033[0m")
    return None

# Stop hook: print summary when loop is about to exit
# 统计历史中的工具结果数量
def summary_hook(messages: list):
    tool_count = sum(1 for m in messages
                     for b in (m.get("content") if isinstance(m.get("content"), list) else [])
                     if isinstance(b, dict) and b.get("type") == "tool_result")
    print(f"\033[90m[HOOK] Stop: session used {tool_count} tool calls\033[0m")
    return None


# 最后的注册代码，决定了整个系统的行为
# Agent 主流程只需要在几个固定位置触发事件；权限、日志、输出检查等功能，则通过注册函数接入。 
# 以后增加功能时，就可以新增 Hook，而不必把所有逻辑都堆进工具执行循环里。
register_hook("UserPromptSubmit", context_inject_hook)
register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook)
register_hook("PostToolUse", large_output_hook)
register_hook("Stop", summary_hook)


# -- Agent loop: same structure as s03, but no hard-coded check --
# s03: if not check_permission(block): ...
# s04: if trigger_hooks("PreToolUse", block): ...

def agent_loop(messages: list):
    while True:
        # 把当前对话发给模型，并保存回复
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})

        # 从模型回复里找出工具调用
        tool_calls = [
            block for block in response.content if block.type == "tool_use"
        ]

        # 如果没有工具调用，先触发 Stop Hook
        if not tool_calls:
            force = trigger_hooks("Stop", messages)
            # 返回真值 → 把返回内容交给模型，继续循环
            if force:
                messages.append({"role": "user", "content": force})
                continue
            # 返回假值 → 结束函数
            return

        # 有工具调用时，为本轮准备结果列表
        results = []
        for block in tool_calls:
            # s04 change: hook replaces hard-coded check_permission()
            # 执行工具之前，触发 PreToolUse Hook
            # 如果权限 Hook 返回拒绝原因，trigger_hooks() 会提前返回，日志 Hook 就不会运行。
            blocked = trigger_hooks("PreToolUse", block)
            
            # 把拒绝原因作为这个工具调用的结果，然后跳过实际执行。
            # 拒绝也要返回结果，这样模型才能知道这次请求没有执行。
            if blocked:
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": str(blocked)})
                # 它跳过的是当前工具调用，然后继续处理下一个工具。它不会立即回到外层的模型请求循环。
                continue

            # 执行工具调用
            handler = TOOL_HANDLERS.get(block.name)
            output = handler(**block.input) if handler else f"Unknown: {block.name}"

            # 工具执行后，触发 PostToolUse Hook
            trigger_hooks("PostToolUse", block, output)  # s04: post hook

            # 把工具执行结果加入本轮结果列表
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})

        # 把本轮结果列表作为用户消息，交给模型
        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    print("s04: Hooks - extension logic on hooks, loop stays clean")
    print("Enter a question, press Enter to send. Type q to quit.\n")

    history = []
    while True:
        try:
            # \001/\002 tell Readline the ANSI escapes have zero display width.
            query = input("\001\033[36m\002s04 >> \001\033[0m\002")
        except (EOFError, KeyboardInterrupt):
            break
        if not query.strip():
            continue
        if query.strip().lower() in ("q", "exit"):
            break
        # 触发用户输入 Hook 打印工作目录
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
