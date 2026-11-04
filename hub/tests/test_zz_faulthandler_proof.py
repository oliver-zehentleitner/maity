"""DEMO ONLY (tsk-80xk3tbhe2hc), never merged: a test that runs past faulthandler_timeout."""

import time


def test_sleeps_past_the_faulthandler_timeout():
    time.sleep(330)
