# s10 Task System 学习笔记：用任务账本记录进度和依赖

这份笔记配合 [code.py](code.py) 阅读。先看具体例子里“任务记录怎么变”，再回到源码理解函数实现。

每个场景都围绕三个问题：

1. 操作之前，任务记录是什么样？
2. 程序检查什么、修改什么？
3. 操作之后，哪些任务可以继续，磁盘上保存了什么？

> s10 给 Agent 做了一本保存在磁盘上的“任务账本”：记录要做什么、做到哪里、谁在做，以及必须先完成什么。

下文用函数调用的形式表示模型发出的工具请求。实际工具通过 `run_...` 包装函数返回文字；底层部分函数返回的是 `Task` 对象，阅读源码时需要区分。

示例 ID 固定用于讲解。实际运行时，必须使用 `create_task` 返回的真实 ID，不能提前猜测。

## 复习导航

- [先理解任务卡片](#1-先理解为什么需要任务系统)。
- [创建任务和添加依赖](#4-情况一先创建所有任务)。
- [认领任务与阻塞检查](#7-情况三前置任务没完成强行认领会怎样)。
- [完成任务与解锁](#9-情况五完成-a后续任务会自动开始吗)。
- [多个依赖和错误关系](#11-情况七一个任务要同时等两件事)。
- [退出后的恢复](#14-情况十退出程序以后怎样恢复进度)。
- [工具速查](#19-工具函数和状态速查)。
- [复习问答](#21-复习问答)。

## 1. 先理解：为什么需要任务系统

假设用户提出：

> “帮我实现用户注册功能，补上测试，并写一份数据结构说明。”

最简单的做法是写一张待办清单：

```text
[ ] 建立用户表
[ ] 实现注册 API
[ ] 编写并运行注册测试
[ ] 编写数据结构说明
```

这份清单能提醒模型还有什么没做，但还没有完整表达这些问题：

- 用户表没建立，注册 API 现在能开始吗？
- 测试没做，是没人开始，还是因为 API 没完成？
- 某个任务已经有人接手，其他执行者还能认领吗？
- 程序退出以后，下次还能知道做到哪里了吗？

s10 给每一项工作增加了独立编号、描述、状态、负责人和前置关系，并保存到磁盘。

可以把它理解成一张张“任务卡片”：

```text
一张卡片：
  任务编号是什么？
  要做什么？
  具体要求是什么？
  还没开始、正在做，还是已经完成？
  谁负责？
  必须先等哪些任务完成？
```

和 s05 的待办清单相比，s10 更强调可持久保存的独立任务，以及任务之间的关系。

## 2. 贯穿全篇的例子：用户注册功能

把用户需求拆成四个任务：

| 简称 | 任务 | 具体要求 |
| --- | --- | --- |
| A | 建立用户表 | 创建 `users` 表，定义字段和约束 |
| B | 实现注册 API | 接收注册信息，把用户写入 `users` 表 |
| C | 编写并运行注册测试 | 验证正常注册、重复用户名、空密码等情况 |
| D | 编写数据结构说明 | 说明用户表的字段和约束 |

在这个教学例子里，我们约定：

```text
B 要等 A：用户表完成后再实现 API。
C 要等 B：API 完成后再编写并运行注册测试。
D 要等 A：用户表确定后再写数据结构说明。
```

画出来是：

```text
A 建立用户表
    ├──→ B 实现注册 API ──→ C 编写并运行注册测试
    │
    └──→ D 编写数据结构说明
```

箭头表示：**左边完成以后，右边才具备开始条件。**

这是为本次示例选择的工作顺序。现实中也可以先设计测试，任务系统只是执行我们明确建立的依赖关系，不会替我们决定所有开发方法。

## 3. 一张任务卡片具体长什么样

假设创建了 A，保存后的内容大致是：

```json
{
  "id": "task_a1b2c3d4",
  "subject": "建立用户表",
  "description": "创建 users 表，包含 id、username 和 password_hash；完成后检查表结构。",
  "status": "pending",
  "owner": null,
  "blockedBy": []
}
```

字段解释：

| 字段 | 通俗理解 | 这个例子里的意思 |
| --- | --- | --- |
| `id` | 任务编号 | 后面认领、查看、完成任务时使用 |
| `subject` | 简短标题 | 建立用户表 |
| `description` | 详细要求 | 创建哪些字段，完成后检查什么 |
| `status` | 做到哪一步 | `pending` 表示还没开始 |
| `owner` | 当前负责人 | `null` 表示还没人负责 |
| `blockedBy` | 必须先完成的任务 ID | 空列表表示没有前置任务 |

对应的 Python 数据结构：

```python
@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str
    owner: str | None
    blockedBy: list[str]
```

`@dataclass` 在这里主要让一张任务卡片能方便地表示为 Python 对象。`asdict(task)` 可以把对象转换成字典，再写成 JSON 文件。

```text
Task 对象
    ↓ asdict
字典
    ↓ JSON 序列化
磁盘上的任务文件
```

文件位置：

```text
.tasks/task_a1b2c3d4.json
```

下文为方便阅读，把 JSON 中的中文直接显示出来。当前源码默认的 JSON 序列化也可能把中文写成 `\u...` 形式；解析后表达的内容相同。

### 3.1 三个状态、两个主要动作

```text
pending：还没开始。

in_progress：已经认领，正在处理。

completed：已标记完成。
```

正常生命周期：

```text
pending
    ↓ claim_task：认领
in_progress
    ↓ complete_task：完成
completed
```

### 3.2 没有单独的 blocked 状态

当前状态只有上面三个。

一个等待前置任务的任务，通常仍是 `pending`。“现在能不能开始”根据依赖另外计算。

```text
A：pending，没有前置任务，可以认领。

B：pending，但前置的 A 没完成，不能认领。
```

因此，**状态相同，不代表当前可执行性相同。**

## 4. 情况一：先创建所有任务

### 4.1 处理前：还没有任务记录

假设项目里没有 `.tasks/`，调用 `list_tasks` 工具时会看到类似提示：

```text
No tasks. Use create_task to add some.
```

仅仅创建 `TaskStore` 对象并不会立即写入所有任务；真正创建任务时才会按需建立目录和文件。

### 4.2 创建 A

模型发出的工具请求可以读成：

```python
create_task(
    subject="建立用户表",
    description="创建 users 表，包含 id、username 和 password_hash；完成后检查表结构。"
)
```

工具结果例如：

```text
Created task_a1b2c3d4: 建立用户表
```

这里的含义是：任务记录已建立，并分配了编号。

**创建任务卡片，不会因此自动创建数据库表。** 真正建立表的工作要由后续代码修改、数据库操作等工具完成。

### 4.3 再创建 B、C、D

```python
create_task(
    subject="实现注册 API",
    description="增加注册接口，将用户写入 users 表。"
)

create_task(
    subject="编写并运行注册测试",
    description="覆盖正常注册、用户名重复和空密码。"
)

create_task(
    subject="编写数据结构说明",
    description="说明 users 表的字段及约束。"
)
```

假设工具返回这些 ID：

| 简称 | 实际 ID | 标题 |
| --- | --- | --- |
| A | `task_a1b2c3d4` | 建立用户表 |
| B | `task_e5f6a7b8` | 实现注册 API |
| C | `task_11223344` | 编写并运行注册测试 |
| D | `task_55667788` | 编写数据结构说明 |

### 4.4 处理后：磁盘出现四个文件

```text
.tasks/
  task_a1b2c3d4.json
  task_e5f6a7b8.json
  task_11223344.json
  task_55667788.json
```

刚创建的任务统一是：

```text
status：pending
owner：null
blockedBy：[]
```

此时还没有建立依赖。

即使标题或描述里写了“等用户表完成后再做”，程序也不会自动把这句话解析成依赖边。需要下一步明确设置 `blockedBy`。

### 4.5 ID 从哪里来

代码使用：

```python
id = f"task_{secrets.token_hex(4)}"
```

生成 `task_` 加8位十六进制字符，例如 `task_a1b2c3d4`。

创建文件用 `open("x")`，表示同名文件已存在就失败。发生碰撞时会重新生成 ID，最多尝试100次，避免直接覆盖已有任务。

所以示例里的编号只是为了讲解固定下来；实际模型要等工具执行后，才能知道分配到了哪个编号。

## 5. 情况二：给任务添加前置关系

### 5.1 先看 B 操作之前的样子

```text
B：实现注册 API
  status：pending
  owner：null
  blockedBy：[]
```

我们希望 B 等 A，因此调用：

```python
update_task(
    task_id="task_e5f6a7b8",
    addBlockedBy=["task_a1b2c3d4"]
)
```

### 5.2 程序检查什么

添加前，会检查目标任务和依赖是否有效，包括：

- B 是否存在。
- B 是否仍为 `pending`，并且没有负责人。
- A 是否存在。
- 是否让任务依赖自己。
- 是否形成依赖循环。

通过后才保存新的关系。

### 5.3 处理后 B 变成什么

```text
B：实现注册 API
  status：pending
  owner：null
  blockedBy：[A 的真实 ID]
```

具体字段是：

```json
{
  "blockedBy": ["task_a1b2c3d4"]
}
```

可以读成：

> “我还是没开始，但开始之前必须等 A 完成。”

### 5.4 给 C 和 D 添加依赖

```python
update_task(
    task_id="task_11223344",
    addBlockedBy=["task_e5f6a7b8"]
)

update_task(
    task_id="task_55667788",
    addBlockedBy=["task_a1b2c3d4"]
)
```

最后可以简写为：

```text
A.blockedBy = []
B.blockedBy = [A]
C.blockedBy = [B]
D.blockedBy = [A]
```

这里的 A、B 是阅读简称；JSON 文件里保存的仍然是实际任务 ID。

### 5.5 特别注意依赖方向

```text
B.blockedBy = [A]
```

意思是：

```text
B 等 A。

A 完成以后，B 才可能开始。
```

**列表里写的是“我在等谁”，不是“谁在等我”。**

## 6. 为什么要先创建任务，再添加依赖

这是本节一个重要的工具交互设计。

模型的一次回复可以同时提出多个工具调用：

```text
调用1：创建“建立用户表”。
调用2：创建“实现注册 API”。
```

这两条调用在模型输出时，参数都已经确定。

但此时创建 A 的工具还没有执行，模型还不知道 A 的运行时 ID，所以无法可靠地提前填写：

```text
注册 API 依赖 task_????????。
```

当前代码把过程拆成两阶段：

```text
第一轮模型输出：
  创建 A、B、C、D。

程序执行工具：
  返回四个真实 ID。

下一轮模型输出：
  使用这些真实 ID，调用 update_task 添加依赖。
```

系统提示中的这段话就是要求这个顺序：

```text
Create all task nodes first.
After create_task returns runtime-generated IDs,
use update_task with those exact IDs to add dependencies.
```

可以读成：

> 先建卡片，拿到编号，再按编号连接关系。

底层 Python 如果自己顺序调用，可以先拿到 `a.id`，再用它操作其他任务；模型同一批工具调用则不能依赖尚未返回的工具结果。阅读示例时要区分这两种场景。

## 7. 情况三：前置任务没完成，强行认领会怎样

### 7.1 操作前

四个任务都是 `pending`：

```text
A：pending，无依赖。
B：pending，等 A。
C：pending，等 B。
D：pending，等 A。
```

### 7.2 模型直接认领 C

```python
claim_task("task_11223344")
```

程序先读取 C，再读取它的前置任务 B：

```text
C 是否 pending？
  是。

C 的所有前置任务都 completed 了吗？
  没有，B 还是 pending。

结果：拒绝认领。
```

返回：

```text
Blocked by: ['task_e5f6a7b8']
```

### 7.3 操作后，C 保持原样

```text
status：pending
owner：null
blockedBy：[B]
```

它不会因为尝试过认领，就变成 `in_progress`。

### 7.4 “没开始”和“现在能开始”是两个判断

```text
status = pending：
  只表示尚未进入进行中状态。

前置任务全部完成：
  才表示依赖条件已经满足。
```

正常认领要同时通过状态检查和依赖检查。

## 8. 情况四：认领可以开始的 A

### 8.1 操作前

```text
A：
  status：pending
  owner：null
  blockedBy：[]
```

### 8.2 认领 A

```python
claim_task("task_a1b2c3d4")
```

检查过程：

```text
A 是 pending：通过。
A 没有尚未完成的前置任务：通过。

设置负责人和状态，保存文件。
```

### 8.3 操作后

```text
A：
  status：in_progress
  owner：agent
  blockedBy：[]
```

对应 JSON：

```json
{
  "id": "task_a1b2c3d4",
  "subject": "建立用户表",
  "description": "创建 users 表，包含 id、username 和 password_hash；完成后检查表结构。",
  "status": "in_progress",
  "owner": "agent",
  "blockedBy": []
}
```

可以理解为：

> “这个任务已经有人接手，当前负责人叫 agent。”

### 8.4 认领之后还要实际工作

认领动作只修改任务记录，真正建立用户表还需要后续操作，例如：

```text
读取数据库定义
    ↓
修改模型或迁移文件
    ↓
执行相应操作和检查
    ↓
确认用户表满足任务描述
```

要分清：

| 动作 | 修改什么 |
| --- | --- |
| `claim_task` | 任务账本：登记开始处理 |
| `write_file`、`edit_file`、`bash` | 实际代码、文件或运行环境 |
| `complete_task` | 任务账本：登记已完成 |

**任务状态变化，和实际工作内容变化，是两条需要配合的线。**

## 9. 情况五：完成 A，后续任务会自动开始吗

### 9.1 完成之前先确认实际工作已经做好

假设用户表已经建立，并且检查满足任务要求，Agent 调用：

```python
complete_task("task_a1b2c3d4")
```

程序检查：

```text
A 是 in_progress 吗？
  是。

A 的负责人和当前完成者一致吗？
  一致。

可以登记完成。
```

### 9.2 A 的变化

```text
完成前：
  status：in_progress
  owner：agent

完成后：
  status：completed
  owner：agent
```

完成后，当前实现会保留 `owner`，不会自动清空负责人。

### 9.3 程序检查哪些后续任务刚刚可以开始

```text
B 等 A：A 已完成，B 现在可以认领。

D 等 A：A 已完成，D 现在可以认领。

C 等 B：B 尚未完成，C 仍不能认领。
```

工具返回类似：

```text
Completed task_a1b2c3d4 (建立用户表)
Unblocked: 编写数据结构说明, 实现注册 API
```

`Unblocked` 表示“这些任务刚刚满足前置条件”。

### 9.4 处理后的全局状态

| 任务 | 状态 | 当前是否允许认领 |
| --- | --- | --- |
| A 用户表 | completed | 已完成，不能再次认领 |
| B 注册 API | pending | 可以 |
| C 注册测试 | pending | 不能，仍等 B |
| D 数据结构说明 | pending | 可以 |

**B 和 D 只是允许认领，没有自动变成进行中。**

当前代码也不会因为出现 `Unblocked`，就在后台启动它们。

### 9.5 B 的文件可能完全没变

A 完成后，B 仍然是：

```json
{
  "id": "task_e5f6a7b8",
  "subject": "实现注册 API",
  "description": "增加注册接口，将用户写入 users 表。",
  "status": "pending",
  "owner": null,
  "blockedBy": ["task_a1b2c3d4"]
}
```

注意：

- `status` 仍是 `pending`。
- `owner` 仍是 `null`。
- `blockedBy` 中仍然保留 A 的 ID。

程序没有删除依赖边，而是读取 A 的状态，发现要求已经满足。

所以：

> 解锁可以只是检查结果发生变化，被解锁任务的文件不一定因此改写。

列表里继续出现 `blockedBy: A`，也不等于“现在一定还被 A 卡住”。它保存的是前置关系；是否仍阻塞，要看 A 当前的状态。

## 10. 情况六：完成 B，只报告这次刚解锁的 C

### 10.1 认领并实际完成 B

先认领：

```python
claim_task("task_e5f6a7b8")
```

然后实际编写 API、做相应验证，再登记完成：

```python
complete_task("task_e5f6a7b8")
```

### 10.2 C 和 D 的情况不同

```text
C 等 B：
  B 刚完成，所以 C 刚刚可以开始。

D 等 A：
  A 之前就完成了，所以 D 早就可以开始。
```

本次返回：

```text
Completed task_e5f6a7b8 (实现注册 API)
Unblocked: 编写并运行注册测试
```

不会把 D 反复报告成刚解锁。

### 10.3 ready_before 可以理解成两个名单的差别

```text
完成 B 之前：
  已经可以认领的有依赖待办任务：D。

完成 B 之后：
  已经可以认领的有依赖待办任务：C、D。

这次新增：C。
```

`complete_task()` 中的 `ready_before` 就是先记住旧名单，再找新出现的任务。

**`Unblocked` 是本次新放行的任务，不是所有可做任务的完整列表。**

### 10.4 多个任务可做，不代表已经并行执行

A 完成后，B 和 D 都允许开始。模型可以决定先做哪个。

当前 Agent Loop 仍按工具调用顺序执行；这份文件没有因为依赖图分叉就自动生成多个工作进程。

本节也没有“全局最多一个任务可以 in_progress”的检查。顺序调用工具时，可以先后把多个就绪任务登记为进行中；这仍不等于已经为它们启动并行执行。

## 11. 情况七：一个任务要同时等两件事

### 11.1 新增 E：交付前验收

假设要求：

```text
C 注册测试完成。
D 数据结构说明完成。

两项都完成以后，才能做 E 交付前验收。
```

先创建 E，假设返回 `task_99aabbcc`，再添加依赖：

```python
update_task(
    task_id="task_99aabbcc",
    addBlockedBy=[
        "task_11223344",
        "task_55667788"
    ]
)
```

可以简写为：

```text
E.blockedBy = [C, D]
```

关系：

```text
C 注册测试 ───────┐
                 ├──→ E 交付前验收
D 数据结构说明 ──┘
```

### 11.2 要求全部完成

| C 的状态 | D 的状态 | E 能否认领 |
| --- | --- | --- |
| pending | pending | 不能 |
| completed | pending | 不能 |
| completed | in_progress | 不能 |
| completed | completed | 可以 |

多个依赖表示“都得完成”，而不是“任意一个完成即可”。

### 11.3 只完成 C 时

```python
claim_task("task_99aabbcc")
```

返回：

```text
Blocked by: ['task_55667788']
```

因为 C 已完成，真正还在等待的是 D。

E 的状态仍然是：

```text
status：pending
owner：null
blockedBy：[C, D]
```

### 11.4 D 也完成以后

完成 D 的结果中可以出现：

```text
Unblocked: 交付前验收
```

E 现在允许认领，但仍然是 `pending`，需要下一次明确调用 `claim_task` 才进入 `in_progress`。

## 12. 情况八：错误的依赖关系怎样被拒绝

下面几个例子，回到任务都还没开始、目标任务仍是 `pending` 且无人认领的阶段。

这样能看到依赖关系本身的校验结果；如果任务已经开始，会先被状态检查挡住。

### 12.1 自依赖：自己等自己

```python
update_task(
    task_id="task_a1b2c3d4",
    addBlockedBy=["task_a1b2c3d4"]
)
```

含义：

```text
A：等我自己完成，我才开始。
```

这无法成立，程序拒绝：

```text
Task cannot depend on itself
```

通过统一工具入口时，异常会包装成带 `Error:` 前缀的工具结果，供模型读取。

### 12.2 循环依赖：大家互相等

已有：

```text
B 等 A。
C 等 B。
```

再让 A 等 C，就变成：

```text
A 等 C。
C 等 B。
B 等 A。
```

没有一个任务能先开始。

调用示例：

```python
update_task(
    task_id="task_a1b2c3d4",
    addBlockedBy=["task_11223344"]
)
```

程序会拒绝，返回依赖循环错误。

`_depends_on()` 所做的追查可以读成：

```text
准备让 A 等 C。
    ↓
先问：C 是否已经直接或间接在等 A？
    ↓
沿着 C 的前置关系查：C → B → A。
    ↓
确实已经在等 A，不能再添加。
```

这里的追查箭头表示“向前置任务查找”，与前面的“完成后放行后续任务”的画图方向不同，阅读时要看箭头表达的含义。

### 12.3 依赖不存在的任务

假设 B 原来依赖 A，现在一次想新增 D 和一个不存在的任务：

```python
update_task(
    task_id="task_e5f6a7b8",
    addBlockedBy=[
        "task_55667788",
        "task_00000000"
    ]
)
```

程序发现 `task_00000000` 不存在，拒绝保存。

```text
修改前：B.blockedBy = [A]

修改失败后：B.blockedBy = [A]
```

不会只加上合法的 D，再忽略后面的错误。

原因是先验证这一批新增关系，全部通过后才扩展列表并保存。

这是本次依赖校验失败不产生部分修改的保证，不代表整个文件存储已经具备数据库式的事务和崩溃恢复。

### 12.4 重复添加同一个依赖

任务仍符合可更新条件时：

```text
原来：B.blockedBy = [A]

再添加：[A, A]

最后：B.blockedBy = [A]
```

不会累积重复边。

### 12.5 开始以后才补前置条件

如果 B 已经被认领：

```text
status：in_progress
owner：agent
```

再调用 `update_task` 添加依赖，会被拒绝。

当前规则要求目标任务同时满足：

```text
status == pending
owner == None
```

也就是没开始、没人接手时才能修改前置关系。

### 12.6 update_task 的名字很宽，实际功能很具体

当前只支持追加依赖，不支持通过这个工具任意修改：

- 标题或详细描述。
- 状态。
- 负责人。
- 删除某条依赖。
- 删除任务、重开任务或把进行中任务退回待办。

判断功能时以函数体和工具参数为准。

## 13. 情况九：状态不对、负责人不对，也不能完成

### 13.1 pending 任务不能直接完成

```python
complete_task("task_a1b2c3d4")
```

如果 A 还没认领，返回：

```text
Task task_a1b2c3d4 is pending, cannot complete
```

正常路径先认领，再完成：

```text
pending → in_progress → completed
```

### 13.2 已完成任务不能再次认领

A 已经 `completed`，再调用：

```python
claim_task("task_a1b2c3d4")
```

返回：

```text
Task task_a1b2c3d4 is completed, cannot claim
```

同样，一个已经 `in_progress` 的任务也不能再用认领动作重新认领。

### 13.3 负责人不一致不能完成

用底层 Python 函数举例：

```python
claim_task("task_a1b2c3d4", owner="alice")
```

任务变成：

```text
status：in_progress
owner：alice
```

另一个名字来完成：

```python
complete_task("task_a1b2c3d4", owner="bob")
```

返回类似：

```text
Task task_a1b2c3d4 is owned by alice, not bob
```

任务仍然是 `in_progress`，负责人仍是 alice。

### 13.4 底层函数和模型工具的参数不同

底层函数支持 `owner` 参数，但本节暴露给模型的工具包装固定使用：

```python
claim_task(task_id, owner="agent")
complete_task(task_id, owner="agent")
```

模型工具参数里没有单独的 `owner` 字段。

因此，这里已经有“负责人”数据和检查，但还没有实现完整的多 Agent 身份管理与调度。上面的 alice/bob 示例是说明底层函数规则。

## 14. 情况十：退出程序以后怎样恢复进度

### 14.1 退出前的状态

```text
A：completed。
B：in_progress，owner=agent。
C：pending，依赖 B。
D：pending，依赖 A。
```

磁盘记录仍是：

```text
.tasks/
  task_a1b2c3d4.json
  task_e5f6a7b8.json
  task_11223344.json
  task_55667788.json
```

### 14.2 重启后，先读任务总览

从同一个工作目录重新运行，新的 `history` 从空列表开始，但任务文件还在。

模型调用 `list_tasks` 工具后，能看到一行一条的摘要，例如：

```text
[x] task_a1b2c3d4: 建立用户表 [completed] [agent]
[>] task_e5f6a7b8: 实现注册 API [in_progress] [agent] (blockedBy: task_a1b2c3d4)
[ ] task_11223344: 编写并运行注册测试 [pending] (blockedBy: task_e5f6a7b8)
[ ] task_55667788: 编写数据结构说明 [pending] (blockedBy: task_a1b2c3d4)
```

图标含义：

```text
[ ]：pending。
[>]：in_progress。
[x]：completed。
```

这里为了阅读按 A、B、C、D 排列。实际代码按文件名排序，不保证创建顺序或依赖顺序。

### 14.3 再打开一张卡片看细节

```python
get_task("task_e5f6a7b8")
```

返回完整 JSON：

```json
{
  "id": "task_e5f6a7b8",
  "subject": "实现注册 API",
  "description": "增加注册接口，将用户写入 users 表。",
  "status": "in_progress",
  "owner": "agent",
  "blockedBy": ["task_a1b2c3d4"]
}
```

区别是：

| 工具 | 可以理解成什么 | 主要看到什么 |
| --- | --- | --- |
| `list_tasks` | 看任务总览 | 标题、状态、负责人、依赖 |
| `get_task` | 打开单张任务卡片 | 包含详细描述的完整 JSON |

### 14.4 记录恢复，不等于工作自动续上

程序不会在启动时自动找到所有未完成任务并执行。

正常恢复过程需要模型主动读取记录，再确认项目现场：

```text
列出任务
    ↓
找到上次进行中的 B
    ↓
读取 B 的详细描述
    ↓
读取当前代码，检查已修改内容和测试情况
    ↓
继续剩余工作
```

B 可能上次只改了一半。任务卡片记录“正在做”，不一定包含每一步代码修改细节，因此仍需检查文件和运行结果。

### 14.5 工作目录影响任务存储位置

源码使用：

```python
WORKDIR = Path.cwd()
TASKS_DIR = WORKDIR / ".tasks"
```

从项目根目录运行，使用项目根目录的 `.tasks/`。换一个工作目录，默认指向的任务库也会变化。

## 15. 把“登记状态”和“真正完成工作”分开

这是理解本节最重要的边界之一。

```text
create_task：登记有这件事要做。

claim_task：登记开始处理。

write_file / edit_file / bash：真正修改文件、执行操作、验证结果。

complete_task：登记已经完成。
```

### 15.1 complete_task 不会自动验证实际成果

它主要检查：

```text
状态是否为 in_progress。
负责人是否一致。
```

它不会自动检查：

```text
数据库表真的创建了吗？
注册接口能用吗？
测试通过了吗？
文档完整了吗？
```

因此，正常顺序应该是：

```text
认领任务
    ↓
完成实际工作
    ↓
做相应验证
    ↓
登记完成
```

如果模型没有工作就标记完成，这份任务系统不能仅靠状态检查发现所有虚报。

### 15.2 complete_task 不重新证明前置工作成果

正常情况下，认领时已经检查依赖。完成时主要检查状态和负责人，没有自动检查实际代码，也没有把所有前置条件重新验证一遍。

这本账本的作用是追踪和约束工作流；任务描述写得清楚、模型完成前检查成果，仍然重要。

## 16. 读源码时容易误解的细节

### 16.1 can_start 只检查依赖，不检查当前任务状态

代码是：

```python
def can_start(task_id: str) -> bool:
    return not incomplete_dependencies(load_task(task_id))
```

它只回答：

> 这个任务有没有尚未满足的前置关系？

因此 A 已经 `completed`，而且没有未完成依赖时：

```text
can_start(A)：可能是 True。

claim_task(A)：仍然拒绝，因为 A 已经 completed。
```

完整的认领规则要看 `claim_task`，不能只看 `can_start` 这个名字。

### 16.2 前置任务文件丢了，不会当作已经完成

```text
B.blockedBy = [A]

A 的文件不存在。
```

`incomplete_dependencies()` 捕获文件不存在的情况，把 A 视为未满足依赖，B 仍不能认领。

这比“找不到就算完成”更符合依赖约束。其他未被该函数捕获的异常仍可能向外传递。

### 16.3 两类 ID 不要混淆

模型调用工具时，还会有工具调用 ID，用来把一次调用和一次返回配对。

```text
工具调用 ID：
  例如 call_001，表示这一次工具调用。

任务 ID：
  例如 task_a1b2c3d4，表示磁盘上的某张任务卡片。
```

例如：

```text
工具调用 call_001：
  创建“建立用户表”。

工具结果对应 call_001：
  Created task_a1b2c3d4: 建立用户表。
```

后续查看、认领和完成任务时，使用 `task_a1b2c3d4`；`tool_use_id` 则用于会话里工具调用和结果配对。

### 16.4 输入校验和文件路径校验

任务 ID 要符合：

```text
task_ + 8位小写十六进制字符。
```

`../outside` 这类字符串不能作为任务 ID 使用。

存储还会检查路径解析后是否仍处于允许的工作目录中，避免任务目录或文件通过路径跳到工作区之外。

这些校验帮助保证读写的是任务库里的文件，而不是把工具参数直接当任意文件路径使用。

### 16.5 工具报错怎样回到模型

`execute_tool()` 会把一般工具异常转换成文字：

```text
Error: Dependency not found: task_00000000
```

然后 Agent Loop 把这段文字作为工具结果追加到 `messages`。

模型下一次就能读到错误，修正 ID、依赖或操作顺序。

“任务状态不对”“仍有前置任务未完成”等分支，有些直接返回提示字符串；不需要所有失败都先抛出异常。

### 16.6 创建 ID 的保护，不等于并发认领安全

创建任务用排他写入避免覆盖同名文件。

但认领流程是：

```text
读取任务
    ↓
检查状态和依赖
    ↓
设置owner和status
    ↓
写回文件
```

当前没有为多个进程同时认领同一张卡片实现完整的锁或原子竞争控制。

所以 s10 提供了任务状态和依赖关系这个基础，不能直接认为已经解决全部并发协作问题。

## 17. 放回 Agent Loop：模型怎样使用这本账本

任务工具与普通工具通过同一个执行入口处理：

```text
用户提出需求
    ↓
主模型决定调用什么工具
    ↓
如果是create_task / update_task / claim_task等：
  Python读取、检查、修改.tasks中的任务记录。

如果是read_file / write_file / bash等：
  Python读取文件、修改代码或执行命令。
    ↓
把每个工具结果写进messages
    ↓
再次请求主模型
    ↓
模型根据结果决定下一步
```

一次可能的过程：

```text
第一轮：模型要求创建 A、B、C、D。
程序：创建文件，把真实 ID 返回。

第二轮：模型使用真实 ID 添加依赖。
程序：检查并保存关系，返回结果。

第三轮：模型认领 A。
程序：把 A 改为 in_progress。

后续：模型调用普通工具完成建表和检查。

再后续：模型完成 A，读到 B、D 被解锁。

继续：模型选择下一项工作。
```

工具执行完，依靠返回的文字让模型知道发生了什么。任务系统本身没有一个独立的自动调度循环，替模型把整张图全部跑完。

另一个边界：模型不再调用工具、Stop Hook 也没有要求继续时，Agent Loop 就会结束。本节不会在结束前强制检查“是不是所有任务都 completed”。

## 18. 和 s08、s09 放在一起理解

| 位置或章节 | 主要保存什么 | 例子 |
| --- | --- | --- |
| `messages` | 当前会话工作记录 | 刚读了什么、模型怎么回复、工具返回什么 |
| s08 归档与压缩 | 当前任务移出上下文的内容与摘要 | 旧日志、长对话、阶段摘要 |
| s09 `.memory/` | 以后仍适用的知识 | 用户偏好、项目约定、资料线索 |
| s10 `.tasks/` | 具体工作的状态和前置关系 | API 正在做，测试必须等 API |

例如：

```text
“用户学代码喜欢举例子。”
  更适合长期记忆。

“注册 API 已认领，注册测试尚未开始。”
  更适合任务记录。

“刚才跑测试的完整输出。”
  属于当前工作记录，太长时可由上下文管理处理。
```

当前 `s10_task_system/code.py` 在基础工具、权限和 Hook 循环上加入任务系统，没有接入 s08 的压缩器或 s09 的记忆流程。

因此要按这份文件实际包含的功能理解，而不是认为所有前面章节的能力都会自动累积到本节。

## 19. 工具、函数和状态速查

### 19.1 六个任务工具

| 工具 | 通俗理解 | 主要作用 |
| --- | --- | --- |
| `create_task` | 建一张卡片 | 生成 ID，保存初始任务 |
| `update_task` | 加上“我在等谁” | 给待办且无人认领的任务追加依赖 |
| `list_tasks` | 看总览 | 列出标题、状态、负责人和依赖 |
| `get_task` | 打开卡片看详情 | 返回包括 description 的完整 JSON |
| `claim_task` | 接手这项工作 | 检查状态和前置关系，登记为进行中 |
| `complete_task` | 登记工作完成 | 检查状态和负责人，保存完成状态，报告新解锁任务 |

### 19.2 关键内部函数

| 位置 | 重点看什么 |
| --- | --- |
| `Task` | 一张任务卡片有哪些字段 |
| `TaskStore.create` | 创建目录、生成 ID、排他写入初始文件 |
| `TaskStore.load` | 从文件读回任务，并检查 ID 与状态 |
| `TaskStore.save` | 把任务对象重新写入 JSON |
| `TaskStore.update_dependencies` | 依赖校验通过后再统一保存 |
| `TaskStore._depends_on` | 沿前置关系查找，避免循环依赖 |
| `incomplete_dependencies` | 找出还没 completed 的前置任务 |
| `can_start` | 是否没有未满足依赖，不检查任务自身状态 |
| `run_list_tasks` | 把任务对象列表转换成面向模型的摘要文字 |
| `execute_tool` | 执行工具、触发 Hook、把异常转换成工具结果 |
| `agent_loop` | 模型决定操作，程序执行，把结果交回模型 |

### 19.3 常见状态变化

| 操作 | 操作前 | 操作后 |
| --- | --- | --- |
| 创建 | 没有记录 | pending、无owner、空依赖 |
| 添加依赖 | pending且无人认领 | 仍为pending，追加blockedBy |
| 认领成功 | pending且依赖满足 | in_progress，设置owner |
| 认领被阻塞 | pending但依赖未完成 | 保持原样 |
| 完成成功 | in_progress且负责人一致 | completed，保留owner |
| 前置任务完成 | 下游pending但有未满足依赖 | 下游仍pending，只是现在可能允许认领 |

## 20. 把完整任务走一遍

下面使用缩写方便回忆。工具中仍应传实际 ID。

### 20.1 建立任务和关系

```text
创建 A：用户表。
创建 B：注册 API。
创建 C：注册测试。
创建 D：数据结构说明。

拿到真实 ID 后：
  B 等 A。
  C 等 B。
  D 等 A。
```

### 20.2 初始状态

```text
A pending，可认领。
B pending，等 A。
C pending，等 B。
D pending，等 A。
```

### 20.3 完成 A

```text
认领 A → 实际建表并检查 → 登记 A 完成。

A completed。
B pending，现在可认领。
C pending，仍等 B。
D pending，现在可认领。
```

### 20.4 完成 B

```text
认领 B → 实际编写 API 并检查 → 登记 B 完成。

A completed。
B completed。
C pending，现在可认领。
D pending，之前就可认领。
```

### 20.5 完成 C 和 D

```text
认领 C → 实际补测试、运行测试、处理问题 → 登记 C 完成。

认领 D → 实际写数据结构说明并检查 → 登记 D 完成。

四张卡片最后都为 completed。
```

如果还有 E 交付前验收，依赖 C、D，那么两项都完成后再认领、实际验收、登记完成。

每一步都把两条线分开看：

```text
任务账本这条线：pending → in_progress → completed。

实际工作这条线：读文件 → 改代码或文档 → 执行验证。
```

## 21. 复习问答

### 问题1：创建“建立用户表”任务，会真的建立用户表吗？

不会。创建的是任务卡片和 JSON 文件。实际建表需要后续代码修改、数据库操作等工作。

### 问题2：B.blockedBy = [A]，谁等谁？

B 等 A。A 完成后，B 的前置条件才满足。

### 问题3：A 完成后，B 会自动变成 in_progress 吗？

不会。B 通常仍是 pending，只是允许认领。要进入进行中，还需要明确调用 `claim_task`。

### 问题4：A 完成后，B 的 blockedBy 为什么仍有 A？

因为它保留的是前置关系。程序读取 A 的状态，判断这条要求是否已经满足，不需要删除依赖边。

### 问题5：pending 是否表示现在就能做？

不一定。它只表示还没开始。是否能认领，还要检查所有前置任务是否完成。

### 问题6：E 依赖 C、D，完成 C 就能认领 E 吗？

不能。列表中的前置任务必须全部 completed。D 还没完成就继续阻塞。

### 问题7：同一条依赖重复添加，会出现多个相同 ID 吗？

目标仍符合可更新条件时，重复依赖会去重，不会增加重复边。

### 问题8：一次新增两条依赖，一条合法、一条不存在，会只加合法那条吗？

不会。整次关系校验通过后才追加并保存。这个例子的校验失败后，原关系保持不变。

### 问题9：为什么不能先猜一个 A 的 ID，再让 B 依赖它？

ID 由程序运行时随机生成。模型要先收到创建结果，再用真实 ID 添加关系，否则可能引用不存在的任务。

### 问题10：已完成的 A，can_start(A) 是否一定是 False？

不一定。`can_start` 只检查依赖，可能返回 True；`claim_task` 会额外检查状态，拒绝再次认领已完成任务。

### 问题11：Unblocked 返回的是所有可做任务吗？

不是。它返回这次完成动作刚刚放行的下游任务；之前已经可做的任务不会被重复报成新解锁。

### 问题12：有多个可认领任务，程序会自动并行执行吗？

不会。当前仍由模型决定下一步工具调用，并由 Agent Loop 顺序执行。本节没有自动并行调度器。

### 问题13：complete_task 会验证测试通过吗？

不会自动验证。它主要检查任务正在进行、负责人一致。模型应在实际工作和相应验证完成后再登记完成。

### 问题14：退出重启后，任务会自动接着做吗？

任务文件可以读回，但需要模型主动列出、查看任务，再检查项目现场继续工作。当前没有启动即自动续跑的机制。

### 问题15：为什么状态恢复了，还要重新读代码？

卡片可能只记录“API 正在做”，没有保存每一步编辑细节。代码可能只改了一半，需要重新确认实际成果。

### 问题16：模型工具能直接传 owner="alice" 吗？

当前暴露的工具没有这个参数，包装函数固定使用 `agent`。底层 Python 函数支持 owner，用于表达负责人检查。

### 问题17：前置任务文件丢失，会认为这项要求已经满足吗？

不会。文件不存在时，这个依赖被视为未满足，下游不能因此被放行。

### 问题18：本节自动包含 s08 压缩和 s09 记忆吗？

没有。当前文件在基础工具与 Hook 上加入任务系统，未接入前两节的完整流程。

## 22. 回到源码时的阅读顺序

建议先沿着一条最短路线阅读：

```text
创建 A、B
    ↓
让 B 等 A
    ↓
认领 A
    ↓
实际完成工作
    ↓
登记 A 完成
    ↓
B 现在允许认领
```

对应源码查找顺序：

1. `Task`：看一张卡片保存哪些信息。
2. `TaskStore.create`：看卡片怎样生成 ID、保存成文件。
3. `update_dependencies`：看怎样连接前置关系。
4. `incomplete_dependencies` 和 `claim_task`：看为什么有些待办任务还不能开始。
5. `complete_task`：看完成后怎样识别新放行的任务。
6. `run_list_tasks` 和 `get_task`：看怎样查看总览与详情。
7. `agent_loop`：看模型怎样调用这些工具、读取操作结果、继续决定下一步。

先把任务记录的变化看清楚，再研究随机 ID、路径校验、图遍历和工具包装等实现细节。
