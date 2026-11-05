#!/usr/bin/env python3
"""
s07_skill_loading.py - Skill Loading

The system prompt contains a catalog of skill names and descriptions.
The model loads the full SKILL.md only when it calls load_skill.

    skills/                    Startup
    +------------------+       +------------------+
    | code-review/     | ----> | SkillLoader      |
    |   SKILL.md       |       | name + summary   |
    | pdf/             |       +--------+---------+
    |   SKILL.md       |                |
    +------------------+                v
                                 system prompt catalog

    LLM -- load_skill(name) --> full SKILL.md
     ^                              |
     +--------- tool_result --------+
"""

import os
import re
import subprocess
from pathlib import Path

import yaml

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

# 确定工作目录和技能目录
WORKDIR = Path.cwd()    # /Users/jarvis/Code/PythonProjects/learn-claude-code
SKILLS_DIR = WORKDIR / "skills"

client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

ENVIRONMENT_PROMPT = (
    "Windows: the bash tool runs through cmd.exe; use cmd.exe syntax, not Unix "
    "Bash or PowerShell syntax, and prefer dedicated file tools for file operations"
    if os.name == "nt"
    else "Unix-like: the bash tool runs the system shell"
)


# -- Skill catalog --
class SkillLoader:
    def __init__(self, skills_dir: Path):
        # 技能目录的位置
        self.skills_dir = skills_dir

        # 扫描得到的技能数据
        self.skills: dict[str, dict[str, str]] = {}

        # 创建 SkillLoader 时，立即扫描技能目录
        self.scan()

    @staticmethod
    # 静态方法，不需要接收 self。因为它只处理传入的文字，不依赖当前对象的技能目录或已保存的数据。
    def parse_frontmatter(text: str) -> tuple[dict, str]:
        """把元数据与正文分开"""
        # 拆分文本 保留每行末尾的换行符
        lines = text.splitlines(keepends=True)
        # 检查第一行是否是 "---"，如果不是，说明没有 frontmatter，直接返回空字典和原始文本
        # .rstrip("\r\n") 去掉行末的回车、换行字符。因此第一行必须严格是 ---；如果前面有空行或两边有空格，就不会通过这项检查。
        if not lines or lines[0].rstrip("\r\n") != "---":
            return {}, text

        # 找到第二条 --- 的索引，作为 frontmatter 的结束位置
        # next(生成器, None) 获取生成器产生的第一个结果；没有结果时返回 None。
        # enumerate(..., start=1) 让索引与原始 lines 的位置保持一致。
        closing_index = next(
            (index for index, line in enumerate(lines[1:], start=1)
             if line.rstrip("\r\n") == "---"),
            None,
        )

        # 如果找不到结束分隔线
        # 同样退回到 没有元数据，全文作为正文。
        if closing_index is None:
            return {}, text

        # 找到后，拆出两部分
        # frontmatter 是从第二行到 closing_index 的所有行，拼接成一个字符串
        frontmatter = "".join(lines[1:closing_index])
        # body 是从 closing_index + 1 到最后的所有行，拼接成一个字符串，并去掉首尾空白
        body = "".join(lines[closing_index + 1:]).strip()

        # 用 YAML 解析元数据
        try:
            # safe_load() 使用受限制的 YAML 加载方式，适合解析这样的配置数据。
            # or {} 表示解析结果是假值时，用空字典兜底。比如空元数据可能解析为 None。
            metadata = yaml.safe_load(frontmatter) or {}
        except yaml.YAMLError:
            # 如果 YAML 格式错误，也改用空字典
            metadata = {}
        if not isinstance(metadata, dict):
            # 检查类型，如果解析结果不是字典，也改用空字典
            metadata = {}

        # 返回一个包含 字典 和 字符串 的元组
        return metadata, body

    def scan(self):
        """查找并读取所有技能文件"""
        # 先清空旧目录，再重新构建。这意味着扫描是 重建快照，不是在旧数据后面不断追加。
        self.skills.clear()

        # 技能目录不存在就结束，此时技能列表为空。
        if not self.skills_dir.exists():
            return

        # 得到解析后的技能根路径，供后面检查文件位置。
        skills_root = self.skills_dir.resolve()

        # 查找技能文件 匹配的是：skills/一级子目录/SKILL.md
        # sorted() 则让扫描顺序按路径排序。
        for manifest in sorted(self.skills_dir.glob("*/SKILL.md")):
            # 检查文件是否存在，且是否在技能根目录下。防止技能目录被符号链接到外部路径。
            if (not manifest.is_file()
                    or not manifest.resolve().is_relative_to(skills_root)):
                continue

            # 通过后读取全文，并解析
            content = manifest.read_text(encoding="utf-8")
            metadata, body = self.parse_frontmatter(content)

            # 为技能确定名称
            raw_name = metadata.get("name")
            # strip() 去掉首尾空白字符，确保名称是干净的字符串；如果不是字符串，就用空字符串。
            name = raw_name.strip() if isinstance(raw_name, str) else ""
            # name 为空时，使用技能目录名作为默认名称。manifest.parent.name 是 SKILL.md 的父目录名。
            name = name or manifest.parent.name

            # 为技能确定描述
            raw_description = metadata.get("description")
            # strip() 去掉首尾空白字符，确保描述是干净的字符串；如果不是字符串，就用空字符串。
            description = (raw_description.strip()
                           if isinstance(raw_description, str) else "")
            # description 为空时，使用正文的第一行作为默认描述。body.split("\n", 1)[0] 拆出正文的第一行。
            description = description or body.split("\n", 1)[0]
            # 去掉开头连续的 # 和空格。
            # 按空白拆分文本。
            # 用单个空格重新连接。
            description = " ".join(str(description).lstrip("# ").split())

            # 保存技能数据到字典中，键是技能名称，值是一个包含 name、description、content 的字典。
            self.skills[name] = {
                "name": name,
                "description": description,
                "content": content,
            }

    def catalog(self) -> str:
        """生成给模型看的技能目录"""
        # 没有技能时返回提示
        if not self.skills:
            return "(no skills found)"
        
        # 返回一个字符串，每行是一个技能的名称和描述，前面加上 - 作为列表标记。
        # 例如：
        # - code-review: Review code for issues and improvements.
        # - pdf: Extract text from PDF files.
        # - ... (more skills)
        return "\n".join(
            f"- {skill['name']}: {skill['description']}"
            for skill in self.skills.values()
        )

    def load(self, name: str) -> str:
        """按名称取出完整技能"""
        # 从技能字典中获取指定名称的技能数据
        skill = self.skills.get(name)

        # 如果找到了技能，就返回它的完整内容（SKILL.md 的全文）。
        if skill:
            return skill["content"]

        # 如果没有找到技能，就返回一个错误提示，并列出所有可用的技能名称。
        # ", ".join(self.skills) 默认使用的是字典的键，也就是技能名称。
        available = ", ".join(self.skills) or "none"

        # 例如：
        # Error: Unknown skill 'nonexistent'. Available: code-review, pdf
        return f"Error: Unknown skill '{name}'. Available: {available}"


