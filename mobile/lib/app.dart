import 'package:flutter/material.dart';

import 'api/models.dart';
import 'screens/discovery_screen.dart';
import 'screens/player_screen.dart';
import 'screens/recorder_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/shows_screen.dart';
import 'state/connection_controller.dart';
import 'state/player_controller.dart';
import 'state/recorder_controller.dart';

/// App root: owns the single [ConnectionController] for the app's
/// lifetime, restores the last-paired device on startup, and switches
/// between the "not connected" (discovery) and "connected" (remote
/// control tabs) UI based on its state.
///
/// This widget tree is the only place that constructs [PlayerController]/
/// [RecorderController] -- both are (re)created exactly when the app
/// transitions to a newly-connected device, and torn down on disconnect,
/// since both hold a subscription tied to that specific connection's
/// WebSocket status stream.
class DmxReplayApp extends StatefulWidget {
  const DmxReplayApp({super.key});

  @override
  State<DmxReplayApp> createState() => _DmxReplayAppState();
}

class _DmxReplayAppState extends State<DmxReplayApp> {
  final ConnectionController _connection = ConnectionController();
  PlayerController? _player;
  RecorderController? _recorder;
  DeviceEndpoint? _controllersBuiltFor;

  @override
  void initState() {
    super.initState();
    _connection.addListener(_syncControllers);
    _connection.restoreLastConnection();
  }

  void _syncControllers() {
    final endpoint = _connection.endpoint;
    if (endpoint == null) {
      _player?.dispose();
      _recorder?.dispose();
      _player = null;
      _recorder = null;
      _controllersBuiltFor = null;
      return;
    }
    if (_controllersBuiltFor != endpoint) {
      _player?.dispose();
      _recorder?.dispose();
      _player = PlayerController(_connection);
      _recorder = RecorderController(_connection);
      _controllersBuiltFor = endpoint;
    }
  }

  @override
  void dispose() {
    _connection.removeListener(_syncControllers);
    _player?.dispose();
    _recorder?.dispose();
    _connection.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'DMXReplay Remote',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorSchemeSeed: Colors.deepPurple, useMaterial3: true),
      darkTheme: ThemeData(colorSchemeSeed: Colors.deepPurple, brightness: Brightness.dark, useMaterial3: true),
      home: ListenableBuilder(
        listenable: _connection,
        builder: (context, _) {
          if (!_connection.isConnected || _player == null || _recorder == null) {
            return DiscoveryScreen(connection: _connection);
          }
          return _RemoteControlHome(
            connection: _connection,
            player: _player!,
            recorder: _recorder!,
          );
        },
      ),
    );
  }
}

class _RemoteControlHome extends StatefulWidget {
  const _RemoteControlHome({required this.connection, required this.player, required this.recorder});

  final ConnectionController connection;
  final PlayerController player;
  final RecorderController recorder;

  @override
  State<_RemoteControlHome> createState() => _RemoteControlHomeState();
}

class _RemoteControlHomeState extends State<_RemoteControlHome> {
  int _tab = 0;

  @override
  Widget build(BuildContext context) {
    final screens = [
      PlayerScreen(connection: widget.connection, player: widget.player),
      ShowsScreen(connection: widget.connection, player: widget.player),
      RecorderScreen(connection: widget.connection, recorder: widget.recorder),
      SettingsScreen(connection: widget.connection),
    ];
    return Scaffold(
      body: IndexedStack(index: _tab, children: screens),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (index) => setState(() => _tab = index),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.play_circle_outline), selectedIcon: Icon(Icons.play_circle), label: 'Player'),
          NavigationDestination(icon: Icon(Icons.movie_outlined), selectedIcon: Icon(Icons.movie), label: 'Shows'),
          NavigationDestination(icon: Icon(Icons.fiber_manual_record_outlined), selectedIcon: Icon(Icons.fiber_manual_record), label: 'Record'),
          NavigationDestination(icon: Icon(Icons.settings_outlined), selectedIcon: Icon(Icons.settings), label: 'Settings'),
        ],
      ),
    );
  }
}
