#!/usr/bin/env python3
"""
s01_agent_loop.py - The Agent Loop

The entire secret of an AI coding agent in one pattern:

    while True:
        response = LLM(messages, tools)
        if response contains no tool_use:
            break
        execute tools
        append results

    +----------+      +-------+      +---------+
    |   User   | ---> |  LLM  | ---> |  Tool   |
    |  prompt  |      |       |      | execute |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool_result |
                          +---------------+
                          (loop continues)

This is the core loop: feed tool results back to the model
until the model decides to stop. Later chapters add policy,
hooks, and lifecycle controls around it.

Usage:
    pip install anthropic python-dotenv
    Configure ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL and MODEL_ID in .env.
    python s01_agent_loop/code-me.py

Alibaba Cloud Bailian (Beijing, pay-as-you-go):
    ANTHROPIC_API_KEY=<your Bailian API key>
    ANTHROPIC_BASE_URL=https://dashscope.aliyuncs.com/apps/anthropic
    MODEL_ID=qwen-plus
"""

import os
import subprocess
from pathlib import Path

try:
    import readline
    # #143 UTF-8 backspace fix for macOS libedit
    readline.parse_and_bind('set bind-tty-special-chars off')
    readline.parse_and_bind('set input-meta on')
    readline.parse_and_bind('set output-meta on')
    readline.parse_and_bind('set convert-meta off')
except ImportError:
    pass

from anthropic import Anthropic
from dotenv import load_dotenv

# Always use the project's .env, even when launched from another directory.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

missing = [name for name in ("ANTHROPIC_API_KEY", "MODEL_ID")
           if not os.getenv(name, "").strip()]
if missing:
    raise SystemExit(
        f"缺少配置：{', '.join(missing)}。请在项目根目录的 .env 中配置；"
        "百炼示例见 s01_agent_loop/bailian.env.example。"
    )

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

# os.name 表示 Python 所处的操作系统类型
# Windows 的 os.name 是 nt，Linux 和 macOS 的 os.name 是 posix
ENVIRONMENT_PROMPT = (
    "Windows: the bash tool runs through cmd.exe; use cmd.exe syntax, not Unix "
    "Bash or PowerShell syntax"
    if os.name == "nt"
    else "Unix-like: the bash tool runs the system shell"
)
SYSTEM = (
    f"You are a coding agent at {os.getcwd()}. Environment: {ENVIRONMENT_PROMPT}. "
    "Use bash to solve tasks. Act, don't explain."
)

# -- Tool definition: just bash --
TOOLS = [{
    "name": "bash",
    "description": "Run a shell command.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}]


# -- Tool execution --
def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
                           capture_output=True, text=True, errors="replace", timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"


# -- The core pattern: a while loop that calls tools until the model stops --
def agent_loop(messages: list):
    # messages 是一个列表，保存整个对话过程
    while True:
        # client.messages.create(...) 是向模型服务发请求。
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )

        # Append assistant turn
        # 这一步把模型刚返回的内容加入历史。
        messages.append({"role": "assistant", "content": response.content})

        # If the model didn't call a tool, we're done
        # 筛选工具调用
        tool_calls = [
            block for block in response.content if block.type == "tool_use"
        ]
        # 如果模型这次没有请求调用工具，就结束当前 Agent 循环。
        if not tool_calls:
            return

        # Execute each tool call, collect results
        results = []
        for block in tool_calls:
            print(f"\033[33m$ {block.input['command']}\033[0m")
            output = run_bash(block.input["command"])
            print(output[:200])
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
            })

        # Feed tool results back, loop continues
        messages.append({"role": "user", "content": results})


# -- Entry point --
if __name__ == "__main__":
    print("s01: Agent Loop")
    print("Enter a question, press Enter to send. Type q to quit.\n")

    history = []
    while True:
        try:
            # \001/\002 tell Readline the ANSI escapes have zero display width.
            query = input("\001\033[36m\002s01 >> \001\033[0m\002")
        except (EOFError, KeyboardInterrupt):
            break
        if not query.strip():
            continue
        if query.strip().lower() in ("q", "exit"):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        # Print the model's final text response
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if getattr(block, "type", None) == "text":
                    print(block.text)
        print()
        print("======== the history ========")
        print(history)
        print("=============================")
