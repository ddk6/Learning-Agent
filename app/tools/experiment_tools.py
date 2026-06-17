from __future__ import annotations

import re
from typing import Any

from app.tools.base import Tool
from app.tools.registry import ToolRegistry


NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
TEMPERATURE_GROUP_PATTERN = re.compile(
    r"((?:-?\d+(?:\.\d+)?\s*[/、,，]\s*)*-?\d+(?:\.\d+)?)\s*(?:摄氏度|℃|°C|度)"
)


def register_experiment_tools(registry: ToolRegistry) -> None:
    def plan_experiment_workflow(arguments: dict[str, Any]) -> str:
        objective = str(arguments.get("objective", "")).strip()
        if not objective:
            return "请提供实验目标，例如：比较 40/50/60 摄氏度下的反应效率。"

        raw_variables = arguments.get("variables", [])
        variables = normalize_variables(raw_variables)
        inferred = infer_variables(objective)
        if inferred:
            variables.extend(item for item in inferred if item not in variables)
        if not variables:
            variables.append("待确认的自变量")

        metric = infer_metric(objective)
        constraints = normalize_text_list(arguments.get("constraints", []))

        return render_workflow(
            objective=objective,
            variables=variables,
            metric=metric,
            constraints=constraints,
        )

    registry.register(
        Tool(
            name="plan_experiment_workflow",
            description=(
                "根据实验目标生成一个实验自动化平台中的垂直工作流 Agent 草案，"
                "包含参数、步骤、风险、失败路径和结果记录模板。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "objective": {
                        "type": "string",
                        "description": "实验目标或用户需求。",
                    },
                    "variables": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选，自变量或实验参数列表。",
                    },
                    "constraints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选，实验约束、设备限制或安全要求。",
                    },
                },
                "required": ["objective"],
                "additionalProperties": False,
            },
            handler=plan_experiment_workflow,
        )
    )


def normalize_variables(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [item.strip() for item in re.split(r"[,，;；/、]", value) if item.strip()]
    return []


def normalize_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def infer_variables(objective: str) -> list[str]:
    temperatures: list[str] = []
    for group in TEMPERATURE_GROUP_PATTERN.findall(objective):
        temperatures.extend(NUMBER_PATTERN.findall(group))
    if temperatures:
        values = ", ".join(f"{value} C" for value in temperatures)
        return [f"温度梯度: {values}"]
    return []


def infer_metric(objective: str) -> str:
    metric_keywords = [
        ("反应效率", "反应效率"),
        ("效率", "效率"),
        ("产率", "产率"),
        ("准确率", "准确率"),
        ("稳定性", "稳定性"),
        ("耗时", "执行耗时"),
    ]
    for keyword, metric in metric_keywords:
        if keyword in objective:
            return metric
    return "主要结果指标"


def render_workflow(
    objective: str,
    variables: list[str],
    metric: str,
    constraints: list[str],
) -> str:
    variable_rows = "\n".join(
        f"| P{index:02d} | {variable} | 待补充 | 由用户目标或 SOP 确认 |"
        for index, variable in enumerate(variables, start=1)
    )
    constraint_lines = "\n".join(f"- {item}" for item in constraints) if constraints else "- 暂无显式约束，执行前需要人工确认设备、安全和样品条件。"

    return f"""# 实验工作流草案

## 1. 当前判断
- 目标：{objective}
- 工作流成熟度：Pilot
- 当前实现：生成可审查的实验计划，不直接控制真实设备。

## 2. 参数表
| 编号 | 参数 | 候选值 | 来源 |
| --- | --- | --- | --- |
{variable_rows}

## 3. 推荐步骤
1. 明确实验目标、样品范围、设备边界和安全约束。
2. 根据参数表生成实验批次，并为每个批次分配唯一编号。
3. 执行前检查设备状态、耗材余量、环境条件和权限。
4. 按批次执行实验，记录每一步的输入参数、开始时间、结束时间和操作者。
5. 采集 `{metric}` 相关结果，标记异常值和失败批次。
6. 汇总不同参数组合下的结果，输出对比结论和下一轮实验建议。

## 4. 失败与降级路径
- 参数缺失：暂停执行，向用户请求补充参数或引用 SOP。
- 设备不可用：跳过自动执行，生成离线实验单和排队任务。
- 采集失败：保留原始输入、错误信息和重试次数，避免覆盖已有结果。
- 结果异常：标记为待复核，不让 Agent 单独给出最终实验结论。

## 5. 风险提示
- 当前计划来自规则化模板，不等同于经过验证的实验 SOP。
- 真实设备控制必须加入权限校验、人工确认、急停机制和审计日志。
- RAG 接入后需要引用来源，避免把检索幻觉写入实验流程。

## 6. 约束
{constraint_lines}

## 7. 结果记录模板
| 批次 ID | 参数组合 | {metric} | 状态 | 异常说明 | 下一步建议 |
| --- | --- | --- | --- | --- | --- |
| B001 | 待执行 | 待记录 | pending | - | 待生成 |
"""
