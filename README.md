# Agent Runtime Lab

一个用于学习和验证 Agent 应用工程的轻量 Runtime Lab。

项目目标不是做一个单点聊天机器人，而是把 Agent 应用落地中最关键的运行时能力拆成可运行、可观察、可评估的小模块：

- LLM 客户端
- Agent 主循环
- 工具注册、schema 与受控调用
- 工具权限、风险等级与人工确认
- Agent Run / Tool Call Trace
- 本地状态持久化
- 最小离线评估集

`notes/` 笔记助手和实验工作流 Proposal 是当前内置的两个 demo plugin，用来验证 Runtime 能力；后续可以替换成 PWmat/Mcloud/Q-Flow、MCP 工具、Web API 或其他业务插件。

这个初版刻意保持轻量：不依赖重型 Agent 框架，先帮助你理解 Agent Runtime 的核心组件：

- LLM 客户端
- Agent 主循环
- 工具注册与调用
- 本地记忆
- 本地 Markdown 笔记读取与搜索
- 运行日志和 trace

## 当前能力

- 命令行对话
- 可选调用 OpenAI 兼容的 Chat Completions 接口
- 本地演示模式，无 API Key 也能使用基础命令
- 读取 `notes/` 下的学习资料，支持 Markdown、TXT、PDF、DOCX
- 搜索 `notes/` 下的学习资料
- 保存和查看学习记忆
- 生成实验自动化工作流 Agent 草案，用于把实习方向转成可运行原型
- 支持实验工作流 Proposal 状态机：`need_info` / `ready` / `applied`
- 支持基于当前 Proposal 的本地诊断建议
- 使用 SQLite 持久化长期记忆、会话消息、Agent Run、工具调用、Proposal 与事件
- 支持短期会话记忆，可复用上一轮回答
- 支持 `/runs` 查看最近 Agent Run 与工具调用日志
- 支持 `/runs --detail` 和 `/trace <run_id>` 查看单次 Agent Run 的工具调用 trace
- 工具声明读写范围、风险等级和确认要求，并在调用前做最小参数校验
- 提供 `evals/minimal_cases.jsonl` 作为最小离线评估用例集
- 使用隔离临时 SQLite 数据库运行 smoke test，避免污染真实学习记忆
- 每次代码变更后，同步在 `notes/` 保存架构、流程、边界与 ADR 说明

## 目录结构

```text
app/
  main.py                 # CLI 入口
  config.py               # 配置与路径
  agents/
    simple_agent.py       # 最小 Agent 主循环
  core/
    llm.py                # 大模型调用封装
    messages.py           # 消息类型
    prompts.py            # 系统提示词
  memory/
    store.py              # 本地记忆存储
  proposals/
    store.py              # 旧版 JSON Proposal 存储，保留用于兼容
    experiment.py         # 实验工作流 Proposal 生成与诊断
  session/
    state.py              # 当前 CLI 会话的短期上下文
  storage/
    sqlite_store.py       # SQLite 状态、运行日志与 Proposal 存储
  workflows/
    state_machine.py      # 可配置状态机加载与校验
    experiment_proposal_state_machine.json
                            # 实验 Proposal 状态机配置
  tools/
    base.py               # 工具定义
    registry.py           # 工具注册器
    experiment_tools.py   # 实验自动化工作流规划工具
    note_tools.py         # 笔记/资料工具
    memory_tools.py       # 记忆工具
evals/
  README.md               # 评估集说明
  minimal_cases.jsonl     # 10 条最小 Agent Runtime 评估用例
notes/
  agent.md                # 入门笔记示例
  architecture-and-adr.md # 当前架构、流程、记忆边界、工具权限和 ADR 快照
data/
  .gitkeep                # 运行时生成 learning_agent.db
```

## 学习资料支持范围

`notes/` 目录当前支持这些文件类型：

- `.md` / `.markdown`
- `.txt`
- `.pdf`
- `.docx`

