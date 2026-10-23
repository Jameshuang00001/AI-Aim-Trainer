"""Read-only comparison of Unity's F9 mouse diagnostic JSONL captures."""
import argparse
import json
from pathlib import Path


def compare(paths):
    phases = {}
    for path in paths:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            phase = phases.setdefault(row['phase'], {'frames': 0, 'eligible_frames': 0,
                'nonzero_axis_frames': 0, 'nonzero_raw_axis_frames': 0,
                'absolute_axis_x': 0., 'absolute_axis_y': 0., 'absolute_yaw': 0., 'absolute_pitch': 0.})
            phase['frames'] += 1
            eligible = (row['focused'] and row['gameplay'] and row['session_active'] and
                        not row['paused'] and row['cursor'] == 'Locked' and row['look_processed'])
            if not eligible:
                continue
            phase['eligible_frames'] += 1
            phase['nonzero_axis_frames'] += bool(row['axis_x'] or row['axis_y'])
            phase['nonzero_raw_axis_frames'] += bool(row['raw_axis_x'] or row['raw_axis_y'])
            for output, source in (('absolute_axis_x','axis_x'), ('absolute_axis_y','axis_y'),
                                   ('absolute_yaw','yaw_delta'), ('absolute_pitch','pitch_delta')):
                phase[output] += abs(row[source])
    physical = phases.get('physical_baseline', {})
    synthetic = phases.get('synthetic_attempt', {})
    finding = 'Insufficient comparable data; collect both phases in focused, locked, active gameplay.'
    if physical.get('nonzero_axis_frames', 0) and synthetic.get('eligible_frames', 0):
        if not synthetic['nonzero_axis_frames'] and not synthetic['nonzero_raw_axis_frames']:
            finding = ('Physical input reaches legacy axes; no synthetic-phase delta reaches those axes. '
                       'Failure is upstream of PlayerController rotation, not camera gain or thresholds. '
                       'Correlate with a posted diagnostic pulse before concluding delivery failed.')
        else:
            finding = ('Synthetic phase contains Unity mouse input. Its source is unproven: physical '
                       'movement can contaminate this phase. This does not verify synthetic input.')
    return {'phases': phases, 'finding': finding,
            'head_lock_enabled': False,
            'limits': 'Labels are manual, not OS event provenance. Raw axes are Unity units, not HID counts. '
                      'No private engine/HID implementation is established by this log.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('logs', type=Path, nargs='+')
    args = parser.parse_args()
    print(json.dumps(compare(args.logs), indent=2))


if __name__ == '__main__':
    main()
