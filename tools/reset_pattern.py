"""Recognize the bench reset's radio gaps before starting provisioning."""
class ResetPattern:
    def __init__(self,now):
        self.last_seen=now
        self.phase='initial_off'
        self.phase_since=now

    def observe(self,now,advertised_at):
        fresh=advertised_at is not None and advertised_at>self.last_seen
        if fresh:self.last_seen=advertised_at
        quiet=now-self.last_seen
        if self.phase=='initial_off' and quiet>=6:
            self.phase='first_on';self.phase_since=now
        elif self.phase=='first_on' and fresh and advertised_at>self.phase_since:
            self.phase='second_off'
        elif self.phase=='second_off' and quiet>=1.5:
            self.phase='second_on';self.phase_since=now
        elif self.phase=='second_on' and fresh and advertised_at>self.phase_since:
            self.phase='final_off'
        elif self.phase=='final_off' and quiet>=1.5:
            self.phase='ready'
        return self.phase=='ready'
