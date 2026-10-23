import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from reset_pattern import ResetPattern

class ResetPatternTests(unittest.TestCase):
    def test_arms_during_last_off_before_final_on(self):
        pattern=ResetPattern(0)
        for now,seen in ((1,1),(7,1),(11,11),(12,12),(13,13),(15,13),(19,19),(20,20),(21,21)):
            self.assertFalse(pattern.observe(now,seen))
        self.assertTrue(pattern.observe(23,21))
        self.assertEqual(pattern.phase,'ready')

    def test_powered_advertising_does_not_start_pairing(self):
        pattern=ResetPattern(0)
        for now in range(1,120):self.assertFalse(pattern.observe(now,now))
        self.assertEqual(pattern.phase,'initial_off')

    def test_one_normal_power_cycle_is_not_the_reset_sequence(self):
        pattern=ResetPattern(0)
        self.assertFalse(pattern.observe(7,None))
        for now in range(11,120):self.assertFalse(pattern.observe(now,now))
        self.assertEqual(pattern.phase,'second_off')
