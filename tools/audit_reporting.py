"""Fail-closed audit aggregation and machine-readable reports."""
from collections import Counter
from xml.etree import ElementTree as ET

VALID_STATUSES = {"PASS", "FAIL", "BLOCKED", "NOT_RUN", "NOT_APPLICABLE"}


def aggregate(results, effective):
    by_case = {}
    invalid = []
    for row in results:
        by_case.setdefault(row.get("caseId"), []).append(row)
        if row.get("status") not in VALID_STATUSES:
            invalid.append(row)
    missing = [case for case in effective if not by_case.get(case)]
    fails = [row for row in results if row.get("status") == "FAIL"]
    incomplete = [row for row in results if row.get("caseId") in effective
                  and row.get("status") != "PASS" and row.get("status") != "FAIL"]
    exit_code = 1 if fails or invalid else 2 if missing or incomplete else 0
    return {"exitCode": exit_code, "missing": missing, "fails": fails,
            "incomplete": incomplete, "invalid": invalid,
            "countsByStatus": dict(Counter(row.get("status") for row in results))}


def junit_xml(results):
    root = ET.Element("testsuites", name="G1-INDEPENDENT-AUDIT")
    by_case = {}
    for row in results:
        by_case.setdefault(row["caseId"], []).append(row)
    for case, rows in sorted(by_case.items()):
        suite = ET.SubElement(root, "testsuite", name=case, tests=str(len(rows)),
                             failures=str(sum(r["status"] == "FAIL" for r in rows)),
                             skipped=str(sum(r["status"] not in {"PASS", "FAIL"} for r in rows)))
        for row in rows:
            test = ET.SubElement(suite, "testcase", name=f"{case}::{row['variant']}")
            if row["status"] == "FAIL":
                ET.SubElement(test, "failure", message=row.get("reason") or "assertion failed")
            elif row["status"] != "PASS":
                ET.SubElement(test, "skipped", message=row.get("reason") or row["status"])
    return ET.tostring(root, encoding="unicode", xml_declaration=True)
