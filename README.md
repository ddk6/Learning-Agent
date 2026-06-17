# Learning Agent

一个用于学习大模型应用开发的个人学习与项目助理 Agent。

这个初版刻意保持轻量：不依赖第三方框架，不强制使用数据库，先帮助你理解 Agent 的核心组件：

- LLM 客户端
- Agent 主循环
- 工具注册与调用
- 本地记忆
- 本地 Markdown 笔记读取与搜索

## 当前能力

- 命令行对话
- 可选调用 OpenAI 兼容的 Chat Completions 接口
- 本地演示模式，无 API Key 也能使用基础命令
- 读取 `notes/` 下的学习资料，支持 Markdown、TXT、PDF、DOCX
- 搜索 `notes/` 下的学习资料
- 保存和查看学习记忆
- 生成实验自动化工作流 Agent 草案，用于把实习方向转成可运行原型
- 使用隔离临时记忆文件运行 smoke test，避免污染真实学习记忆

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
  tools/
    base.py               # 工具定义
    registry.py           # 工具注册器
    experiment_tools.py   # 实验自动化工作流规划工具
    note_tools.py         # 笔记/资料工具
    memory_tools.py       # 记忆工具
notes/
  agent.md                # 入门笔记示例
data/
  .gitkeep                # 运行时生成 memory.json
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

## 本地记忆格式

当前阶段用 `data/memory.json` 保存长期学习记忆。每条记忆使用这个最小 schema：

```json
{
  "id": "uuid",
  "content": "记忆内容",
  "tags": ["learning"],
  "created_at": "2026-06-15T00:00:00+00:00"
}
```

代码会兼容早期的 `tag` 字符串字段，但新增记忆统一写入 `tags` 数组。

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
/notes
/read agent.md
/read Hello-Agents-V1.0.2-20260210.pdf
/search Agent 主循环
/remember 今天理解了 Agent = 模型 + 工具 + 控制流程
/memory
/experiment 比较 40/50/60 摄氏度下的反应效率
```

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
请记住：我已经完成 Learning Agent 的大模型接入
查看最近的学习记忆
帮我生成一个比较 40/50/60 摄氏度下反应效率的实验工作流草案
```

## 实习方向：实验自动化工作流 Agent

当前项目已经加入一个最小的实验工作流规划工具：`plan_experiment_workflow`。

它不会控制真实设备，只负责把用户的实验目标转成可审查的工作流草案，包括：

- 实验目标与成熟度标注
- 参数表
- 推荐步骤
- 失败与降级路径
- 风险提示
- 结果记录模板

本地演示命令：

```powershell
python -m app.main "/experiment 比较 40/50/60 摄氏度下的反应效率"
```

这个能力的定位是 Pilot：适合用于实习竞品调研、工作流抽象和 PoC 展示；在接入真实实验设备前，必须补充权限校验、人工确认、审计日志、设备状态检查和急停机制。

## 学习路线

建议你按这个顺序迭代：

1. 跑通当前 CLI 与本地工具
2. 阅读 `app/agents/simple_agent.py`，理解 Agent 主循环
3. 给 `notes/` 添加自己的学习笔记
4. 接入大模型，观察工具调用过程
5. 加入 SQLite，把 `data/memory.json` 升级为数据库
6. 加入 embedding 与向量检索，升级成 RAG 学习助手
7. 加入 FastAPI 和前端页面
8. 加入日志、评测、trace 和多 Agent

## 设计原则

这个项目的核心不是一开始做得很复杂，而是让每一层都能独立成长：

- `core/llm.py` 只负责模型调用
- `tools/` 只负责工具定义和执行
- `memory/` 只负责记忆读写
- `agents/` 只负责编排模型和工具
- `notes/` 存放你的真实学习材料

后续无论换模型、加工具、接数据库、做 RAG，都可以小步扩展。
