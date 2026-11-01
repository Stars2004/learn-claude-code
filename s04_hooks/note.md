# s04_hooks

假设你要求删除 `hello.py`，并且主程序按对应时机触发 Hook，那么流程就是：

```
你输入任务
    ↓
context_inject_hook：打印当前工作目录
    ↓
模型请求 bash("rm hello.py")
    ↓
permission_hook：询问是否允许
    ├─ 拒绝 → 返回拒绝原因，跳过后续 PreToolUse Hook
    └─ 允许
         ↓
       log_hook：打印工具调用日志
         ↓
       执行删除命令
         ↓
       large_output_hook：检查输出长度
    ↓
把工具结果交回模型
    ↓
模型给出最终回答、循环准备结束
    ↓
summary_hook：打印累计工具结果数量
```

```python
# s04 >> Read the file README.md
# 首先触发 UserPromptSubmit hook，执行 context_inject_hook 函数，在终端打印：
# [HOOK] UserPromptSubmit: working in /Users/jarvis/Code/PythonProjects/learn-claude-code

# messages
[{'role': 'user', 'content': 'Read the file README.md'}]

# response
Message(id='msg_5907faf4-f825-96e9-b920-656b29150645', container=None, content=[ThinkingBlock(signature='', thinking="First, let's load the README.md file.", type='thinking'), ToolUseBlock(id='toolu_462039363ac94d989b981e87', caller=None, input={'path': '/Users/jarvis/Code/PythonProjects/learn-claude-code/README.md'}, name='read_file', type='tool_use', toolset_name=None)], diagnostics=None, model='qwen3.8-27b', role='assistant', stop_details=None, stop_reason='tool_use', stop_sequence=None, type='message', usage=Usage(cache_creation=None, cache_creation_input_tokens=0, cache_read_input_tokens=0, inference_geo=None, input_tokens=634, output_tokens=55, output_tokens_details=None, server_tool_use=None, service_tier=None, speed=None, prompt_tokens_details={'cached_tokens': 0}))

# messages
[{'role': 'user', 'content': 'Read the file README.md'}, {'role': 'assistant', 'content': [ThinkingBlock(signature='', thinking="First, let's load the README.md file.", type='thinking'), ToolUseBlock(id='toolu_462039363ac94d989b981e87', caller=None, input={'path': '/Users/jarvis/Code/PythonProjects/learn-claude-code/README.md'}, name='read_file', type='tool_use', toolset_name=None)]}]

# 有 tooluse 触发 PreToolUse hook 分别执行 permission_hook 和 log_hook 函数
# 在 permission_hook 内，由于是 read_file 工具，执行路径安全检查，检查通过，返回 None
# 在 log_hook 内，终端打印工具调用参数的值：
# [HOOK] read_file(['/Users/jarvis/Code/PythonProjects/learn-claude-code/README)

# 真正执行工具调用

# 工具执行后，触发 PostToolUse hook 执行 large_output_hook 函数
# 工具执行后的 output 检查输出长度，超过 100,000 个字符，就打印提醒.

# 工具调用结果 results
[{'type': 'tool_result', 'tool_use_id': 'toolu_462039363ac94d989b981e87', 'content': '[English](./README.md) | [中文](./README-zh.md) | [日本語](./README-ja.md)\n\n<a href="https... the key designs and build it yourself."**'}]

# messages
[{'role': 'user', 'content': 'Read the file README.md'}, {'role': 'assistant', 'content': [...]}, {'role': 'user', 'content': [...]}]

# new response
Message(id='msg_bb7d0d2b-b9cf-9671-91d7-e80997ad926c', container=None, content=[ThinkingBlock(signature='', thinking="The user requested to read README.md. I've read it. Let me summarize the contents briefly.", type='thinking'), TextBlock(citations=None, text="I've read the README.md. Here's a summary:\n\n## Learn Claude Code — Harness Engineering for Real Agents\n\n**Core thesis:** Agency (perceive, reason, act) comes from the *model's training*, not external code. An agent product = **Model (driver) + Harness (vehicle)**. This repo teaches you to build the harness — tools, knowledge, observation/action interfaces, and permissions.\n\n**The core pattern** is a simple agent loop: call the LLM with `messages` + `tools`, append the response, and if it contains `tool_use` blocks, execute the tools, append `tool_result`s, and loop back — until the model stops calling tools.\n\n**17 progressive lessons** (root-level `s01`–`s17`), each isolating one harness mechanism:\n\n| # | Topic | # | Topic |\n|---|---|---|---|\n| s01 | Agent Loop | s10 | Task System |\n| s02 | Tool Use | s11 | Background Tasks |\n| s03 | Permission System | s12 | Cron Scheduler |\n| s04 | Hooks | s13 | Agent Teams |\n| s05 | TodoWrite | s14 | MCP Plugin |\n| s06 | Subagent | s15 | Integrated Harness |\n| s07 | Skill Loading | s16 | Workflow Runtime |\n| s08 | Context Compact | s17 | Goal Loop |\n| s09 | Memory | | |\n\n**Structure:** Each chapter is a folder with `README.md` (EN), `README.zh.md` / `README.ja.md` translations, a standalone `code.py`, and SVG diagrams. A legacy 12-lesson track lives in `docs/` and `agents/`.\n\n**Quick start:**\n```sh\npip install -r requirements.txt\ncp .env.example .env   # ANTHROPIC_API_KEY\npython s01_agent_loop/code.py\n```\n\n**Ecosystem:** Kode Agent CLI (`npm i -g @shareai-lab/kode`), Kode Agent SDK, and a sister repo **claw0** for always-on assistants (heartbeat + cron + IM channels). MIT licensed.\n\nWhat would you like to do next — e.g., run a lesson, explore a specific chapter, or set up the environment?", type='text')], diagnostics=None, model='qwen3.8-27b', role='assistant', stop_details=None, stop_reason='end_turn', stop_sequence=None, type='message', usage=Usage(cache_creation=None, cache_creation_input_tokens=0, cache_read_input_tokens=0, inference_geo=None, input_tokens=7218, output_tokens=530, output_tokens_details=None, server_tool_use=None, service_tier=None, speed=None, prompt_tokens_details={'cached_tokens': 0}))

# messages
[{'role': 'user', 'content': 'Read the file README.md'}, {'role': 'assistant', 'content': [...]}, {'role': 'user', 'content': [...]}, {'role': 'assistant', 'content': [...]}]

# 没有 tooluse 了，退出循环之前触发 Stop hook，执行 summary_hook 函数
# 统计 messages 中的工具调用数量，终端打印：
# [HOOK] Stop: session used 1 tool calls

# 退出 agentloop
```

