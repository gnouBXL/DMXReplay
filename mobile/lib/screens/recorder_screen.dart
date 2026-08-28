import 'package:flutter/material.dart';

import '../state/connection_controller.dart';
import '../state/recorder_controller.dart';
import '../widgets/connection_status_banner.dart';
import '../widgets/error_banner.dart';

/// Recording control: start/stop and a live status readout (duration,
/// frame/packet counts) -- the brief's "Recording: Record start, Record
/// stop" requirement. Only present/usable when the connected device was
/// started with `--enable-recorder` (docs/MOBILE_API.md §5's "Requires
/// Recorder" column); this screen surfaces that as a plain error message
/// via [RecorderController] rather than hiding itself, so a user
/// connecting to a player-only device gets a clear reason, not a missing
/// tab they have to guess about.
class RecorderScreen extends StatefulWidget {
  const RecorderScreen({super.key, required this.connection, required this.recorder});

  final ConnectionController connection;
  final RecorderController recorder;

  @override
  State<RecorderScreen> createState() => _RecorderScreenState();
}

class _RecorderScreenState extends State<RecorderScreen> {
  final _filenameController = TextEditingController(text: 'recording.dmxr');

  @override
  void dispose() {
    _filenameController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Recording')),
      body: SafeArea(
        child: Column(
          children: [
            ConnectionStatusBanner(connection: widget.connection),
            Expanded(
              child: ListenableBuilder(
                listenable: widget.recorder,
                builder: (context, _) {
                  final status = widget.recorder.status;
                  return ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      ErrorBanner(message: widget.recorder.lastError),
                      const SizedBox(height: 8),
                      Center(
                        child: Icon(
                          status.recording ? Icons.fiber_manual_record : Icons.fiber_manual_record_outlined,
                          color: status.recording ? Colors.red : Colors.grey,
                          size: 64,
                        ),
                      ),
                      Center(
                        child: Text(
                          status.recording ? 'Recording' : 'Not recording',
                          style: Theme.of(context).textTheme.headlineSmall,
                        ),
                      ),
                      const SizedBox(height: 24),
                      if (status.recording) ...[
                        _statRow('Duration', '${status.durationSeconds.toStringAsFixed(1)} s'),
                        _statRow('Universes', status.universeCount.toString()),
                        _statRow('Frames captured', status.frameCount.toString()),
                        _statRow('Packets received', status.totalPackets.toString()),
                        _statRow('Malformed packets', status.malformedPackets.toString()),
                        if (status.fileSizeBytes != null)
                          _statRow('File size', _formatBytes(status.fileSizeBytes!)),
                        const SizedBox(height: 24),
                        FilledButton.icon(
                          onPressed: widget.recorder.busy ? null : widget.recorder.stop,
                          style: FilledButton.styleFrom(backgroundColor: Colors.red),
                          icon: const Icon(Icons.stop),
                          label: const Text('Stop recording'),
                        ),
                      ] else ...[
                        TextField(
                          controller: _filenameController,
                          decoration: const InputDecoration(
                            labelText: 'File name',
                            helperText: 'Saved to the device\'s show library, e.g. myshow.dmxr',
                          ),
                        ),
                        const SizedBox(height: 16),
                        FilledButton.icon(
                          onPressed: widget.recorder.busy
                              ? null
                              : () => widget.recorder.start(_filenameController.text.trim()),
                          icon: const Icon(Icons.fiber_manual_record),
                          label: const Text('Start recording'),
                        ),
                      ],
                    ],
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _statRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: Colors.grey)),
          Text(value, style: const TextStyle(fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }

  String _formatBytes(int bytes) {
    if (bytes < 1024) {
      return '$bytes B';
    }
    if (bytes < 1024 * 1024) {
      return '${(bytes / 1024).toStringAsFixed(1)} KB';
    }
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }
}
