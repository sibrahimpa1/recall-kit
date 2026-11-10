"""Turn pytest JUnit XML into the markdown test matrix used in the README and CI summary."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

GROUPS = {
    "test_continuity": "Continuity (fresh sessions)",
    "test_failure_modes": "Failure modes",
    "test_http_auth": "HTTP + scoped tokens",
    "test_ops": "Backups / brief / ICS / tokens",
    "test_llm_eval": "LLM-in-the-loop",
}


def main(paths: list[str]) -> None:
    rows, totals = [], {"passed": 0, "failed": 0, "skipped": 0}
    for path in paths:
        for case in ET.parse(path).getroot().iter("testcase"):
            module = case.get("classname", "").split(".")[-1]
            if case.find("failure") is not None or case.find("error") is not None:
                status = "failed"
            elif case.find("skipped") is not None:
                status = "skipped"
            else:
                status = "passed"
            totals[status] += 1
            icon = {"passed": "✅ pass", "failed": "❌ FAIL", "skipped": "⏭ skipped"}[status]
            rows.append((GROUPS.get(module, module), case.get("name", ""), icon, float(case.get("time", 0))))
    print("| Area | Test | Result | Time |\n|---|---|---|---|")
    for group, name, icon, secs in rows:
        print(f"| {group} | `{name}` | {icon} | {secs:.1f}s |")
    print(f"\n**{totals['passed']} passed, {totals['failed']} failed, {totals['skipped']} skipped**")


if __name__ == "__main__":
    main(sys.argv[1:])
