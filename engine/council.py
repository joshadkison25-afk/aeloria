"""Deterministic council/intel reports for Axiom.

The council layer is a presentation/intelligence layer over engine truth. It
does not mutate mechanics or choose outcomes; it makes pressure, beliefs,
knowledge, causality, and surfaced events readable.
"""

from __future__ import annotations

from typing import Any

ADVISORS = ("chancellor", "marshal", "steward", "spymaster", "chronicler")


def _item(kind: str, title: str, summary: str, severity: float, faction: str = "", source: str = "") -> dict[str, Any]:
    return {
        "kind": kind,
        "title": title,
        "summary": summary,
        "severity": round(max(0.0, min(20.0, float(severity or 0))), 1),
        "faction": faction,
        "source": source,
    }


def _pressure_items(report: list[dict[str, Any]], domain: str, advisor_kind: str) -> list[dict[str, Any]]:
    rows = []
    for row in report:
        faction = str(row.get("faction", ""))
        domain_row = ((row.get("domains") or {}).get(domain) or {})
        score = float(domain_row.get("score", 0) or 0)
        if score < 15:
            continue
        reasons = list(domain_row.get("reasons") or [])
        summary = ", ".join(reasons[:3]) if reasons else f"{domain} pressure is rising"
        rows.append(_item(advisor_kind, f"{faction}: {domain} pressure", summary, score / 5.0, faction, "pressure_report"))
    return rows


