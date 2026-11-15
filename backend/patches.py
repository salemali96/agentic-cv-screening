"""Apply changes to an extracted profile from external verification, clarification replies, or
(in evaluation) the hidden truth. The extracted profile itself is never modified, so every change
can be traced and undone."""
from copy import deepcopy


def apply(profile, patches):
    p = deepcopy(profile)
    for pt in patches or []:
        op = pt.get("op")
        sec = pt.get("section")
        ev = pt.get("evidence")
        if op == "set" and sec in p and isinstance(pt.get("index"), int) and 0 <= pt["index"] < len(p[sec]):
            item = p[sec][pt["index"]]
            item[pt["field"]] = pt["value"]
            if ev:
                item.setdefault("evidence", []).append(ev)
            # A value set from a resolved source supersedes conflicts on that field.
            p["conflicts"] = [c for c in p.get("conflicts", []) if not (c.get("item_type") == sec and c.get("item_index") == pt["index"] and c.get("field") == pt["field"] and pt.get("resolves_conflict"))]
        elif op == "add" and sec in p:
            item = deepcopy(pt["item"])
            if ev:
                item.setdefault("evidence", []).append(ev)
            p[sec].append(item)
        elif op == "resolve":
            for c in p.get("conflicts", []):
                if c.get("id") == pt.get("conflict"):
                    s, i, f = c.get("item_type"), c.get("item_index"), c.get("field")
                    if s in p and isinstance(i, int) and i < len(p[s]):
                        p[s][i][f] = pt["value"]
                        if ev:
                            p[s][i].setdefault("evidence", []).append(ev)
            p["conflicts"] = [c for c in p.get("conflicts", []) if c.get("id") != pt.get("conflict")]
        elif op == "conflict":
            c = deepcopy(pt["conflict"])
            c.setdefault("id", f"X{len(p.get('conflicts', [])) + 1}")
            p.setdefault("conflicts", []).append(c)
    return p
