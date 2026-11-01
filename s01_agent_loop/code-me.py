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

# 尝试改善终端里的中文输入体验
try:
    # readline 用于增强终端中的交互输入，例如编辑输入内容、使用历史记录等。
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

# print(__file__) => F:\learn-claude-code\s01_agent_loop\code-me.py
# print(Path(__file__).resolve()) => F:\learn-claude-code\s01_agent_loop\code-me.py 
# print(Path(__file__).resolve().parents[0]) => F:\learn-claude-code\s01_agent_loop
# print(Path(__file__).resolve().parents[1]) => F:\learn-claude-code

# 找到项目根目录的 .env 并加载
# __file__ 表示当前这份 Python 文件的路径 Path(__file__) 把它转换成路径对象
# .resolve() 得到解析后的绝对路径
# .parents[0] 当前文件所在的目录 .parents[1] 当前文件所在目录的上一级目录
# / ".env" 在这个目录后面拼接 .env
# override=True 表示：如果当前程序已有同名环境变量，优先使用 .env 中的值覆盖它。
# Always use the project's .env, even when launched from another directory.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

# 如果只配置了密钥，结果就是 missing == ["MODEL_ID"]
# 如果只配置了模型，结果就是 missing == ["ANTHROPIC_API_KEY"]
missing = [name for name in ("ANTHROPIC_API_KEY", "MODEL_ID")
           if not os.getenv(name, "").strip()]
if missing:
    raise SystemExit(
        f"缺少配置：{', '.join(missing)}。请在项目根目录的 .env 中配置；"
        "百炼示例见 s01_agent_loop/bailian.env.example。"
    )

# 如果设置了自定义 API 地址，清除另一种认证变量
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

# 创建客户端，保存模型名称
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

# 根据操作系统，生成环境提示
# os.name 表示 Python 所处的操作系统类型
# Windows 的 os.name 是 nt，Linux 和 macOS 的 os.name 是 posix
# 告诉模型：
# Windows：这个工具执行的是 cmd.exe 命令，要使用 CMD 语法。
# Linux、macOS 等系统：使用系统 Shell 的语法。
ENVIRONMENT_PROMPT = (
    "Windows: the bash tool runs through cmd.exe; use cmd.exe syntax, not Unix "
    "Bash or PowerShell syntax"
    if os.name == "nt"
    else "Unix-like: the bash tool runs the system shell"
)

# 构建给模型的系统提示词
# os.getcwd() 获取的是当前 Python 进程的工作目录。
# print(os.getcwd()) => F:\learn-claude-code
SYSTEM = (
    f"You are a coding agent at {os.getcwd()}. Environment: {ENVIRONMENT_PROMPT}. "
    "Use bash to solve tasks. Act, don't explain."
)

# -- Tool definition: just bash --
# 向模型声明工具的名字和参数
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
    # 只要命令包含黑名单里的任意一段文本，就拒绝执行。
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        # 启动子进程，实际运行命令
        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
                           capture_output=True, text=True, errors="replace", timeout=120)
        # 整理输出，限制返回长度
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    # 如果启动进程等操作出现系统错误，就把异常内容转换成字符串返回。
    # 这么做的作用是：这些异常不会直接让整个 Agent 程序退出，模型还能收到错误信息，再决定下一步。
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"


# -- The core pattern: a while loop that calls tools until the model stops --
def agent_loop(messages: list):
    # messages 是一个列表，保存整个对话过程
    while True:
        # 把任务和历史发给模型
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
        # 遍历模型返回的内容块，只保留类型为 tool_use 的块，忽略普通文字等其他内容。
        tool_calls = [
            block for block in response.content if block.type == "tool_use"
        ]

        # 如果模型这次没有请求调用工具，就结束当前 Agent 循环。
        if not tool_calls:
            return

        # Execute each tool call, collect results
        # 逐个执行模型请求的命令
        results = []
        for block in tool_calls:
            print(f"\033[33m$ {block.input['command']}\033[0m")
            # 调用前面定义的函数，通过 subprocess.run() 运行命令，并取得输出字符串。
            output = run_bash(block.input["command"])
            print(output[:200])
            # 把输出包装成工具结果
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
            })

        # Feed tool results back, loop continues
        # 把结果加入历史，进入下一轮
        # 明明是程序执行的结果，为什么角色是 user
        # 因为 Anthropic 的这套消息协议规定：客户端工具的 tool_result 放在 user 消息中。
        # 这里的 user 表示客户端回传的消息，不代表真人又输入了一句话。
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
        # 跳过空输入
        if not query.strip():
            continue
        # 识别退出命令
        if query.strip().lower() in ("q", "exit"):
            break
        # 保存用户问题，启动 Agent
        history.append({"role": "user", "content": query})
        agent_loop(history)
        # Print the model's final text response
        # 取出最后一条消息，打印模型的文字回答
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                # 读取对象 block 的 type 属性；没有这个属性时，返回 None。
                if getattr(block, "type", None) == "text":
                    print(block.text)
        print()
        print("======== the history ========")
        print(history)
        print("=============================")
        