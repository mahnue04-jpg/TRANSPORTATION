"""Execute a bounded public-source assignment through Nova's development code."""
import argparse
import json
from app.core.nova.work_revenue.prospect_research import run_assignment, verify_saved_run

p=argparse.ArgumentParser();p.add_argument('--seeds');p.add_argument('--output',required=True);p.add_argument('--verify',action='store_true');args=p.parse_args()
if args.verify: result=verify_saved_run(args.output)
else:
    m=run_assignment(json.load(open(args.seeds)),args.output)
    result={"source_count":m["source_count"],"failures":m["failures"],"output_rows":m["operations"]["output_rows"],"outreach_sent":m["outreach_sent"],"execution":m["execution"]}
print(json.dumps(result,indent=2))
