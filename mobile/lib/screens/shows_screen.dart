import 'package:flutter/material.dart';

import '../state/connection_controller.dart';
import '../state/player_controller.dart';
import '../widgets/connection_status_banner.dart';
import '../widgets/error_banner.dart';

/// Browse and select a show from the device's configured show library
/// (`GET_SHOWS`/`LOAD_SHOW`, docs/MOBILE_API.md §5) -- the brief's "Show
/// library"/"Show selection" requirement. Uploading new shows to the
/// library is Phase G (file transfer), not this screen -- this screen only
/// ever picks among files the device already has.
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
}