PDF 默认通过 `pypdf` 解析文本；如果环境中没有安装 `pypdf`，会回退到项目内置的轻量解析器读取常见小型文本 PDF。扫描件、图片型 PDF、复杂排版 PDF 仍可能无法可靠提取文本。

通用搜索会默认跳过超过大小上限的大文件，避免每次关键词搜索都被大型 PDF 拖慢。需要处理大 PDF 时，优先直接读取指定文件，或在工具调用里显式设置 `include_large_files=true`。

Word 目前支持 `.docx`，不支持旧版二进制 `.doc`。

## 本地状态存储

当前默认用 `data/learning_agent.db` 保存长期记忆、会话消息、Agent Run、工具调用、Proposal 与 Proposal 事件。

SQLite 当前包含这些表：

```text
memories      长期学习记忆
sessions      CLI 会话
messages      会话消息
tool_results  最近工具结果摘要
agent_runs    每次 Agent 处理用户输入的运行记录
tool_calls    正式工具调用日志
proposals     Proposal 当前快照与历史状态
proposal_events Proposal 状态变化事件
```

运行日志可以通过 CLI 查看：

```powershell
python -m app.main "/runs"
python -m app.main "/runs --detail"
python -m app.main "/trace latest"
```

`/runs` 会展示最近 Agent Run 的状态、工具调用数量、失败数量和工具耗时摘要。
`/runs --detail` 会展示最近一次 Agent Run 的 trace，包含用户输入、运行状态、工具调用参数、审计信息、执行结果摘要与错误。
`/trace <run_id>` 可以查看指定 run；不传 run id 时默认查看最近一次。

如果本地已有旧版 `data/memory.json` 或 `data/proposals.json`，启动时会在对应 SQLite 表为空的情况下做一次非破坏性导入；不会删除旧 JSON 文件。

Proposal 状态转换由 `app/workflows/experiment_proposal_state_machine.json` 配置驱动。当前核心流转包括：

```text
ready + viewed -> ready
ready + applied -> applied
applied + diagnosed -> diagnosed
diagnosed + revised -> ready
```

非法转换会被拒绝，并返回明确错误。

## 快速开始

确认本机有 Python 3.10 或更高版本：

```powershell
python --version
```

启动 CLI：

```powershell
python -m app.main
```

运行本地 smoke test：

```powershell
python scripts/smoke_test.py
```

如果还没有配置 API Key，会进入本地演示模式。你可以先试这些命令：

```text
/help
/session
/runs
/runs --detail
/trace latest
/save-last
/tools
/notes
/read agent.md
/read Hello-Agents-V1.0.2-20260210.pdf
/search Agent 主循环
/remember 今天理解了 Agent = 模型 + 工具 + 控制流程
/memory
/experiment 比较 40/50/60 摄氏度下的反应效率
/proposal
/proposal-detail
/apply-proposal
/diagnose 端口连接超时
```

会话消息现在会持久化到 SQLite。它用于支持“保存刚才的内容”“这三个要点”“上一轮回答”等指代；需要长期保留时使用 `/save-last` 或自然语言保存请求，内容会写入 `memories` 表。

记忆边界：

- 会话记忆：自动记录最近对话和工具结果，服务于当前会话上下文。
- 长期记忆：只保存用户明确要求或对项目长期有价值的信息。
- 工具结果：只保存摘要，避免大文件内容污染上下文。

工具权限边界：

- 模型只能调用 `ToolRegistry` 注册的项目工具，不能直接访问文件系统。
- 笔记工具只允许访问 `notes/` 内的受支持文件类型。
- 工具 schema 禁止未知参数，并校验基础类型与范围。
- 实验 Proposal 当前只写本地记录，不控制真实设备或外部系统。

## 接入大模型

复制 `.env.example` 为 `.env`，然后填写你的模型配置：

```text
OPENAI_API_KEY=你的_api_key
OPENAI_MODEL=gpt-4.1-mini
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_TEMPERATURE=0.2
```

再次启动：

```powershell
python -m app.main
```

接入模型后，你可以用自然语言说：

