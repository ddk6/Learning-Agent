from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.tools.experiment_tools import infer_metric, infer_variables
from app.tools.registry import ToolRegistry


GENERIC_OBJECTIVE_WORDS = {
    "实验",
    "做实验",
    "帮我做实验",
    "设计实验",
    "帮我设计实验",
    "安排实验",
}


ToolCaller = Callable[[str, dict[str, Any]], str]


def create_experiment_proposal(
    objective: str,
    registry: ToolRegistry,
    tool_caller: ToolCaller | None = None,
) -> dict[str, Any]:
    objective = objective.strip()
    if not objective or objective in GENERIC_OBJECTIVE_WORDS or len(objective) < 8:
        return need_info_proposal(objective, ["请说明实验目标，例如比较什么条件、优化什么结果。"])

    questions = missing_information_questions(objective)
    if questions:
        return need_info_proposal(objective, questions)

    arguments = {"objective": objective}
    workflow = (
        tool_caller("plan_experiment_workflow", arguments)
        if tool_caller
        else registry.call("plan_experiment_workflow", arguments)
    )
    variables = infer_variables(objective) or ["用户目标中包含的实验参数"]
    metric = infer_metric(objective)
    return {
        "status": "ready",
        "kind": "experiment_workflow",
        "summary": f"生成实验工作流提案：{objective}",
        "objective": objective,
        "variables": variables,
        "metric": metric,
        "workflow": workflow,
        "risks": [
            "当前提案只生成本地计划，不控制真实设备。",
            "应用前需要人工确认设备、安全、样品和 SOP。",
            "后续接入 RAG 后必须给出来源引用。",
        ],
        "apply_plan": [
            "保存当前 Proposal 状态。",
            "把应用记录写入长期记忆，形成审计线索。",
            "保留 Proposal 详情，防止重复应用和方便复盘。",
        ],
    }


def missing_information_questions(objective: str) -> list[str]:
    questions: list[str] = []
    if not infer_variables(objective):
        questions.append("自变量或参数梯度是什么？例如温度、流量、时间、浓度。")
    metric = infer_metric(objective)
    if metric == "主要结果指标":
        questions.append("评价指标是什么？例如反应效率、产率、稳定性或耗时。")
    return questions


def need_info_proposal(objective: str, questions: list[str]) -> dict[str, Any]:
    return {
        "status": "need_info",
        "kind": "experiment_workflow",
        "summary": "实验信息不足，暂不能生成可应用提案。",
        "objective": objective,
        "questions": questions,
        "workflow": "",
        "risks": ["信息不足时不应让 Agent 盲猜实验参数。"],
        "apply_plan": [],
    }


def render_proposal_card(proposal: dict[str, Any]) -> str:
    status = str(proposal.get("status") or "unknown")
    summary = str(proposal.get("summary") or "")
    objective = str(proposal.get("objective") or "")

    if status == "need_info":
        questions = proposal.get("questions") or []
        question_lines = "\n".join(f"{index}. {item}" for index, item in enumerate(questions, start=1))
        return f"""# Proposal 状态：need_info

{summary}

## 已知目标
{objective or "未提供"}

## 需要补充
{question_lines}

请补充这些信息后重新运行 `/experiment ...`。"""

    risks = proposal.get("risks") or []
    risk_lines = "\n".join(f"- {item}" for item in risks)
    return f"""# Proposal 状态：ready

## 摘要
{summary}

## 可用操作
- `/proposal-detail`：查看完整工作流和应用计划
- `/apply-proposal`：人工确认后应用到本地记录

## 风险提示
{risk_lines}
"""


def render_proposal_detail(proposal: dict[str, Any]) -> str:
    status = str(proposal.get("status") or "unknown")
    if status == "need_info":
        return render_proposal_card(proposal)

    apply_plan = proposal.get("apply_plan") or []
    apply_lines = "\n".join(f"{index}. {item}" for index, item in enumerate(apply_plan, start=1))
    workflow = str(proposal.get("workflow") or "暂无工作流。")
    return f"""{workflow}

## 8. 应用计划
{apply_lines}

## 9. 当前状态
- Proposal ID: {proposal.get("id", "pending")}
- Status: {status}
- Applied at: {proposal.get("applied_at") or "not applied"}
"""


def diagnose_experiment_issue(proposal: dict[str, Any] | None, issue: str) -> str:
    issue = issue.strip()
    if not issue:
        return "用法：/diagnose 这里写观察到的错误或异常现象"
    objective = "未绑定 Proposal"
    if proposal:
        objective = str(proposal.get("objective") or objective)

    lower = issue.lower()
    causes: list[str] = []
    if any(word in lower for word in ("timeout", "超时", "无响应")):
        causes.extend(["设备或端口通信超时", "网络、防火墙或串口参数不匹配"])
    if any(word in lower for word in ("permission", "权限", "拒绝访问")):
        causes.extend(["端口被占用或权限不足", "缺少应用前人工确认或锁定检查"])
    if any(word in lower for word in ("empty", "空", "missing", "缺失")):
        causes.extend(["配置字段缺失", "Proposal 应用时缺少默认值回填"])
    if not causes:
        causes.append("需要更多日志才能判断，先从参数、设备状态、权限和数据采集链路排查")

    cause_lines = "\n".join(f"- {item}" for item in causes)
    return f"""# 诊断建议

## 关联目标
{objective}

## 观察到的问题
{issue}

## 可能原因
{cause_lines}

## 建议动作
1. 查看最近一次 Proposal 详情，确认参数、约束和应用计划是否完整。
2. 检查端口、设备、权限和网络状态，不要直接重试危险动作。
3. 将异常现象补充进下一版 Proposal，必要时回到 need_info 状态。
4. 后续接入日志系统后，把错误码、工具耗时和失败节点结构化记录。"""
