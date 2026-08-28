import 'package:flutter/material.dart';

import '../api/dmxreplay_websocket_client.dart';
import '../state/connection_controller.dart';

/// A thin, always-visible strip showing which device this app is talking
/// to and whether the live WebSocket status feed is actually connected
/// right now. Every screen that shows device state should place this at
/// the top, so "am I looking at live data or the last thing I heard
/// before the connection dropped" is never ambiguous to the user
/// (docs/MOBILE_API.md §8's disconnect/reconnect framing).
class ConnectionStatusBanner extends StatelessWidget {
  const ConnectionStatusBanner({super.key, required this.connection});

  final ConnectionController connection;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: connection,
      builder: (context, _) {
        final endpoint = connection.endpoint;
        if (endpoint == null) {
          return _bar(
            context,
            color: Colors.grey.shade700,
            icon: Icons.link_off,
            text: 'Not connected',
          );
        }
        final state = connection.connectionState;
        final (color, icon, label) = switch (state) {
          WsConnectionState.connected => (Colors.green.shade700, Icons.check_circle, 'Connected'),
          WsConnectionState.connecting => (Colors.orange.shade700, Icons.sync, 'Connecting…'),
          WsConnectionState.authenticating => (Colors.orange.shade700, Icons.lock_clock, 'Authenticating…'),
          WsConnectionState.reconnecting => (
              Colors.orange.shade700,
              Icons.sync_problem,
              'Reconnecting… (playback on the device is unaffected)',
            ),
          WsConnectionState.disconnected => (Colors.red.shade700, Icons.link_off, 'Disconnected'),
        };
        return _bar(context, color: color, icon: icon, text: '$label — ${endpoint.name}');
      },
    );
  }

  Widget _bar(BuildContext context, {required Color color, required IconData icon, required String text}) {
    return Container(
      width: double.infinity,
      color: color,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: Row(
        children: [
          Icon(icon, color: Colors.white, size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }
}
