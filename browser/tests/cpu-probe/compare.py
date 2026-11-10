import json, sys
runs = {f.rsplit(".json",1)[0]: json.load(open(f)) for f in sys.argv[1:]}
keys = sorted(set().union(*runs.values()))
names = list(runs)
print("runs:", names)
same = []
for k in keys:
    vals = [str(runs[n].get(k, "-")) for n in names]
    if len(set(vals)) == 1: same.append(k); continue
    groups = {}
    for n, v in zip(names, vals): groups.setdefault(v, []).append(n)
    print(f"{k}: " + " | ".join(f"{'+'.join(g)}={v[:24]}" for v, g in groups.items()))
print(f"\nidentical on all: {len(same)} keys")
