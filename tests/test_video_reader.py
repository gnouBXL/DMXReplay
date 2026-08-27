"""Real tests for ExternalVideoReader: encodes a genuine H.264/MP4 test
video via PyAV (each frame's pixel value = frame index, at a known fps),
then verifies seek/sample-and-hold frame selection against it -- no display
needed, since correctness here is about "which frame got selected," not
about rendering."""
from __future__ import annotations

from fractions import Fraction

import av
import pytest

from dmxreplay.video import ExternalVideoReader, NullVideoSink, PPMFileVideoSink

FPS = 25
FRAME_COUNT = 50  # 2 seconds


def _make_test_video(path: str, width: int = 64, height: int = 48) -> None:
    container = av.open(path, mode="w")
    stream = container.add_stream("libx264", rate=FPS)
    stream.width, stream.height = width, height
    stream.pix_fmt = "yuv420p"
    stream.codec_context.time_base = Fraction(1, 1000)
    # crf=0: near-lossless. Confirmed empirically (not assumed) that x264's
    # *default* CRF quantizes away this test's subtle 1-gray-level-per-frame
    # steps almost entirely (frame values landed many frames "behind" where
    # they should be) -- an expected property of a lossy lookahead encoder
    # optimizing for perceptual similarity, not a DMXReplay bug, but it
    # would have made this test's own assertions meaningless without this.
    stream.codec_context.options = {"crf": "0", "preset": "ultrafast"}
    # color_range=2 (JPEG/full range): also confirmed empirically. Without
    # explicitly signaling this, decoded frames default to "unspecified",
    # which swscale's YUV->RGB conversion treats as MPEG/limited range
    # (Y=16..235) -- silently clipping/compressing this test's raw 0..255 Y
    # values (e.g. Y=5 decoded as R=0, since limited range floors at 16).
    # This is specific to synthetic full-range test content asserting exact
    # pixel values; ExternalVideoReader itself must NOT force color_range
    # (real-world video is normally genuinely limited-range, and forcing it
    # would corrupt real colors) -- the fix belongs here, in how the test
    # video is produced, not in the reader.
    stream.codec_context.color_range = 2

    for i in range(FRAME_COUNT):
        frame = av.VideoFrame(width, height, format="yuv420p")
        # Y (luma) plane carries the frame index; U/V (chroma) MUST be the
        # neutral 128, not also `i` -- setting chroma equal to luma produces
        # an invalid color that clips hard in YUV->RGB conversion (verified
        # empirically: R clipped to 0 for nearly every frame index, making
        # every "which frame is this" check trivially/wrongly pass or fail
        # regardless of whether frame selection was actually correct).
        y_plane, u_plane, v_plane = frame.planes
        y_plane.update(bytes([i % 256]) * y_plane.buffer_size)
        u_plane.update(bytes([128]) * u_plane.buffer_size)
        v_plane.update(bytes([128]) * v_plane.buffer_size)
        frame.pts = round(i * 1000 / FPS)  # ms
        frame.time_base = Fraction(1, 1000)
        for p in stream.encode(frame):
            container.mux(p)
    for p in stream.encode():
        container.mux(p)
    container.close()


@pytest.fixture(scope="module")
def test_video(tmp_path_factory) -> str:
    path = str(tmp_path_factory.mktemp("video") / "test.mp4")
    _make_test_video(path)
    return path


def test_duration_matches_encoded_content(test_video):
    with ExternalVideoReader(test_video) as reader:
        # ~2s of content (50 frames @ 25fps); allow a little slack for
        # container-level duration rounding.
        assert 1_900_000_000 <= reader.duration_ns <= 2_100_000_000
        assert reader.width == 64
        assert reader.height == 48


def test_frame_at_start_is_frame_0(test_video):
    with ExternalVideoReader(test_video) as reader:
        frame = reader.frame_at(0)
        assert frame is not None
        assert frame.rgb_bytes[0] == 0  # frame index 0 -> pixel value 0


def test_frame_at_exact_timestamp_matches_that_frame(test_video):
    with ExternalVideoReader(test_video) as reader:
        # Frame 25 lands at 25 * (1000/25) = 1000ms = 1_000_000_000 ns.
        frame = reader.frame_at(1_000_000_000)
        assert frame is not None
        assert frame.timestamp_ns == 1_000_000_000
        assert frame.rgb_bytes[0] == 25


def test_frame_at_between_timestamps_holds_the_earlier_frame(test_video):
    with ExternalVideoReader(test_video) as reader:
        # Halfway between frame 10 (400ms) and frame 11 (440ms): sample-
        # and-hold must return frame 10, not round to the nearer one.
        frame = reader.frame_at(420_000_000)
        assert frame.rgb_bytes[0] == 10


def test_forward_scan_does_not_require_reseeking(test_video):
    """Requesting monotonically increasing positions should just continue
    decoding forward -- verified indirectly by confirming the sequence of
    frames returned is correct and monotonic, exercising the no-reseek path
    in ExternalVideoReader.frame_at()."""
    with ExternalVideoReader(test_video) as reader:
        values = []
        for i in range(0, 50, 5):
            frame = reader.frame_at(round(i * 1000 / FPS) * 1_000_000)
            values.append(frame.rgb_bytes[0])
        assert values == sorted(values)
        assert values[0] == 0
        assert values[-1] == 45


def test_backward_seek_reseeks_correctly(test_video):
    with ExternalVideoReader(test_video) as reader:
        forward = reader.frame_at(1_500_000_000)
        assert forward.rgb_bytes[0] == 37  # frame ~37 at 1.5s (37*40ms=1480ms)
        backward = reader.frame_at(200_000_000)  # jump back to 0.2s (frame 5)
        assert backward.rgb_bytes[0] == 5
        forward_again = reader.frame_at(1_000_000_000)
        assert forward_again.rgb_bytes[0] == 25


def test_frame_at_before_start_returns_none(test_video):
    with ExternalVideoReader(test_video) as reader:
        assert reader.frame_at(-1) is None


def test_null_video_sink_never_raises(test_video):
    with ExternalVideoReader(test_video) as reader:
        frame = reader.frame_at(0)
    sink = NullVideoSink()
    sink.present(frame)  # must not raise


def test_ppm_file_sink_writes_real_readable_images(test_video, tmp_path):
    out_dir = str(tmp_path / "frames")
    sink = PPMFileVideoSink(out_dir)
    with ExternalVideoReader(test_video) as reader:
        for i in range(3):
            frame = reader.frame_at(i * 400_000_000)
            sink.present(frame)

    assert sink.frame_count == 3
    written = sorted((tmp_path / "frames").glob("*.ppm"))
    assert len(written) == 3
    header = written[0].read_bytes()[:20]
    assert header.startswith(b"P6\n64 48\n255\n")