# 创建加载器，自动扫描技能目录，读取所有 SKILL.md 文件并生成技能列表，保存在 SKILL_LOADER.skills 中。
# SKILLS_DIR: /Users/jarvis/Code/PythonProjects/learn-claude-code/skills
SKILL_LOADER = SkillLoader(SKILLS_DIR)


def build_system_prompt() -> str:
    return (
        f"You are a coding agent at {WORKDIR}. Environment: {ENVIRONMENT_PROMPT}. "
        "Use tools to solve tasks. "
        "Act, don't explain.\n\n"
        # 列出所有可用技能的名称和描述，供模型参考。
        f"Skills available:\n{SKILL_LOADER.catalog()}\n\n"
        # 当某个技能适用时，使用 load_skill 读取完整说明。
        "Use load_skill to read the full instructions when a skill applies."
    )


# 生成系统提示，包含工作目录、环境信息、可用技能列表等，供模型在对话中参考。
SYSTEM = build_system_prompt()


# -- Tools --

def run_bash(command: str) -> str:
    try:
        result = subprocess.run(
            command, shell=True, cwd=WORKDIR,
            capture_output=True, text=True, errors="replace", timeout=120,
        )
        output = (result.stdout + result.stderr).strip()
        return output[:50000] if output else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


def run_read(path: str, limit: int | None = None) -> str:
    try:
        lines = (WORKDIR / path).resolve().read_text(encoding="utf-8").splitlines()
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
    import glob
    try:
        matches = sorted({
            match for match in glob.glob(
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
    {"name": "load_skill", "description": "Load the full SKILL.md content by skill name.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
]

TOOL_HANDLERS = {
    "bash": run_bash,
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
    "glob": run_glob,
    # load_skill 直接调用 SKILL_LOADER.load 方法，传入技能名称，返回完整的技能内容。
    "load_skill": SKILL_LOADER.load,
}


# -- Hooks --

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
    """PreToolUse: block denied operations and ask about risky ones."""
    if block.name == "bash":
        command = block.input.get("command", "")
        for pattern in DENY_LIST:
            if pattern in command:
                print(f"\n\033[31m[blocked] '{pattern}'\033[0m")
                return "Permission denied by deny list"
            
        if contains_destructive_command(command) or any(
            keyword in command for keyword in DESTRUCTIVE
        ):
            print("\n\033[33m[permission] Potentially destructive command\033[0m")
            print(f"   Tool: {block.name}({block.input})")
            choice = input("   Allow? [y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                return "Permission denied by user"

    if block.name in ("read_file", "write_file", "edit_file"):
        path = block.input.get("path", "")
        if not (WORKDIR / path).resolve().is_relative_to(WORKDIR):
            print("\n\033[33m[permission] Access outside workspace\033[0m")
            print(f"   Tool: {block.name}({block.input})")
            choice = input("   Allow? [y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                return "Permission denied by user"
            
    return None


def log_hook(block):
    """PreToolUse: log every tool call."""
    args_preview = str(list(block.input.values())[:2])[:60]
    print(f"\033[90m[HOOK] {block.name}({args_preview})\033[0m")
    return None


def large_output_hook(block, output):
    """PostToolUse: warn on large output."""
    if len(str(output)) > 100000:
        print(f"\033[33m[HOOK] Large output from {block.name}: {len(str(output))} chars\033[0m")
    return None


def context_inject_hook(query: str):
    """UserPromptSubmit: log the working directory."""
    print(f"\033[90m[HOOK] UserPromptSubmit: working in {WORKDIR}\033[0m")
    return None


def summary_hook(messages: list):
    """Stop: print the number of tool results in this message list."""
    tool_count = sum(
        1
        for message in messages
        for block in (
            message.get("content")
            if isinstance(message.get("content"), list)
            else []
        )
        if isinstance(block, dict) and block.get("type") == "tool_result"
    )
    print(f"\033[90m[HOOK] Stop: session used {tool_count} tool calls\033[0m")
    return None


register_hook("UserPromptSubmit", context_inject_hook)
register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook)
register_hook("PostToolUse", large_output_hook)
register_hook("Stop", summary_hook)


def execute_tool(block) -> str:
    """执行工具调用，返回结果字符串"""
    blocked = trigger_hooks("PreToolUse", block)
    if blocked:
        return str(blocked)

    handler = TOOL_HANDLERS.get(block.name)
    try:
        output = handler(**block.input) if handler else f"Unknown: {block.name}"
    except Exception as e:
        output = f"Error: {e}"

    trigger_hooks("PostToolUse", block, output)
    return str(output)


def agent_loop(messages: list):

    while True:
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000,
        )

        messages.append({"role": "assistant", "content": response.content})

        tool_calls = [
            block for block in response.content if block.type == "tool_use"
        ]

        if not tool_calls:
            force = trigger_hooks("Stop", messages)
            if force:
                messages.append({"role": "user", "content": force})
                continue
            return

        results = []
        for block in tool_calls:
            output = execute_tool(block)
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
            })

        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    print("s07: Skill Loading - catalog first, full content on demand")
    print("Enter a question, press Enter to send. Type q to quit.\n")

    history = []
    while True:
        try:
            # \001/\002 tell Readline the ANSI escapes have zero display width.
            query = input("\001\033[36m\002s07 >> \001\033[0m\002")
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
