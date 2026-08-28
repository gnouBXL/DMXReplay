import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

import 'models.dart';

/// Connection lifecycle states this client can be in -- surfaced directly
/// to the UI (`ConnectionStatusBanner`) so the user always sees whether
/// they're looking at live data or a stale last-known status.
enum WsConnectionState { disconnected, connecting, authenticating, connected, reconnecting }

/// WebSocket half of the Control API (docs/MOBILE_API.md §6/§8):
/// **receive-only** from this app's point of view. Commands
/// (play/pause/seek/...) are sent over [DmxReplayRestClient] instead, which
/// has natural one-request-one-response semantics; this client's only job
/// is the real-time `{"type": "status", "data": {...}}` broadcast the
/// Control API pushes roughly once per second so the timeline/play-state UI
/// stays live without polling (docs/MOBILE_API.md §6's own framing).
///
/// This is a deliberate architecture choice, not a limitation of the wire
/// protocol: docs/MOBILE_API.md §5 documents that the *same* commands work
/// over the WebSocket connection too, but that protocol has no
/// request-id/correlation field, so multiplexing concurrent commands over
/// it would need either strict FIFO ordering discipline or a correlation
/// scheme the server doesn't currently provide. Routing all commands
/// through REST (which HTTP already correlates for free) and reserving
/// this connection for status keeps both halves simple and correct
/// instead of adding client-side complexity to work around a gap in the
/// server's WS protocol. If a future server version adds message IDs,
/// commands could move here too without changing anything on the REST
/// side.
///
/// Handles reconnection (docs/ARCHITECTURE.md §4's acceptance test: the
/// smartphone disconnecting -- backgrounded app, Wi-Fi drop, the
/// Raspberry Pi itself rebooting -- must never affect the device's own
/// playback, and this app must recover gracefully when connectivity
/// returns) with capped exponential backoff, re-running the auth
/// handshake on every reconnect attempt since a fresh WebSocket connection
/// always starts unauthenticated (docs/MOBILE_API.md §4/§8).
class DmxReplayWebSocketClient {
  DmxReplayWebSocketClient({
    required this.endpoint,
    this.token,
    this.reconnectDelays = const <Duration>[
      Duration(seconds: 1),
      Duration(seconds: 2),
      Duration(seconds: 5),
      Duration(seconds: 10),
      Duration(seconds: 20),
      Duration(seconds: 30), // caps here -- keeps retrying every 30s indefinitely
    ],
    this.authTimeout = const Duration(seconds: 10),
    WebSocketChannel Function(Uri uri)? channelFactory,
  }) : _channelFactory = channelFactory ?? WebSocketChannel.connect;

  final DeviceEndpoint endpoint;
  final String? token;
  final List<Duration> reconnectDelays;
  final Duration authTimeout;
  final WebSocketChannel Function(Uri uri) _channelFactory;

  final StreamController<PlayerStatus> _statusController = StreamController<PlayerStatus>.broadcast();
  final StreamController<WsConnectionState> _stateController = StreamController<WsConnectionState>.broadcast();

  /// Live `PlayerStatus` pushes from the device, roughly once per second
  /// while connected (docs/MOBILE_API.md §6).
  Stream<PlayerStatus> get statusUpdates => _statusController.stream;

  /// Connection lifecycle changes -- drive `ConnectionStatusBanner` from
  /// this, not from guessing based on the last status update's age.
  Stream<WsConnectionState> get connectionState => _stateController.stream;

  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _subscription;
  Timer? _reconnectTimer;
  int _reconnectAttempt = 0;
  bool _stoppedByUser = false;

  WsConnectionState _lastState = WsConnectionState.disconnected;

  void _setState(WsConnectionState state) {
    _lastState = state;
    _stateController.add(state);
  }

  /// Connects (or reconnects) once. Call [start] instead for normal use --
  /// this is the single attempt [start]/the reconnect loop both build on.
  Future<void> _connectOnce() async {
    _setState(WsConnectionState.connecting);
    final channel = _channelFactory(endpoint.wsUri());
    _channel = channel;

    if (token != null) {
      _setState(WsConnectionState.authenticating);
      channel.sink.add(jsonEncode({'type': 'auth', 'token': token}));
      final firstMessage = await channel.stream.first.timeout(authTimeout);
      final decoded = jsonDecode(firstMessage as String) as Map<String, dynamic>;
      if (decoded['type'] != 'auth_ok') {
        await channel.sink.close();
        throw StateError('WebSocket authentication rejected by device.');
      }
    }

    _setState(WsConnectionState.connected);
    _reconnectAttempt = 0;
    _subscription = channel.stream.listen(
      _handleMessage,
      onDone: _handleDisconnect,
      onError: (Object _) => _handleDisconnect(),
      cancelOnError: true,
    );
  }

  void _handleMessage(dynamic raw) {
    final Map<String, dynamic> decoded;
    try {
      decoded = jsonDecode(raw as String) as Map<String, dynamic>;
    } on FormatException {
      return; // malformed frame -- ignore rather than crash the connection
    }
    if (decoded['type'] == 'status') {
      _statusController.add(PlayerStatus.fromJson(decoded['data'] as Map<String, dynamic>));
    }
    // {"type": "response", ...} echoes of commands sent by *other* clients
    // (or, in a future protocol version, commands this app itself might
    // send over this channel) are intentionally ignored here -- see the
    // class doc comment on why this app routes commands through REST.
  }

  void _handleDisconnect() {
    _subscription?.cancel();
    _subscription = null;
    if (_stoppedByUser) {
      _setState(WsConnectionState.disconnected);
      return;
    }
    _setState(WsConnectionState.reconnecting);
    _scheduleReconnect();
  }

  void _scheduleReconnect() {
    _reconnectTimer?.cancel();
    final delay = reconnectDelays[_reconnectAttempt.clamp(0, reconnectDelays.length - 1)];
    _reconnectAttempt++;
    _reconnectTimer = Timer(delay, () {
      if (_stoppedByUser) {
        return;
      }
      _connectOnce().catchError((Object _) => _handleDisconnect());
    });
  }

  /// Starts the connection and the automatic-reconnect loop. Safe to call
  /// once per client instance (create a new client if you need to change
  /// [endpoint]/[token]).
  Future<void> start() async {
    _stoppedByUser = false;
    try {
      await _connectOnce();
    } catch (_) {
      _handleDisconnect();
    }
  }

  /// Stops the connection and, importantly, stops the automatic-reconnect
  /// loop -- call this when the user explicitly disconnects/switches
  /// devices, not on a transient network blip (that's what the built-in
  /// reconnect handles on its own).
  Future<void> stop() async {
    _stoppedByUser = true;
    _reconnectTimer?.cancel();
    await _subscription?.cancel();
    await _channel?.sink.close();
    _setState(WsConnectionState.disconnected);
  }

  WsConnectionState get currentState => _lastState;

  Future<void> dispose() async {
    await stop();
    await _statusController.close();
    await _stateController.close();
  }
}
