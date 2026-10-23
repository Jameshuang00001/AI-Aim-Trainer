"""Read-only Quartz JSONL analysis. Never imports/post events or enables assist."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
from statistics import mean, median


def analyze(paths):
    trials=defaultdict(dict)
    events=Counter()
    for path in paths:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            if not line.strip(): continue
            row=json.loads(line); events[row['event']]+=1
            if not row.get('test_id'): continue
            if row['event']=='sample':
                trials[row['test_id']].setdefault('samples',[]).append(row)
            else:
                trials[row['test_id']][row['event']]=row
    details=[]
    for trial in trials.values():
        result=trial.get('result')
        if not result: continue
        posted=trial.get('posted',trial.get('baseline_started',{}))
        samples=sorted(trial.get('samples',[]),key=lambda x:x['receive_monotonic'])
        latency=None
        baseline=posted.get('baseline_state')
        start=posted.get('post_start_monotonic'); end=posted.get('post_end_monotonic')
        if baseline and start is not None and end is not None:
            quiet=posted['baseline_receive_monotonic']
            for row in samples:
                if row['state']['frame'] <= baseline['frame']: continue
                if row['state']['axis_nonzero_frames'] > baseline['axis_nonzero_frames']:
                    latency=[(quiet-end)*1000,(row['receive_monotonic']-start)*1000]
                    break
                quiet=row['receive_monotonic']
        details.append({'test_id':result['test_id'],'method':result['method'],
            'direction':result.get('direction',1),
            'dx':result.get('unity_received_mouse_x'),'dy':result.get('unity_received_mouse_y'),
            'yaw':result.get('camera_yaw_change'),'pitch':result.get('camera_pitch_change'),
            'nonzero_frames':result.get('unity_nonzero_mouse_frames'),
            'success':result.get('success'), 'controlled_trial_passed':result.get('controlled_trial_passed'),
            'outcome':result.get('outcome'),
            'pre':result.get('pre_window'),'post':result.get('post_window'),
            'has_phase_trace':bool(samples), 'arrival_latency_bracket_ms':latency,
            'assessment_delay_ms':(datetime.fromisoformat(result['timestamp'])-
                datetime.fromisoformat(posted['timestamp'])).total_seconds()*1000 if posted else None})
    methods={}
    for method in sorted({r['method'] for r in details}):
        rows=[r for r in details if r['method']==method]
        values=[r for r in rows if all(type(r[k]) in (int,float) for k in ('dx','dy','yaw','pitch'))]
        methods[method]={'trials':len(rows),'observed_successes':sum(bool(r['success']) for r in rows) if method!='zero' else 0,
            'successful_trials':sum(bool(r['success']) for r in rows),
            'quiet_control_passes':sum(r['outcome']=='quiet_control' for r in rows),
            'direction_counts':dict(Counter(str(r['direction']) for r in rows)),
            'trials_with_phase_trace':sum(r['has_phase_trace'] for r in rows),
            'controlled_passes':sum(r['controlled_trial_passed'] is True for r in rows),
            'responses_with_multiple_nonzero_frames':sum((r['nonzero_frames'] or 0)>1 for r in rows),
            'expected_sign_responses':sum(r['dx']*r['direction']>0 and r['dy']*r['direction']<0 and
                                         r['yaw']*r['direction']>0 and r['pitch']*r['direction']>0 for r in values),
            'mean':{k:mean(r[k] for r in values) for k in ('dx','dy','yaw','pitch')} if values else {},
            'median':{k:median(r[k] for r in values) for k in ('dx','dy','yaw','pitch')} if values else {}}
    return {'events':dict(events),'methods':methods,'trials':details,
        'independently_verified_methods':[], 'head_lock_enabled':False,
        'conclusion':'Observed post-window responses are correlation evidence, not event provenance. '
            'Old records lack pre/post traces and no-event controls. New controlled trials '
            'and direction reversal strengthen evidence but cannot automatically prove provenance.',
        'timing_limit':'Assessment delay is not latency. Arrival brackets use local packet reception, '
            'not hardware timestamps; transport delay and physical contamination remain possible.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('logs',nargs='*',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    paths=args.logs or sorted((Path.home()/'Library/Logs/AI-Aim-Trainer/quartz_diagnostics').glob('*.jsonl'))
    report=json.dumps(analyze(paths),indent=2)
    if args.output:
        args.output.write_text(report+'\n',encoding='utf-8')
    print(report)


if __name__=='__main__': main()
