"""Absolute request deadline for the serial macOS/Linux experiment CLI."""

import signal

from .generation import ProviderFailure


class DeadlineLLM:
    def __init__(self, llm, seconds=60):
        if not 0 < seconds <= 60:
            raise ValueError("deadline_must_be_positive_and_at_most_60_seconds")
        self.llm, self.seconds = llm, seconds

    def generate(self, messages, **kwargs):
        if not hasattr(signal, "setitimer"):
            raise ProviderFailure("absolute_deadline_platform_unsupported")
        if signal.getitimer(signal.ITIMER_REAL)[0]:
            raise ProviderFailure("absolute_deadline_nested_timer_unsupported")
        previous = signal.getsignal(signal.SIGALRM)

        def expired(*_):
            # PaidClient's reservation intentionally remains held: billing is unknown.
            raise ProviderFailure("absolute_deadline_billing_unknown")

        signal.signal(
            signal.SIGALRM, expired
        )  # Serial CLI/main thread only; fails before billing otherwise.
        signal.setitimer(signal.ITIMER_REAL, self.seconds)
        try:
            return self.llm.generate(messages, **kwargs)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
