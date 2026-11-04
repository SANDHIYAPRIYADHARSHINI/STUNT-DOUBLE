"""Heuristic risk signals, never a SQL authorization boundary."""

import re

from app.models import RiskReport


def analyze_risk(
    sql: list[str],
    affected_rows: int,
    disagreement: bool = False,
    instructions: str = "",
    max_affected_rows: int = 100,
) -> RiskReport:
    """Score SQL, blast radius, disagreement and suspicious task instructions."""
    warnings: list[str] = []
    flags: list[str] = []
    score = 0
    for statement in sorted(set(sql)):
        normalized = re.sub(r"/\*.*?\*/|--[^\n]*", " ", statement, flags=re.S).upper()
        for part in normalized.split(";"):
            if re.search(r"\b(DROP|TRUNCATE|ALTER)\b", part) or (
                re.search(r"\b(DELETE|UPDATE)\b", part) and not re.search(r"\bWHERE\b", part)
            ):
                score = 100
                warnings.append("Destructive or unbounded SQL detected")
            elif re.search(r"\bDELETE\b", part):
                score += 25
                warnings.append("Deletion proposed")
    if affected_rows > max_affected_rows:
        score += 50
        warnings.append("Affected rows exceed the configured limit")
    elif affected_rows:
        score += 10
    if disagreement:
        score += 30
        warnings.append("Agents disagree on proposed changes")
    for pattern in (
        r"ignore.*instructions",
        r"bypass.*approval",
        r"system\s+prompt",
        r"exfiltrat",
        r"disable.*safety",
    ):
        if re.search(pattern, instructions, re.I | re.S):
            flags.append(pattern)
    if flags:
        score += 60
        warnings.append("Suspected prompt injection; manual investigation required")
    score = min(100, score)
    level = (
        "critical" if score >= 80 else "high" if score >= 50 else "medium" if score >= 20 else "low"
    )
    return RiskReport(
        score=score,
        level=level,
        warnings=sorted(set(warnings)),
        blast_radius=affected_rows,
        prompt_injection_flags=flags,
    )
