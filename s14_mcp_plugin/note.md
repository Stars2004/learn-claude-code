# s14 MCP Tools 学习笔记

**在 s14 里，可以把接入 MCP 理解成给 Agent 的工具箱加上一批服务提供的工具。** MCP（Model Context Protocol）提供统一的发现和调用方式，具体的搜索、查版本等功能由服务实现。

例如，Agent 一开始有 `read_file` 和 `bash`。连接 `docs` 后，模型下一轮还可以选择 `mcp__docs__search` 和 `mcp__docs__get_version`。Python 负责把工具交给模型、检查调用权限，再把执行结果送回模型。课程源码见 [code.py](code.py)。

## 复习导航

- [MCP 有什么用](#1-mcp-有什么用)
- [从六个工具变成八个](#2-从六个工具变成八个)
- [模型调用以后参数去了哪里](#3-模型调用以后参数去了哪里)
- [命名冲突与权限由谁处理](#4-命名冲突与权限由谁处理)
- [Skill 和 MCP 的区别](#5-skill-和-mcp-的区别)
- [源码速查和复习问答](#6-源码速查和复习问答)

## 1. MCP 有什么用

假设你问 Agent「这个 PR 为什么测试失败了？帮我查日志，告诉我具体原因。」如果接入的服务提供查询 PR 检查和读取日志的工具，Agent 就可以先查失败的检查，再读那次的日志，最后根据报错解释失败原因。接入文档库时，流程也相似，服务会提供文档搜索等工具。

对写 Agent 的人来说，每接入一个系统都可以复用**发现工具 → 把工具提供给模型 → 调用工具 → 接收结果**的流程。各个服务提供的能力和参数可以不同。

在本课中，`docs` 和 `deploy` 都是当前 Python 进程里的模拟服务。`MOCK_SERVERS` 保存这两个名字对应的工厂函数。连接 `docs` 时调用本地工厂，搜索时执行本地函数。课程用 `register()` 接收工具定义和处理函数来演示工具发现，用 `MCPClient.call_tool()` 演示按名字和参数调用。真实 MCP 服务的通信过程由这两处本地操作模拟。对应源码见 [MCPClient](code.py#L170) 和 [connect_mcp](code.py#L289)。

## 2. 从六个工具变成八个

沿着一个实际可以对照课程输出的请求往下看。

> 连接 `docs`，搜索 `agent hooks`，并告诉我文档 API 的版本。

### 第一轮只有基础工具和连接工具

程序启动时，`mcp_clients = {}`。模型第一次调用收到五个基础工具和一个 `connect_mcp`。

```text
bash、read_file、write_file、edit_file、glob、connect_mcp
```

此时模型可以请求连接 `docs`。

```json
{
  "name": "connect_mcp",
  "input": {"name": "docs"}
}
```

Python 在 `MOCK_SERVERS` 里找到 `_mock_server_docs()`，创建一个 `MCPClient`，登记 `search` 和 `get_version` 的工具定义及对应函数，再把对象放到 `mcp_clients["docs"]`。连接本身也有一条 `tool_result`，随后被追加进 `messages`。

```text
Connected to MCP server 'docs'. Discovered 2 tools: search, get_version
```

### 下一轮重新组装工具池

每次请求模型前，Agent Loop 都会执行 `tools, handlers = assemble_tool_pool()`。第二次执行时，`mcp_clients` 里已经有 `docs`，工具列表于是变为八个。

```text
原来的六个工具
+ mcp__docs__search
+ mcp__docs__get_version
```

连接结果告诉模型刚才发生了什么，下一次请求的 `tools` 字段才提供新工具的名称和参数定义。因为一轮开始时就构建好了执行映射，新连接的工具要等下一轮重新组装后可用。

| 信息 | 谁使用 | 搜索例子里的内容 |
| --- | --- | --- |
| `tools` | 模型 | `mcp__docs__search`，需要字符串参数 `query` |
| `handlers` | Python 工具执行器 | 把 `mcp__docs__search` 转到 `docs` 的原始 `search` |
| `mcp_tool_policies` | 权限 Hook | `mcp__docs__search` 的策略为 `allow` |
| `messages` | 后续的模型调用 | 用户请求、连接结果和之后的搜索结果 |

组装时，服务工具定义中的 `inputSchema` 会被放到模型工具定义的 `input_schema` 字段中。系统提示也会加入已连接的服务名称。重复连接同名服务会返回 `already connected`。退出程序后，内存中的连接登记随进程结束，下一次启动会重新发现工具。对应源码见 [assemble_tool_pool](code.py#L323)、[assemble_system_prompt](code.py#L369) 和 [agent_loop](code.py#L486)。

## 3. 模型调用以后参数去了哪里

模型拿到更新后的工具列表，发出一次搜索请求。

```json
{
  "name": "mcp__docs__search",
  "input": {"query": "agent hooks"}
}
```

处理过程可以简化成下面三行。每一层接到同一个查询词，使用的工具名则随所在位置改变。

```python
# execute_tool 通过模型看到的工具名找到执行函数
handlers["mcp__docs__search"](query="agent hooks")

# 执行函数转给对应的 MCPClient，使用服务的原始工具名
docs_client.call_tool("search", {"query": "agent hooks"})

# MCPClient 从自己的处理函数字典中取得函数，再按参数执行
search(query="agent hooks")
```

搜索和版本工具在这节代码里的实际模拟输出如下。

```text
mcp__docs__search(query="agent hooks") → [docs] Found 3 results for 'agent hooks'
mcp__docs__get_version()               → [docs] API v2.1.0
```

如果模型在同一轮请求这两个工具，Python 会将各自的结果用 `tool_use_id` 与原调用配对，一起放进下一条消息。模型下一轮读取结果后再答复用户。这里模拟搜索的返回值是一句结果数量说明，能供模型阅读的内容到这句话为止。

### 为什么循环里的 lambda 要保存默认参数

```python
lambda *, client=server, tool=raw_name, **kwargs: (
    client.call_tool(tool, kwargs)
)
```

循环轮到 `search` 时，默认参数保存当时的服务对象和原始名字 `search`。轮到 `get_version` 时，另一个 lambda 保存自己的值。如果只让函数体引用循环里的 `server` 和 `raw_name`，以后实际执行时可能读到循环结束时的值，导致搜索请求被发给最后一个工具处理。对应源码见 [工具绑定](code.py#L357) 和 [execute_tool](code.py#L469)。

### 漏传 query 时发生什么

如果一次搜索请求漏了 `query`，而这个请求实际到达 Python 函数，`handler(**args)` 会抛出 `TypeError`。`MCPClient.call_tool()` 捕获异常，返回类似下面的文字。

```text
MCP error: TypeError: ... missing 1 required positional argument: 'query'
```

这段文字作为普通工具结果回到模型。模型可以读到错误、补上 `query`，在下一轮重试。对应源码见 [MCPClient.call_tool](code.py#L190)。

## 4. 命名冲突与权限由谁处理

### 两个服务都有 search，怎样区分

模型侧使用 `mcp__{server}__{tool}` 作为工具名，因此 `docs` 的 `search` 会显示为 `mcp__docs__search`。组装时会把不在允许字符集合内的字符换成下划线，并检查完整名称是否超过 64 字符。

替换字符可能让不同的名字变成同一个。例如：

```text
服务 docs.one，工具 get.version  → mcp__docs_one__get_version
服务 docs_one，工具 get_version → mcp__docs_one__get_version
```

组装时检测到重复就会报错，避免后加入的执行函数覆盖前一个。此时模型请求还没发出，Agent Loop 会记录错误并结束当前回合。原始服务名和工具名仍然用于程序调用和查找宿主策略。对应源码见 [normalize_mcp_name](code.py#L213) 和 [名称冲突检查](code.py#L334)。

### 为什么查部署状态可以直接执行，触发部署需要确认

假设模型已连接 `deploy`，下一轮会看到下列两个工具。

| 工具请求 | 宿主配置 | 处理结果 |
| --- | --- | --- |
| `mcp__deploy__status(service="web")` | `allow` | 直接调用，模拟返回 `[deploy] web: running (v1.4.2)` |
| `mcp__deploy__trigger(service="web")` | `confirm` | 先在终端询问 `Allow? [y/N]`，输入 `y` 或 `yes` 后才调用 |

对触发部署的请求输入 `n` 或直接回车，会返回 `Permission denied by user`，处理函数不会运行。本课的部署处理函数返回演示文字。工具是否可见由连接和发现决定，当前调用是否放行由 `PreToolUse` 中的权限 Hook 决定。

`readOnlyHint` 等标记来自服务。权限 Hook 根据宿主侧的 `MCP_HOST_POLICY` 判定，未配置的 MCP 工具默认走确认流程。对应源码见 [MCP_HOST_POLICY](code.py#L205) 和 [permission_hook](code.py#L401)。

## 5. Skill 和 MCP 的区别

**用 Skill 配合现有工具，也能完成很多相同的任务。** 比如排查 PR 测试失败，Skill 可以教 Agent 用 `bash` 调用 `gh`，先找失败的检查，再读日志。只要环境里有 `gh`，已经登录并具备读取权限，这套流程就能工作。Skill 还可以附带脚本，把常用操作封装起来。

区别在于两者提供的东西。Skill 提供可复用的工作流程，MCP 让程序通过统一接口发现和调用服务提供的工具。用一个更小的例子看清楚。

> 退款期限是几天？先告诉我答案，再给出处。

假设政策规定「购买后 7 天内可以申请退款」。下面的退款示例用于对照两种数据流。

### 用 Skill 读取本地政策

在 s07 的模式下，`load_skill("answer-refund-question")` 会把完整 `SKILL.md` 作为 `tool_result` 加进 `messages`。假设它写着以下步骤。

```text
1. 用 read_file 读取 docs/refund.md。
2. 找到“退款期限”一节。
3. 用一句话回答，再附上文件路径。
```

模型拿到说明后，再使用已经有的 `read_file("docs/refund.md")`，从文件正文找到「7 天」。加载这份 Skill 的直接变化是**模型的 `messages` 多了一份操作说明**。对应源码见 [s07 的 SkillLoader](../s07_skill_loading/code.py#L59)。

### 用 MCP 查询公司知识库

假设同一条政策保存在公司知识库里，连接对应的 MCP 服务后，模型的 `tools` 多了 `mcp__docs__search`，可以传入 `{"query": "退款期限"}`。一次查询可能返回如下数据。

```text
标题：退款政策
片段：购买后 7 天内可以申请退款。
来源：知识库 / 退款政策
```

模型可以用返回的片段和来源回答用户。这是用来说明真实查询工具可以提供什么的示例，课程内置的模拟搜索只返回查询词和结果数量。

| 刚完成的操作 | 模型现在拿到了什么 |
| --- | --- |
| `load_skill(...)` | 一份工作说明，告诉模型读哪里、看哪一节、按什么格式回复 |
| `connect_mcp(...)` 后进入下一轮 | 新的可调用工具及参数定义，调用后才得到服务返回的数据 |

两者也可以组合。如果公司把政策从本地文件迁到知识库，可以把 Skill 的第一步改成「调用 `mcp__docs__search` 搜索退款期限」，后面的答复格式继续沿用。已有 `gh`、本地文件或脚本能满足需求时，Skill 可以直接复用它们。需要把同一套查询能力提供给多个支持 MCP 的 Agent 时，MCP 提供统一的调用方式。

## 6. 源码速查和复习问答

| 想弄懂什么 | 看哪里 |
| --- | --- |
| 连接 `docs` 时保留了什么对象？ | [connect_mcp](code.py#L289) 和 `mcp_clients` |
| 服务提供的工具定义怎样进入模型请求？ | [assemble_tool_pool](code.py#L323) 中给 `tools` 加定义的部分 |
| 模型给出的前缀名称怎样找到原始函数？ | [工具绑定](code.py#L357) 和 [MCPClient.call_tool](code.py#L190) |
| 谁决定部署操作需要确认？ | [宿主策略](code.py#L205) 和 [permission_hook](code.py#L401) |
| 为什么连接成功后，下一轮才能调用搜索？ | [agent_loop](code.py#L486) 每轮调用模型前重建工具池 |

**1. MCP 可以理解成给 Agent 增加了一些工具吗？** 可以。更准确地说，工具由服务提供，MCP 约定怎样发现和调用这些工具。

**2. `connect_mcp` 返回“找到两个工具”以后，什么真正让模型可以选择它们？** 下一轮重新组装工具池，再通过模型请求的 `tools` 字段传进去。

**3. `tools` 和 `handlers` 分别给谁用？** `tools` 给模型看，描述可选工具和参数。`handlers` 给 Python 用，决定调用到哪个实际函数。

**4. 服务标注工具为只读，宿主就会直接执行吗？** 看宿主策略。课程中获得 `allow` 才会直接执行，其他 MCP 工具需要确认。

**5. Skill 和 MCP 都能用于查 PR 失败原因，主要差别在哪？** Skill 可以提供排查步骤并使用已有命令，MCP 可以提供查检查状态和读日志的工具入口。组合后，Skill 指导怎样查，MCP 提供查询能力。

**6. 课程里的 `docs` 搜索返回了 3 篇真实文档吗？** 模拟函数返回一句「找到 3 条」的文字，模型只收到这段文字。真实知识库可以通过同样的调用位置返回实际数据。

此前讲解用模拟模型回复验证了工具列表从 6 个变为 8 个的过程。仓库中的工具发现、宿主权限和名称冲突三项相关测试均已通过。
