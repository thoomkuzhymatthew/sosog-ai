#!/usr/bin/env python3
"""Compatibility CLI for the airline flight-change vertical adapter."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

def parse_args():
    p=argparse.ArgumentParser()
    for name in ("repo-root","tau-root","proposal","output","report"): p.add_argument(f"--{name}",required=True,type=Path)
    return p.parse_args()

def render_report(output):
    s=output["summary"]
    lines=["# Airline Flight-change Repair: Independent Final Report","",f"Decision: **{s['decision']}**","",
           f"- Visible repair regressions: {s['repair_passed']}/{s['repair_total']}",f"- Locked normal variations: {s['locked_normal_passed']}/{s['locked_normal_total']}",
           f"- Locked unsafe variations: {s['locked_unsafe_passed']}/{s['locked_unsafe_total']}",f"- Wrong writes: {s['wrong_writes']}",f"- Model calls: {s['model_calls']}","","## Failures",""]
    failures=[r for r in output["repair_results"]+output["locked_results"] if not r["passed"]]
    lines += [f"- `{r['case_id']}`: status={r['status']}, writes={r['writes']}, reason={r['reason']}" for r in failures] or ["No failures."]
    lines += ["","## Cost interpretation","","The repaired executor itself made no model calls. Historical cost is potential model-cost avoidance only after independent human safety review.",""]
    return "\n".join(lines)

def main():
    a=parse_args(); sys.path.insert(0,str(a.repo_root.resolve()))
    from crystallized.airline.flight_change_adapter import FlightChangeAdapter, legacy_output
    from sosog.repair.contracts import CandidateReference, EvaluationTier
    proposal=a.proposal.resolve(); candidate=CandidateReference.from_content(proposal.read_bytes(),location=str(proposal)); adapter=FlightChangeAdapter(tau_root=a.tau_root.resolve())
    output=legacy_output(adapter,candidate,adapter.evaluate(candidate,EvaluationTier.VISIBLE),adapter.evaluate(candidate,EvaluationTier.LOCKED))
    a.output.parent.mkdir(parents=True,exist_ok=True); a.report.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(output,indent=2,sort_keys=True)+"\n"); a.report.write_text(render_report(output)); print(json.dumps(output["summary"],indent=2,sort_keys=True)); return 0

if __name__ == "__main__": raise SystemExit(main())
