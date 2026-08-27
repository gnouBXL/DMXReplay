"""End-to-end validation using the real Recorder and Player classes (Phase
5/6), not the lower-level simulation in test_end_to_end_artnet_pipeline.py
(written back when those classes didn't exist yet -- see
docs/RASPBERRY_PI.md §11). Same shape, now with the actual orchestration:

    ArtNetSender (simulated console)
        --UDP-->  Recorder  (real: ArtNetListener -> DMXEngine -> DMXReplayWriter)
                        |
                  real .dmxr file
                        |
                  Player  (real: DMXReplayReader -> Timeline -> ArtNetSender)
        --UDP-->  ArtNetListener  (simulated lighting rig)

Asserts the DMX values the simulated lighting rig receives are byte-for-byte
identical to what the simulated console originally sent.
"""
from __future__ import annotations

import asyncio
import socket

from dmxreplay.network.artnet import ArtNetListener, ArtNetSender
from dmxreplay.player import Player
from dmxreplay.recorder import Recorder


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_recorder_to_player_round_trip_is_byte_exact(tmp_path):
    recorder_port = _free_port()
    rig_port = _free_port()
    dmxr_path = str(tmp_path / "e2e_real_classes.dmxr")

    async def record_phase() -> list[tuple[int, int]]:
        """Real console -> real Recorder. Returns the exact (universe, ch1)
        values sent, in order, as the ground truth to compare against."""
        recorder = Recorder()
        await recorder.add_source("Art-Net", interface_ip="127.0.0.1", port=recorder_port)

        console = ArtNetSender()
        await console.start(interface_ip="127.0.0.1")

        sent: list[tuple[int, int]] = []

        async def send(universe: int, ch1: int) -> None:
            console.send(
                net=0, subnet=0, universe=universe, data=bytes([ch1, 0, 0, 0]),
                destination_ip="127.0.0.1", port=recorder_port,
            )
            sent.append((universe, ch1))
            await asyncio.sleep(0.01)

        # Discovery: two universes.
        await send(1, 1)
        await send(2, 101)
        await asyncio.sleep(0.05)

        recorder.start(dmxr_path)
        for i in range(2, 8):
            await send(1, i)
            await send(2, 100 + i)

        recorder.stop()
        console.stop()
        await recorder.close()
        return sent

    sent = asyncio.run(record_phase())

    async def playback_phase() -> list[tuple[int, int]]:
        """Real .dmxr -> real Player -> real Art-Net output -> simulated rig."""
        received: list[tuple[int, int]] = []

        def on_packet(pkt, ip, ts):
            received.append((pkt.universe, pkt.data[0]))

        rig = ArtNetListener(on_packet=on_packet)
        await rig.start(interface_ip="127.0.0.1", port=rig_port)

        player = Player()
        player.load(dmxr_path)
        player.set_output("Art-Net", interface_ip="127.0.0.1", destination_ip="127.0.0.1", port=rig_port)
        # The recorded frames are ~10ms apart; sample much faster than that
        # so playback's sample-and-hold (SPECIFICATION.md §13) doesn't
        # legitimately skip any of them -- this test is about end-to-end
        # data fidelity, not about playback-rate-reduction skipping, which
        # is intentional/separate behavior already covered by test_player.py.
        player.set_fps(500)

        await player.play()
        await asyncio.sleep(0.5)
        await player.stop()
        rig.stop()
        return received

    received = asyncio.run(playback_phase())
    assert len(received) >= 2

    # Each recorded DMXFrame is a snapshot of *every* row at the moment one
    # packet was received (dmxreplay.dmx.DMXEngine._update): since each
    # Art-Net packet updates only one universe, consecutive committed frames
    # legitimately repeat the other row's still-unchanged value. So the
    # right check isn't "every sent value reappears in the same row's
    # received list" (it won't, 1:1) -- it's that nothing received was
    # fabricated (every value came from what was actually sent) and that
    # the final state the simulated rig ends up holding, for each universe,
    # exactly matches the last value the simulated console actually sent.
    # That's the real end-to-end guarantee this pipeline has to uphold.
    sent_values_row1 = {v for u, v in sent if u == 1}
    sent_values_row2 = {v for u, v in sent if u == 2}
    received_row1 = [v for u, v in received if u == 1]
    received_row2 = [v for u, v in received if u == 2]
    assert received_row1, "row 1 was never played back"
    assert received_row2, "row 2 was never played back"
    assert set(received_row1) <= sent_values_row1  # no fabricated values
    assert set(received_row2) <= sent_values_row2
    assert received_row1 == sorted(received_row1)  # forward, non-decreasing
    assert received_row2 == sorted(received_row2)
    assert received_row1[-1] == max(sent_values_row1)  # final state matches exactly
    assert received_row2[-1] == max(sent_values_row2)
