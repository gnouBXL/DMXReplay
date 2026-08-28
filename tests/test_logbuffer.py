"""Real logging tests for dmxreplay.control.logbuffer.RingBufferLogHandler
-- attaches to a real logger and emits real records, no mocking."""
from __future__ import annotations

import logging

from dmxreplay.control.logbuffer import RingBufferLogHandler


def test_captures_emitted_records():
    handler = RingBufferLogHandler()
    logger = logging.getLogger("dmxreplay.test.logbuffer")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info("hello world")
    finally:
        logger.removeHandler(handler)

    lines = handler.lines()
    assert len(lines) == 1
    assert "hello world" in lines[0]
    assert "INFO" in lines[0]


def test_ring_buffer_caps_at_capacity():
    handler = RingBufferLogHandler(capacity=3)
    logger = logging.getLogger("dmxreplay.test.logbuffer.cap")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        for i in range(10):
            logger.info("message %d", i)
    finally:
        logger.removeHandler(handler)

    lines = handler.lines()
    assert len(lines) == 3
    assert "message 9" in lines[-1]
    assert "message 7" in lines[0]  # oldest 7 evicted, only the last 3 remain
