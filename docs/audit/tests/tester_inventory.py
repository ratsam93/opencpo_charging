import sys, re, glob, os, collections, inspect
sys.path.insert(0, sys.argv[1])
os.chdir(sys.argv[1])
import runner
from tests.base import OCPPTest
reg16 = runner.V16_TEST_CATEGORIES
reg201 = runner.V201_TEST_CATEGORIES
def summarize(reg, label):
    tot = 0
    seen = []
    for cat, classes in reg.items():
        print(f"{label} {cat}: {len(classes)}")
        tot += len(classes)
        seen += classes
    print(f"{label} TOTAL registered entries: {tot}, unique: {len(set(seen))}")
    return seen
r16 = summarize(reg16, "v16")
r201 = summarize(reg201, "v201")
# all classes defined in tests/
defined = {}
for f in sorted(glob.glob(os.path.join(sys.argv[1], "tests", "**", "*.py"), recursive=True)):
    src = open(f).read()
    for m in re.finditer(r"^class\s+(\w+)\((\w+)\)", src, re.M):
        if m.group(2) == "OCPPTest" or True:
            defined.setdefault(m.group(1), []).append((os.path.relpath(f, sys.argv[1]), m.group(2)))
ocpp = {k: v for k, v in defined.items() if any(b == "OCPPTest" for _, b in v)}
print("classes with base OCPPTest (grep):", sum(len(v) for v in ocpp.values()))
print("  by dir:", collections.Counter(p.split('/')[1] for v in ocpp.values() for p, _ in v))
reg_names = {c.__name__ for c in r16 + r201}
for name, locs in sorted(ocpp.items()):
    for p, b in locs:
        if name not in reg_names:
            print("NOT REGISTERED:", p, name)
# registered classes not defined via OCPPTest
for c in r16 + r201:
    if not issubclass(c, OCPPTest):
        print("registered but not OCPPTest subclass:", c)
# which registered classes also exist in v16 & v201 groups and category per dir
import itertools
print("unique registered v16:", len(set(r16)), "v201:", len(set(r201)))
for label, reg in (("v16", reg16), ("v201", reg201)):
    for cat, classes in reg.items():
        for c in classes:
            pass
