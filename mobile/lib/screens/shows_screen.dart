import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/connection_controller.dart';
import '../state/player_controller.dart';
import '../widgets/connection_status_banner.dart';
import '../widgets/error_banner.dart';

/// Browse, select, inspect, and delete shows in the device's configured
/// show library (`GET_SHOWS`/`LOAD_SHOW`/`GET_SHOW_INFO`/`DELETE_SHOW`,
/// docs/MOBILE_API.md §5) -- the brief's "Show library"/"Show selection"
/// requirement plus Phase G's delete/info. Uploading a new show onto the
/// device (`PUT /api/v1/shows/{name}`) is implemented in
/// `DmxReplayRestClient.uploadShowBytes`/`docs/MOBILE_API.md` §5 but has no
/// UI here yet -- picking a file from the phone's storage needs a
/// file-picker plugin this project doesn't currently depend on (see
/// docs/MOBILE.md's platform notes).
class ShowsScreen extends StatefulWidget {
  const ShowsScreen({super.key, required this.connection, required this.player});

  final ConnectionController connection;
  final PlayerController player;

  @override
  State<ShowsScreen> createState() => _ShowsScreenState();
}

class _ShowsScreenState extends State<ShowsScreen> {
  @override
  void initState() {
    super.initState();
    widget.player.refreshShows();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Shows')),
      body: SafeArea(
        child: Column(
          children: [
            ConnectionStatusBanner(connection: widget.connection),
            Expanded(
              child: ListenableBuilder(
                listenable: widget.player,
                builder: (context, _) {
                  return RefreshIndicator(
                    onRefresh: widget.player.refreshShows,
                    child: Column(
                      children: [
                        ErrorBanner(message: widget.player.lastError),
                        Expanded(
                          child: widget.player.shows.isEmpty
                              ? ListView(
                                  children: const [
                                    Padding(
                                      padding: EdgeInsets.all(24),
                                      child: Text(
                                        'No shows found in the device\'s show library.',
                                        textAlign: TextAlign.center,
                                      ),
                                    ),
                                  ],
                                )
                              : ListView.builder(
                                  itemCount: widget.player.shows.length,
                                  itemBuilder: (context, index) {
                                    final name = widget.player.shows[index];
                                    final isCurrent = widget.player.status.showName == name;
                                    return ListTile(
                                      leading: Icon(
                                        isCurrent ? Icons.play_circle : Icons.movie_outlined,
                                        color: isCurrent ? Theme.of(context).colorScheme.primary : null,
                                      ),
                                      title: Text(name),
                                      selected: isCurrent,
                                      enabled: !widget.player.busy,
                                      onTap: () => widget.player.loadShow(name),
                                      trailing: PopupMenuButton<String>(
                                        enabled: !widget.player.busy,
                                        onSelected: (action) {
                                          if (action == 'info') {
                                            _showInfo(context, name);
                                          } else if (action == 'delete') {
                                            _confirmDelete(context, name);
                                          }
                                        },
                                        itemBuilder: (context) => const [
                                          PopupMenuItem(value: 'info', child: Text('Show info')),
                                          PopupMenuItem(value: 'delete', child: Text('Delete')),
                                        ],
                                      ),
                                    );
                                  },
                                ),
                        ),
                      ],
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _showInfo(BuildContext context, String name) async {
    final info = await widget.player.getShowInfo(name);
    if (!context.mounted) {
      return;
    }
    if (info == null) {
      return; // error already surfaced via widget.player.lastError's banner
    }
    await showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(info.name),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _infoRow('Duration', '${info.durationSeconds.toStringAsFixed(1)} s'),
            _infoRow('Universes', info.universeCount.toString()),
            _infoRow('Encoding', info.encoding),
            _infoRow('FPS', info.vfr ? 'variable' : (info.fps?.toStringAsFixed(1) ?? '—')),
            _infoRow('Audio', info.hasAudio ? 'yes' : 'no'),
            _infoRow('External video', info.hasExternalVideo ? 'yes' : 'no'),
            if (info.fileSizeBytes != null) _infoRow('File size', _formatBytes(info.fileSizeBytes!)),
            if (info.description != null) _infoRow('Description', info.description!),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Close')),
        ],
      ),
    );
  }

  Widget _infoRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: Colors.grey)),
          const SizedBox(width: 12),
          Flexible(child: Text(value, textAlign: TextAlign.right)),
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

  Future<void> _confirmDelete(BuildContext context, String name) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Delete $name?'),
        content: const Text(
          'This permanently removes the show from the device. If it is currently '
          'playing, stop it first.',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.of(context).pop(true), child: const Text('Delete')),
        ],
      ),
    );
    if (confirmed == true) {
      await widget.player.deleteShow(name);
    }
  }
}
