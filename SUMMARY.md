# learn-claude-code — Project Summary

*Summarized from `README.md` and `requirements.txt`*

## What It Is

**Learn Claude Code — Harness Engineering for Real Agents.** A 0-to-1 course teaching how to build agent *harnesses*: the operational environment (tools, knowledge, observation, action interfaces, permissions) around a pre-trained LLM.

Core thesis: **Agency comes from the model, not the harness.** "An Agent Product = Model + Harness." The model is the driver; the harness is the vehicle. Workflow builders, node graphs, and prompt-chain orchestration are explicitly rejected as "not agents" — they can't engineer agency into existence.

## Core Pattern

A single agent loop:

```
User -> messages[] -> LLM -> response
                        contains tool_use?
                          no  -> return text
                          yes -> execute tools, append results, loop
```

The model decides when to call tools and when to stop; the code just executes. Each lesson adds one harness mechanism around this untouched loop.

## Dependencies (requirements.txt)

| Package | Minimum Version | Purpose |
|---|---|---|
| `anthropic` | 0.25.0 | Claude API client (the model driver) |
| `python-dotenv` | 1.0.0 | Loads `ANTHROPIC_API_KEY` from `.env` |
| `pyyaml` | 6.0 | YAML parsing (config/skill files) |

## The 17 Lessons (current track, `s01`–`s17`)

| # | Topic | Motto / Key Idea |
|---|---|---|
| s01 | Agent Loop | "One loop + Bash is all you need" — `messages` / `while True` / `tool_use` |
| s02 | Tool Use | "Adding a tool means adding one handler" — `TOOL_HANDLERS` dispatch map, concurrency |
| s03 | Permission System | "Set boundaries first, then grant freedom" — `PermissionRule`, approval pipeline |
| s04 | Hook System | "Hook around the loop, never rewrite the loop" — `PreToolUse` / `PostToolUse` |
| s05 | TodoWrite | "An agent without a plan drifts" — plan-then-execute, completion rate doubles |
| s06 | Subagent | Fresh `messages[]` per subtask; final text returns as one tool result |
| s07 | Skill Loading | "Load knowledge on demand, not upfront" — `SkillLoader` catalog |
| s08 | Context Compact | "Context always fills up — have a way to make room" — budget, snip/micro compact, history summarization |
| s09 | Memory | "Remember what matters, forget what doesn't" — selection / extraction / consolidation |
| s10 | Task System | "Big goals break into small tasks" — file-backed task graph with `blockedBy` deps |
| s11 | Background Tasks | "Slow ops go background" — threaded execution, notification queue |
| s12 | Cron Scheduler | "Fire on schedule, no human kick needed" — time-based durable triggers |
| s13 | Agent Teams | "Let teammates divide the work" — persistent teammates, atomic task claims, task-bound worktrees |
| s14 | MCP Plugin | "Plug in more via MCP" — external tools into the same pool |
| s15 | Integrated Harness | "Many mechanisms, one loop" — reconnects the cumulative runtime |
| s16 | Workflow Runtime | "When the orchestration shape is fixed, put it in code" — saved workflows, resumable journals |
| s17 | Goal Loop | "A goal decides when the loop may stop" — independent evaluator gates stopping |

## Learning Path

1. **Act** (s01–s04): agent loop, tools, permissions, hooks
2. **Handle complex work** (s05, s06, s08): planning, subagents, compaction
3. **Remember across sessions** (s09): memory
4. **Run long tasks** (s10–s12): tasks, background, cron
5. **Collaborate** (s13): agent teams
6. **Extend and assemble** (s07, s14, s15): skills, MCP, integrated harness
7. **Orchestrate and close goals** (s16–s17): workflows, goal loop

## Structure & Usage

- Each chapter = a folder with `README.md` (English default, plus `.zh` / `.ja`), runnable `code.py`, and `images/` diagrams.
- Quick start: `pip install -r requirements.txt`, `cp .env.example .env` (set `ANTHROPIC_API_KEY`), then `python s01_agent_loop/code.py`.
- Legacy 12-lesson track kept in `agents/` and `docs/` during migration (don't mix chapter numbers across tracks).
- Optional web platform: `cd web && npm install && npm run dev` (http://localhost:3000).
- Sister repos: **Kode Agent CLI** (`@shareai-lab/kode`) and **kode-agent-sdk** for productionizing; **claw0** for always-on assistants (heartbeat + cron + IM + memory).

## License

MIT
