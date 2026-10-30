"""Check an API-format graph against a running ComfyUI's /object_info WITHOUT queueing it (partner nodes cost money).
Every node class exists, every input name is known, combo values are allowed, links point at real outputs of a
compatible type, and required inputs are set.  python3 tools/check_graph.py workflows/urban-cuts-api.json [--url http://127.0.0.1:8197]"""
import argparse, json, sys, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("graph"); ap.add_argument("--url", default="http://127.0.0.1:8197")
a = ap.parse_args()
g = json.load(open(a.graph))
info = json.load(urllib.request.urlopen(f"{a.url}/object_info"))
errs = []


def spec_of(cls, name):
    inp = info[cls]["input"]
    for sect in ("required", "optional"):
        if name in inp.get(sect, {}):
            return inp[sect][name]
    if "." in name:   # DynamicCombo sub-input such as SaveVideo's format.codec
        return ["*", {}]
    return None


def type_name(t):
    return "COMBO" if isinstance(t, list) else t


for nid, n in g.items():
    cls = n["class_type"]
    if cls not in info:
        errs.append(f"{nid}: unknown node {cls}"); continue
    for name, val in n["inputs"].items():
        spec = spec_of(cls, name)
        if spec is None:
            errs.append(f"{nid} {cls}: unknown input {name}"); continue
        want = spec[0]
        if isinstance(val, list) and len(val) == 2 and isinstance(val[0], str):
            src = g.get(val[0])
            if src is None:
                errs.append(f"{nid} {cls}.{name}: link to missing node {val[0]}"); continue
            outs = info[src["class_type"]]["output"]
            if val[1] >= len(outs):
                errs.append(f"{nid} {cls}.{name}: output {val[1]} out of range"); continue
            got = type_name(outs[val[1]])
            if isinstance(outs[val[1]], list) and isinstance(want, list):
                if not set(outs[val[1]]) <= set(want):
                    errs.append(f"{nid} {cls}.{name}: linked combo values {outs[val[1]]} not all allowed")
            elif isinstance(outs[val[1]], list) and want == "COMBO":
                opts = spec[1].get("options", [])
                if opts and not set(outs[val[1]]) <= set(opts):
                    errs.append(f"{nid} {cls}.{name}: linked combo values {outs[val[1]]} not in {opts}")
            elif "*" not in (got, type_name(want)) and got not in str(type_name(want)).split(","):
                errs.append(f"{nid} {cls}.{name}: type {got} -> {type_name(want)}")
        elif isinstance(want, list):
            if val not in want:
                errs.append(f"{nid} {cls}.{name}: {val!r} not in {want}")
        elif want == "COMBO":
            opts = spec[1].get("options", [])
            if opts and val not in opts:
                errs.append(f"{nid} {cls}.{name}: {val!r} not in {opts}")
    for name in info[cls]["input"].get("required", {}):
        if name not in n["inputs"]:
            errs.append(f"{nid} {cls}: required input {name} missing")
print(f"{len(g)} nodes checked against {a.url}: {'OK' if not errs else str(len(errs)) + ' problems'}")
for e in errs:
    print("  ", e)
sys.exit(1 if errs else 0)
