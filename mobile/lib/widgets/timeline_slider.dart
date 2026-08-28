import 'package:flutter/material.dart';

/// The show timeline: a seek bar plus elapsed/total time labels. This
/// widget only ever *displays* a position and, on user drag-release, asks
/// [onSeekEnd] to send a single `SEEK` command (docs/MOBILE_API.md §5) --
/// it never ticks time forward locally between status pushes, since the
/// device's own WebSocket broadcast (roughly 1/s) is the single source of
/// truth for playback position (docs/MOBILE_API.md §6, §2's warning
/// against building anything that depends on tighter timing than that).
class TimelineSlider extends StatefulWidget {
  const TimelineSlider({
    super.key,
    required this.position,
    required this.duration,
    required this.enabled,
    required this.onSeekEnd,
  });

  final Duration position;
  final Duration duration;
  final bool enabled;
  final ValueChanged<Duration> onSeekEnd;

  @override
  State<TimelineSlider> createState() => _TimelineSliderState();
}

class _TimelineSliderState extends State<TimelineSlider> {
  double? _dragValue;

  @override
  Widget build(BuildContext context) {
    final totalMs = widget.duration.inMilliseconds.toDouble();
    final max = totalMs > 0 ? totalMs : 1.0;
    final current = (_dragValue ?? widget.position.inMilliseconds.toDouble()).clamp(0.0, max);

    return Column(
      children: [
        Slider(
          value: current,
          max: max,
          onChanged: widget.enabled && totalMs > 0 ? (value) => setState(() => _dragValue = value) : null,
          onChangeEnd: widget.enabled && totalMs > 0
              ? (value) {
                  widget.onSeekEnd(Duration(milliseconds: value.round()));
                  setState(() => _dragValue = null);
                }
              : null,
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(_format(Duration(milliseconds: current.round()))),
              Text(_format(widget.duration)),
            ],
          ),
        ),
      ],
    );
  }

  String _format(Duration d) {
    String two(int n) => n.toString().padLeft(2, '0');
    final hours = d.inHours;
    final minutes = d.inMinutes.remainder(60);
    final seconds = d.inSeconds.remainder(60);
    return hours > 0 ? '$hours:${two(minutes)}:${two(seconds)}' : '${two(minutes)}:${two(seconds)}';
  }
}