```text
帮我搜索笔记里关于 Agent 主循环的内容，并总结成 3 个学习要点
```

Agent 会把 `search_notes`、`read_note`、`save_memory`、`list_memory` 这些工具作为 function calling 工具提供给模型。
模型会先判断是否需要调用工具，Python 负责真正执行本地文件读取、搜索或记忆保存，最后再由模型组织回答。

最小验收可以试：

```text
帮我列出当前有哪些学习笔记
帮我搜索笔记里关于 Agent 主循环的内容，并总结成 3 点
保存这三个要点
请记住：我已经完成 Agent Runtime Lab 的大模型接入
查看最近的学习记忆
帮我生成一个比较 40/50/60 摄氏度下反应效率的实验工作流草案
```

## 实习方向：实验自动化工作流 Agent

当前项目已经加入一个最小的实验工作流规划工具：`plan_experiment_workflow`，以及围绕它的 Proposal 状态机。
它在本项目中的定位是 demo plugin：用来验证 Runtime 的工具 schema、权限边界、人工确认、状态机、trace 和审计日志，而不是绑定到某一个垂直行业。

它不会控制真实设备，只负责把用户的实验目标转成可审查、可确认、可记录的工作流提案，包括：

- `need_info`：信息不足，追问关键参数
- `ready`：信息足够，生成可查看详情的 Proposal
- `applied`：人工确认后应用到本地记录，防止重复应用
- `diagnosed`：基于当前 Proposal 生成诊断建议
- 实验目标与成熟度标注
- 参数表
- 推荐步骤
- 失败与降级路径
- 风险提示
- 结果记录模板

本地演示命令：

```powershell
python -m app.main "/experiment 比较 40/50/60 摄氏度下的反应效率"
python -m app.main "/proposal-detail"
python -m app.main "/apply-proposal"
python -m app.main "/diagnose 端口连接超时"
python -m app.main "/runs --detail"
```

这个能力的定位是 Pilot：适合用于实习竞品调研、工作流抽象和 PoC 展示；在接入真实实验设备前，必须补充权限校验、人工确认、审计日志、设备状态检查、后台执行队列和急停机制。

## 最小评估集

`evals/minimal_cases.jsonl` 当前包含 10 条最小用例，覆盖：

- CLI 命令路由
- 工具清单和权限展示
- 笔记列表、读取、搜索
- 记忆写入
- Proposal 的 `need_info` 与 `ready` 状态
- Proposal 详情
- Agent trace 可见性

这些用例先采用 `expected_contains` 方式描述验收条件，保持模型无关。后续可以增加 `evals/runner.py`，把每条用例自动喂给 `SimpleAgent`，输出任务完成率、工具选择准确率、审批触发率和 trace 完整度。

## 学习路线

建议你按这个顺序迭代：

1. 跑通当前 CLI 与本地工具
2. 阅读 `app/agents/simple_agent.py`，理解 Agent 主循环
3. 给 `notes/` 添加自己的学习笔记
4. 接入大模型，观察工具调用过程
5. 加入 SQLite，把记忆、会话、运行日志和 Proposal 升级为数据库
6. 使用 `/runs --detail` 和 `/trace` 观察工具调用链路
7. 用 `evals/minimal_cases.jsonl` 固化最小质量线
8. 加入 embedding 与向量检索，升级成 RAG plugin
9. 加入 FastAPI 和前端页面
10. 尝试 MCP 工具适配、LangGraph 工作流或多 Agent

## 设计原则

这个项目的核心不是一开始做得很复杂，而是让 Runtime 的每一层都能独立成长：

- `core/llm.py` 只负责模型调用
- `tools/` 只负责工具定义和执行
- `memory/` 只负责记忆读写
- `agents/` 只负责编排模型和工具
- `storage/` 只负责状态、run 和 tool call 持久化
- `evals/` 只负责定义可重复验收用例
- `notes/` 存放你的真实学习材料

后续无论换模型、加工具、接数据库、做 RAG、接 MCP 或迁移到 Web UI，都可以小步扩展。
