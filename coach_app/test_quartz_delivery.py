import copy
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from coach_app.quartz_delivery_test import Experiment, assess, post_pulse, post_relative_pulse, valid_state


def sample():
    return dict(pid=9900, diagnostic_version=1, frame=10, axis_nonzero_frames=0,
                yaw=0., pitch=0., axis_sum_x=0., axis_sum_y=0., raw_sum_x=0., raw_sum_y=0.,
                gameplay=True, emergency=False)


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.
        self.events, self.posts = [], []
        self.focused = self.trusted = True
        self.backend = SimpleNamespace(pid=9900, focused=lambda:self.focused,
            trusted=lambda:self.trusted, emergency=lambda:False,
            validate_destination=lambda:{'selected_window_id':4101, 'resolved_owner_pid':9900,
                'game_executable':'/game/AI-Aim-Trainer-Test.app/Contents/MacOS/AI-Aim-Trainer',
                'input_events_posted':False}, post=lambda method:self.posts.append(method))
        self.log = SimpleNamespace(write=lambda event:self.events.append(copy.deepcopy(event)))
        self.experiment = Experiment(self.backend,self.log,{},clock=lambda:self.now)

    def tick(self, state=None, keys=None, emergency=False):
        if state is None:
            state=sample(); state['frame']=10+int(self.now*100)
        return self.experiment.tick(state,self.now,keys or {},emergency)

    def ready(self):
        for t in (0.,.1,.2,.35):
            self.now=t
            self.tick()

    def test_launch_never_posts(self):
        self.ready()
        self.assertEqual(self.posts,[])

    def test_key_held_at_launch_needs_release_and_fresh_press(self):
        self.experiment.previous={'pid':True}
        for t in (0.,.1,.2,.35):
            self.now=t; self.tick(keys={'pid':True})
        self.assertEqual(self.posts,[])
        self.tick(keys={})
        self.tick(keys={'pid':True})
        self.assertEqual(self.posts,['pid'])

    def test_single_pulse_hold_does_not_repeat(self):
        self.ready(); self.tick(keys={'pid':True})
        for t in (.4,.5,.6,.8,1.2,2.):
            self.now=t
            after=sample(); after['frame']=1000+int(t*100)
            self.tick(after,{'pid':True})
        self.assertEqual(self.posts,['pid'])

    def test_hid_results_keep_pid_context_but_no_pid_argument(self):
        self.ready(); self.tick(keys={'hid':True})
        self.now=.8
        after=sample(); after.update(frame=1000,axis_nonzero_frames=1,axis_sum_x=.2,axis_sum_y=-.2,
                                     yaw=.4,pitch=.4)
        self.tick(after)
        self.now=1.25; after['frame']=1100; self.tick(after)
        result=self.events[-1]
        self.assertTrue(result['success'])
        self.assertIsNone(result['destination_pid_argument'])
        self.assertEqual(result['resolved_owner_pid'],9900)
        self.assertEqual(result['posted_dx'],2)
        self.assertEqual(result['unity_received_mouse_x'],.2)
        self.assertFalse(result['independently_verified'])

    def test_focus_loss_and_f8_cancel_without_more_posts(self):
        self.ready(); self.focused=False
        self.tick(keys={'pid':True}); self.assertFalse(self.posts)
        self.focused=True; self.ready(); self.tick(keys={'hid':True})
        count=len(self.posts)
        self.assertFalse(self.tick(emergency=True))
        self.assertEqual(len(self.posts),count)
        self.assertEqual(self.events[-1]['outcome'],'emergency_stop')

    def test_missing_accessibility_prevents_post(self):
        self.ready(); self.trusted=False
        self.assertFalse(self.tick(keys={'hid':True}))
        self.assertEqual(self.posts,[])

    def test_physical_baseline_posts_nothing(self):
        self.ready(); self.tick(keys={'physical':True})
        self.assertEqual(self.posts,[])

    def test_stale_or_old_unity_telemetry_prevents_post(self):
        self.ready(); self.now=1.
        self.experiment.tick(sample(),0.,{'pid':True})
        self.assertEqual(self.posts,[])
        old=sample(); old.pop('diagnostic_version')
        self.assertFalse(valid_state(old,9900))
        self.assertFalse(valid_state(sample(),9001))

    def test_zero_axes_fails_without_changing_thresholds(self):
        before=sample(); after=sample(); after['frame']=20
        self.assertFalse(assess(before,after,'pid')['success'])
        after.update(axis_nonzero_frames=1,yaw=.004,pitch=.004)
        self.assertFalse(assess(before,after,'hid')['success'])

    def test_stationary_control_and_phase_traces(self):
        self.ready(); self.tick(keys={'zero':True})
        self.now=.8; self.tick()
        self.now=1.25; self.tick()
        self.assertEqual(self.posts,[])
        result=self.events[-1]
        self.assertEqual(result['outcome'],'quiet_control')
        self.assertTrue(result['controlled_trial_passed'])
        self.assertTrue(result['pre_window']['quiet'])
        self.assertTrue(result['post_window']['quiet'])
        phases={e['phase'] for e in self.events if e['event']=='sample'}
        self.assertEqual(phases,{'pre','pulse','post'})

    def test_post_pulse_movement_rejects_controlled_trial(self):
        self.ready(); self.tick(keys={'pid':True})
        self.now=.8
        after=sample(); after.update(frame=1000,axis_nonzero_frames=1,axis_sum_x=.05,axis_sum_y=-.05,
                                     yaw=.1,pitch=.1)
        self.tick(after)
        self.now=1.25; after.update(frame=1100,axis_nonzero_frames=2,axis_sum_x=.1,axis_sum_y=-.1,
                                  yaw=.2,pitch=.2)
        self.tick(after)
        self.assertTrue(self.events[-1]['success'])
        self.assertFalse(self.events[-1]['controlled_trial_passed'])

    def test_reverse_direction_is_bounded_and_checks_opposite_response(self):
        before=sample(); after=sample()
        after.update(frame=20,axis_nonzero_frames=1,axis_sum_x=-.05,axis_sum_y=.05,yaw=-.1,pitch=-.1)
        result=assess(before,after,'pid',direction=-1)
        self.assertTrue(result['direction_matches'])
        self.assertTrue(result['response_in_existing_bounds'])
        q=MagicMock(); post_pulse(q,'pid',9900,direction=-1)
        self.assertEqual([c.args[2] for c in q.CGEventSetIntegerValueField.call_args_list],[-2,-2])
        with self.assertRaises(ValueError): post_pulse(q,'pid',9900,direction=10)

    def test_dispatch_difference_only_and_no_clicks_or_warp(self):
        for method in ('pid','hid'):
            q=MagicMock()
            post_pulse(q,method,9900)
            self.assertEqual(q.CGEventCreateMouseEvent.call_args.args[1],q.kCGEventMouseMoved)
            self.assertEqual(q.CGEventSetIntegerValueField.call_count,2)
            if method=='pid':
                self.assertEqual(q.CGEventPostToPid.call_args.args[0],9900)
                q.CGEventPost.assert_not_called()
            else:
                self.assertEqual(q.CGEventPost.call_args.args[0],q.kCGHIDEventTap)
                q.CGEventPostToPid.assert_not_called()
            q.CGWarpMouseCursorPosition.assert_not_called()

    def test_single_axis_uses_same_event_and_records_native_return_not_acceptance(self):
        for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2)):
            q = MagicMock()
            q.CGEventGetTimestamp.return_value = 123456789
            q.CGEventGetType.return_value = 5
            q.CGEventGetIntegerValueField.side_effect = [dx, dy]
            result = post_relative_pulse(q, 'pid', 9900, dx, dy)
            self.assertEqual([c.args[2] for c in q.CGEventSetIntegerValueField.call_args_list], [dx, dy])
            q.CGEventPostToPid.assert_called_once_with(9900, q.CGEventCreateMouseEvent.return_value)
            self.assertEqual(result['event_timestamp_ns'], 123456789)
            self.assertEqual((result['event_dx'], result['event_dy']), (dx, dy))
            self.assertTrue(result['post_call_returned'])
            self.assertFalse(result['unity_acceptance_confirmed'])
            q.CGEventPost.assert_not_called()
            q.CGWarpMouseCursorPosition.assert_not_called()


if __name__=='__main__':
    unittest.main()
