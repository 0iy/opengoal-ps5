#!/bin/bash
# one game, several flag sets, each a full perfround; prints the trace summary of each
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
G=$1; SECS=$2; shift 2
while [ $# -gt 0 ]; do
  L=$1; F=$2; shift 2
  python -u perfround.py ${G}_${L} $G $SECS trace $F > /dev/null 2>&1
  f=$(ls perf_runs/${G}_${L}.trace_*.bin 2>/dev/null | head -1)
  echo "##### ${G}_${L}  flags: $F"
  grep "^fps series" perf_runs/${G}_${L}.summary.txt | awk '{n=NF; s=0; c=0; for(i=n-30;i<=n;i++){if(i>3){s+=$i;c++}} printf "last-30 avg fps %.1f\n", s/c}'
  [ -n "$f" ] && timeout 150 python trace2json.py $f - 2>&1 | grep -E "^frames|submit_lock|backpressure|batch submit|wait batch|wait async|wait flip|per draw|draw \(glfix|driver draw_vbo"
done
echo SUITEDONE
