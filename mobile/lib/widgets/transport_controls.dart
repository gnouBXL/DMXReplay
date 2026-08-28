import 'package:flutter/material.dart';

/// Large, touch-first transport buttons (previous / play-or-pause / stop /
/// next). Each button sends exactly one Control API command
/// (docs/MOBILE_API.md §5) through the callback passed in -- this widget
/// holds no state of its own and never talks to the network directly.
class TransportControls extends StatelessWidget {
  const TransportControls({
    super.key,
    required this.playing,
    required this.enabled,
    required this.onPlay,
    required this.onPause,
    required this.onStop,
    required this.onNext,
    required this.onPrevious,
  });

  final bool playing;
  final bool enabled;
  final VoidCallback onPlay;
  final VoidCallback onPause;
  final VoidCallback onStop;
  final VoidCallback onNext;
  final VoidCallback onPrevious;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceEvenly,
      children: [
        _button(icon: Icons.skip_previous, size: 40, onTap: enabled ? onPrevious : null, tooltip: 'Previous show'),
        _button(icon: Icons.stop, size: 40, onTap: enabled ? onStop : null, tooltip: 'Stop'),
        _button(
          icon: playing ? Icons.pause_circle_filled : Icons.play_circle_filled,
          size: 72,
          onTap: enabled ? (playing ? onPause : onPlay) : null,
          tooltip: playing ? 'Pause' : 'Play',
        ),
        _button(icon: Icons.skip_next, size: 40, onTap: enabled ? onNext : null, tooltip: 'Next show'),
      ],
    );
  }

  Widget _button({
    required IconData icon,
    required double size,
    required VoidCallback? onTap,
    required String tooltip,
  }) {
    return IconButton(
      iconSize: size,
      onPressed: onTap,
      icon: Icon(icon),
      tooltip: tooltip,
    );
  }
}