def _war_items(world_state: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for rel in world_state.get("relationships", []) or []:
        if not isinstance(rel, dict) or rel.get("type") != "war":
            continue
        a = str(rel.get("faction_a", ""))
        b = str(rel.get("faction_b", ""))
        ticks = int(rel.get("war_ticks", 0) or 0)
        severity = min(20.0, 8.0 + ticks * 0.6)
        items.append(_item(
            "war",
            f"War: {a} vs {b}",
            f"Open conflict has lasted {ticks} tick{'s' if ticks != 1 else ''}.",
            severity,
            a,
            "relationships",
        ))
    return items


def _knowledge_items(world_state: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for row in world_state.get("faction_knowledge", []) or []:
        if not isinstance(row, dict):
            continue
        faction = str(row.get("faction", ""))
        suspicions = list(row.get("suspicions") or [])
        rumors = list(row.get("rumors") or [])
        false_beliefs = list(row.get("false_beliefs") or [])
        if suspicions:
            items.append(_item(
                "suspicion",
                f"{faction}: suspicions active",
                str(suspicions[0]),
                9 + min(6, len(suspicions)),
                faction,
                "faction_knowledge",
            ))
        if false_beliefs:
            items.append(_item(
                "false_belief",
                f"{faction}: false belief risk",
                str(false_beliefs[0]),
                12 + min(5, len(false_beliefs)),
                faction,
                "faction_knowledge",
            ))
        if rumors:
            items.append(_item(
                "rumor",
                f"{faction}: rumor pressure",
                str(rumors[0]),
                6 + min(5, len(rumors)),
                faction,
                "faction_knowledge",
            ))
    return items


def _causality_items(world_state: dict[str, Any]) -> list[dict[str, Any]]:
    from engine.causality import get_tick_causes, summarize_cause

    items = []
    for cause in get_tick_causes(world_state):
        items.append(_item(
            "cause",
            f"{cause.get('actor', 'Unknown')}: {cause.get('decision', 'action')}",
            summarize_cause(cause),
            float(cause.get("severity", 1) or 1),
            str(cause.get("actor", "")),
            "causality_ledger",
        ))
    return items


def _belief_items(world_state: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for row in world_state.get("faction_beliefs", []) or []:
        if not isinstance(row, dict):
            continue
        faction = str(row.get("faction", ""))
        beliefs = [b for b in row.get("beliefs", []) or [] if isinstance(b, dict)]
        if not beliefs:
            continue
        belief = max(beliefs, key=lambda b: float(b.get("confidence", 0) or 0))
        confidence = float(belief.get("confidence", 0) or 0)
        items.append(_item(
            "belief",
            f"{faction}: dominant belief",
            str(belief.get("claim", "")),
            confidence * 12.0,
            faction,
            "faction_beliefs",
        ))
    return items


def _event_items(world_state: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    primary = world_state.get("primary_event") or {}
    if isinstance(primary, dict) and primary.get("name"):
        items.append(_item(
            "primary_event",
            str(primary.get("name")),
            str(primary.get("summary", "")),
            float(primary.get("severity", 1) or 1),
            "",
            "primary_event",
        ))
    for event in world_state.get("active_events", []) or []:
        if not isinstance(event, dict) or not event.get("name"):
            continue
        items.append(_item(
            "active_event",
            str(event.get("name")),
            str(event.get("summary", "")),
            float(event.get("severity", 1) or 1),
            ", ".join(list(event.get("involved") or [])[:2]),
            "active_events",
        ))
    return items


def _briefing_for_advisor(advisor: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {
            "advisor": advisor,
            "status": "quiet",
            "summary": "No urgent signal exceeds the council threshold.",
            "focus": "",
            "severity": 0.0,
        }
    top = items[0]
    status = "stable"
    sev = float(top.get("severity", 0) or 0)
    if sev >= 14:
        status = "critical"
    elif sev >= 9:
        status = "watch"
    return {
        "advisor": advisor,
        "status": status,
        "summary": str(top.get("summary") or top.get("title") or ""),
        "focus": str(top.get("title") or ""),
        "severity": round(sev, 1),
    }


def _strategic_questions(
    advisor_reports: dict[str, list[dict[str, Any]]],
    watchlist: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []

    top_watch = watchlist[0] if watchlist else {}
    if top_watch:
        faction = str(top_watch.get("faction") or "")
        dom = str(top_watch.get("dominant_pressure") or "pressure")
        questions.append(_item(
            "strategic_question",
            f"What breaks first in {faction}?",
            f"{faction} is the highest-pressure faction; inspect {dom} pressure before intervening.",
            float(top_watch.get("overall", 0) or 0) / 5.0,
            faction,
            "pressure_report",
        ))

    marshal_top = advisor_reports.get("marshal", [])[:1]
    if marshal_top:
        item = marshal_top[0]
        questions.append(_item(
            "strategic_question",
            "Can the current front sustain another tick?",
            str(item.get("summary") or ""),
            float(item.get("severity", 0) or 0),
            str(item.get("faction") or ""),
            "marshal",
        ))

    spymaster_top = advisor_reports.get("spymaster", [])[:1]
    if spymaster_top:
        item = spymaster_top[0]
        questions.append(_item(
            "strategic_question",
            "Who is acting on bad information?",
            str(item.get("summary") or ""),
            float(item.get("severity", 0) or 0),
            str(item.get("faction") or ""),
            "spymaster",
        ))

    chancellor_top = advisor_reports.get("chancellor", [])[:1]
    if chancellor_top:
        item = chancellor_top[0]
        questions.append(_item(
            "strategic_question",
            "Which political tie is most fragile?",
            str(item.get("summary") or ""),
            float(item.get("severity", 0) or 0),
            str(item.get("faction") or ""),
            "chancellor",
        ))

    return sorted(
        questions,
        key=lambda item: (item.get("severity", 0), item.get("title", "")),
        reverse=True,
    )[:6]


def build_council_report(world_state: dict[str, Any]) -> dict[str, Any]:
    """Build the current deterministic council report."""
    pressure_report = world_state.get("pressure_report") or []
    if not isinstance(pressure_report, list):
        pressure_report = []

    advisor_reports = {advisor: [] for advisor in ADVISORS}
    advisor_reports["chancellor"].extend(_pressure_items(pressure_report, "diplomatic", "diplomacy"))
    advisor_reports["chancellor"].extend(_pressure_items(pressure_report, "legitimacy", "legitimacy"))
    advisor_reports["marshal"].extend(_pressure_items(pressure_report, "military", "military"))
    advisor_reports["marshal"].extend(_war_items(world_state))
    advisor_reports["steward"].extend(_pressure_items(pressure_report, "economic", "economy"))
    advisor_reports["steward"].extend(_pressure_items(pressure_report, "stability", "stability"))
    advisor_reports["spymaster"].extend(_pressure_items(pressure_report, "knowledge", "knowledge"))
    advisor_reports["spymaster"].extend(_knowledge_items(world_state))
    advisor_reports["chronicler"].extend(_causality_items(world_state))
    advisor_reports["chronicler"].extend(_belief_items(world_state))
    advisor_reports["chronicler"].extend(_event_items(world_state))

    for advisor in ADVISORS:
        advisor_reports[advisor] = sorted(
            advisor_reports[advisor],
            key=lambda item: (item.get("severity", 0), item.get("title", "")),
            reverse=True,
        )[:8]

    all_items = []
    for items in advisor_reports.values():
        all_items.extend(items)
    top_risks = sorted(
        all_items,
        key=lambda item: (item.get("severity", 0), item.get("title", "")),
        reverse=True,
    )[:10]
    watchlist = [
        row for row in sorted(
            pressure_report,
            key=lambda item: float(item.get("overall", 0) or 0),
            reverse=True,
        )
        if float(row.get("overall", 0) or 0) >= 10
    ][:10]
    advisor_briefings = {
        advisor: _briefing_for_advisor(advisor, advisor_reports[advisor])
        for advisor in ADVISORS
    }
    strategic_questions = _strategic_questions(advisor_reports, watchlist)

    return {
        "tick": int(world_state.get("tick", 0) or 0),
        "world_date": str(world_state.get("world_date", "") or ""),
        "top_risks": top_risks,
        "watchlist": watchlist,
        "advisor_briefings": advisor_briefings,
        "strategic_questions": strategic_questions,
        "advisor_reports": advisor_reports,
    }


def update_council_report(world_state: dict[str, Any]) -> dict[str, Any]:
    report = build_council_report(world_state)
    world_state["council_report"] = report
    return report
