"""Deterministic planner evaluation; no external LLM judge is used."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.agent.planner import AnalyticalPlanner


def evaluate_planner(tool_names: set[str], cases_path: Path | None = None) -> dict[str, Any]:
    path = cases_path or Path(__file__).with_name("media_intelligence_cases.json")
    cases = json.loads(path.read_text(encoding="utf-8"))
    planner = AnalyticalPlanner(tool_names)
    correct_domain = correct_tool = evaluated_tools = 0
    failures = []
    memory: dict[str, Any] = {}
    for case in cases:
        if case.get("requires_memory"):
            memory = {"last_domain": "bicomp", "last_entities": {"brands": ["VOLVO", "RENAULT"]}}
        plan = planner.plan(case["question"], memory)
        predicted_tool = plan.steps[0].tool if plan.steps else None
        expected_domain = case["expected_domain"]
        domain_match = expected_domain in plan.domains
        correct_domain += int(domain_match)
        if case.get("expected_tool") is not None:
            evaluated_tools += 1
            tool_match = predicted_tool == case["expected_tool"]
            correct_tool += int(tool_match)
        else:
            tool_match = predicted_tool is None
        if not (domain_match and tool_match):
            failures.append({"question": case["question"], "expected_tool": case.get("expected_tool"), "predicted_tool": predicted_tool, "domains": plan.domains})
    return {"cases": len(cases), "domain_accuracy": correct_domain / len(cases),
            "tool_selection_accuracy": correct_tool / evaluated_tools if evaluated_tools else 1.0, "failures": failures}
