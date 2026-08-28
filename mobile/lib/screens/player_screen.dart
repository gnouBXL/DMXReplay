import 'package:flutter/material.dart';

import '../state/connection_controller.dart';
import '../state/player_controller.dart';
import '../widgets/connection_status_banner.dart';
import '../widgets/error_banner.dart';
import '../widgets/timeline_slider.dart';
import '../widgets/transport_controls.dart';

/// The main remote-control screen: current show, timeline/seek, transport
/// buttons, loop toggle, and a compact sync/output status readout. This is
/// the screen a user spends most of their time on -- the brief's "Player:
/// Play, Pause, Stop, Seek, Previous, Next" requirement.
///
/// Every control here sends one named command and nothing else
/// (`PlayerController`'s own doc comment) -- this screen never sends DMX
/// data, and the Raspberry Pi keeps playing exactly as it was if this
/// screen (or the whole app) disappears mid-show.
class PlayerScreen extends StatefulWidget {
  const PlayerScreen({super.key, required this.connection, required this.player});

  final ConnectionController connection;
  final PlayerController player;

  @override
  State<PlayerScreen> createState() => _PlayerScreenState();
}

class _PlayerScreenState extends State<PlayerScreen> {
  @override
  void initState() {
    super.initState();
    widget.player.refreshStatus();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            ConnectionStatusBanner(connection: widget.connection),
            Expanded(
              child: ListenableBuilder(
                listenable: widget.player,
                builder: (context, _) {
                  final status = widget.player.status;
                  return RefreshIndicator(
                    onRefresh: widget.player.refreshStatus,
                    child: ListView(
                      padding: const EdgeInsets.all(16),
                      children: [
                        ErrorBanner(message: widget.player.lastError),
                        const SizedBox(height: 8),
                        Text(
                          status.showName ?? 'No show loaded',
                          style: Theme.of(context).textTheme.headlineSmall,
                          textAlign: TextAlign.center,
                        ),
                        const SizedBox(height: 4),
                        Text(
                          status.loaded
                              ? '${status.universeCount} universe(s)'
                                  '${status.hasAudio ? " · audio" : ""}'
                                  '${status.hasExternalVideo ? " · video" : ""}'
                              : 'Load a show from the Shows tab',
                          textAlign: TextAlign.center,
                          style: const TextStyle(color: Colors.grey),
                        ),
                        const SizedBox(height: 24),
                        TimelineSlider(
                          position: status.position,
                          duration: status.duration,
                          enabled: status.loaded && !widget.player.busy,
                          onSeekEnd: widget.player.seek,
                        ),
                        const SizedBox(height: 16),
                        TransportControls(
                          playing: status.playing,
                          enabled: status.loaded && !widget.player.busy,
                          onPlay: widget.player.play,
                          onPause: widget.player.pause,
                          onStop: widget.player.stop,
                          onNext: widget.player.next,
                          onPrevious: widget.player.previous,
                        ),
                        const SizedBox(height: 24),
                        SwitchListTile(
                          title: const Text('Loop'),
                          value: status.loop,
                          onChanged: status.loaded
                              ? (value) => widget.player.setLoop(value)
                              : null,
                        ),
                        ListTile(
                          leading: Icon(
                            status.outputConfigured ? Icons.wifi_tethering : Icons.wifi_tethering_off,
                            color: status.outputConfigured ? Colors.green : Colors.grey,
                          ),
                          title: Text(status.outputConfigured ? 'Output configured' : 'Output not configured'),
                          subtitle: const Text('Configure Art-Net/sACN output in the Settings tab'),
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
