"""Map agents to pipeline stages and work out each stage's state."""

STAGES = [
    ("R", "Requirements"), ("Q", "BA analysis"), ("0.8", "Distil"), ("1", "Plan"), ("1-B", "Investigate"),
    ("2", "Plan review"), ("2.7", "ADR"), ("3", "Build"), ("4", "Unit tests"), ("4.5", "QA"),
    ("5", "Code + security review"), ("5.5", "Performance"), ("5.8", "Docs"), ("5.85", "Acceptance"),
    ("6", "Ship"),
]
ORDER = dict((key, index) for index, (key, _label) in enumerate(STAGES))
LABEL = dict(STAGES)

AGENT_STAGE = {
    "requirements-writer": "R",
    "requirement-analyst": "Q", "gap-analysis-agent": "Q", "story-generation-agent": "Q",
    "distiller": "0.8",
    "planner": "1",
    "investigator": "1-B",
    "ceo-reviewer": "2", "eng-reviewer": "2", "design-reviewer": "2",
    "adr-writer": "2.7",
    "implementer": "3",
    "unit-tester": "4",
    "qa-tester": "4.5",
    "code-reviewer": "5", "security-reviewer": "5",
    "perf-tester": "5.5",
    "doc-writer": "5.8",
    "acceptance-verifier": "5.85",
    "ship-pr": "6",
}

_PIPELINE = ["0.8", "1", "1-B", "2", "2.7", "3", "4", "4.5", "5", "5.5", "5.8", "6"]
FLOW_STAGES = {
    "pipeline-all": ["R", "Q", "0.8", "1", "2", "2.7", "3", "4", "4.5", "5", "5.5", "5.8", "5.85", "6"],
    "pipeline": list(_PIPELINE),
    "pipeline-parallel": list(_PIPELINE),
}


def place_agents(agents):
    """Set .stage/.fix/.other on agents given in start order.

    An implementer that starts after a later stage has begun is a fix round of that stage.
    An agent type outside the table goes to the stage reached at that time, marked other.
    """
    reached = None
    for agent in agents:
        mapped = AGENT_STAGE.get(agent.agent_type)
        agent.fix = False
        agent.other = False
        if mapped is None:
            agent.other = True
            agent.stage = reached
        elif mapped == "3" and reached is not None and ORDER[reached] > ORDER["3"]:
            agent.fix = True
            agent.stage = reached
        else:
            agent.stage = mapped
        if agent.stage is not None and (reached is None or ORDER[agent.stage] > ORDER[reached]):
            reached = agent.stage


def stage_list(flow, agents):
    keys = list(FLOW_STAGES.get(flow, FLOW_STAGES["pipeline-all"]))
    types = set(a.agent_type for a in agents)
    if "1-B" in keys and "investigator" not in types:
        keys.remove("1-B")
    if "1" in keys and "investigator" in types and "planner" not in types:
        keys.remove("1")
    for agent in agents:
        if agent.stage and agent.stage not in keys:
            keys.append(agent.stage)
    keys.sort(key=lambda k: ORDER[k])
    return keys


def build_stages(flow, agents, run_status):
    keys = stage_list(flow, agents)
    default = keys[0] if keys else None
    groups = dict((key, []) for key in keys)
    for agent in agents:
        groups.setdefault(agent.stage or default, []).append(agent)
    with_agents = [key for key in keys if groups.get(key)]
    latest = with_agents[-1] if with_agents else None
    out = []
    for key in keys:
        members = groups.get(key, [])
        running = any(a.status == "running" for a in members)
        if members and (running or (key == latest and run_status == "running")):
            state = "in progress"
        elif members:
            state = "done"
        elif any(ORDER[other] > ORDER[key] for other in with_agents):
            state = "skipped"
        else:
            state = "not reached"
        out.append({"key": key, "label": LABEL[key], "state": state, "agents": [a.agent_id for a in members]})
    return out
