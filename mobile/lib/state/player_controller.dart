import 'dart:async';

import 'package:flutter/foundation.dart';

import '../api/dmxreplay_exception.dart';
import '../api/dmxreplay_rest_client.dart';
import '../api/models.dart';
import 'connection_controller.dart';

/// Player-side state and commands for the currently-connected device.
/// Every method here sends exactly one named command
/// (docs/MOBILE_API.md §5) and updates [status] from the response --
/// **this class never sends DMX data itself**, only these control
/// commands, and the device's own master timeline is what actually paces
/// playback regardless of what this app does (see
/// ConnectionController's doc comment for the fuller architectural note).
class PlayerController extends ChangeNotifier {
  PlayerController(this._connection) {
    _statusSub = _connection.statusUpdates.listen(_onStatusPush);
  }

  final ConnectionController _connection;
  StreamSubscription<PlayerStatus>? _statusSub;

  PlayerStatus _status = PlayerStatus.empty;
  List<String> _shows = const [];
  String? _lastError;
  bool _busy = false;

  PlayerStatus get status => _status;
  List<String> get shows => _shows;
  String? get lastError => _lastError;
  bool get busy => _busy;

  void _onStatusPush(PlayerStatus status) {
    _status = status;
    notifyListeners();
  }

  Future<T?> _guard<T>(Future<T> Function() action) async {
    final client = _connection.restClient;
    if (client == null) {
      _lastError = 'Not connected to a device.';
      notifyListeners();
      return null;
    }
    _busy = true;
    _lastError = null;
    notifyListeners();
    try {
      return await action();
    } on DmxReplayException catch (exc) {
      _lastError = exc.message;
      return null;
    } finally {
      _busy = false;
      notifyListeners();
    }
  }

  Future<void> refreshShows() async {
    final client = _connection.restClient;
    if (client == null) {
      return;
    }
    final result = await _guard(client.getShows);
    if (result != null) {
      _shows = result;
      notifyListeners();
    }
  }

  Future<void> refreshStatus() async {
    final client = _connection.restClient;
    if (client == null) {
      return;
    }
    final result = await _guard(client.getStatus);
    if (result != null) {
      _status = result;
      notifyListeners();
    }
  }

  Future<void> loadShow(String name) async {
    final result = await _guard(() => _connection.restClient!.loadShow(name));
    if (result != null) {
      _status = result;
      notifyListeners();
    }
  }

  Future<void> play() async => _runTransport((c) => c.play());
  Future<void> pause() async => _runTransport((c) => c.pause());
  Future<void> stop() async => _runTransport((c) => c.stop());
  Future<void> next() async => _runTransport((c) => c.next());
  Future<void> previous() async => _runTransport((c) => c.previous());
  Future<void> seek(Duration position) async => _runTransport((c) => c.seek(position));

  Future<void> _runTransport(Future<PlayerStatus> Function(DmxReplayRestClient client) call) async {
    final result = await _guard(() => call(_connection.restClient!));
    if (result != null) {
      _status = result;
      notifyListeners();
    }
  }

  /// `SET_CONFIG` with only `loop` set (docs/MOBILE_API.md §5) -- the
  /// player screen's loop toggle.
  Future<void> setLoop(bool loop) async {
    final client = _connection.restClient;
    if (client == null) {
      return;
    }
    final result = await _guard(() => client.setConfig(loop: loop));
    if (result != null) {
      // SET_CONFIG returns a DeviceConfig, not a PlayerStatus -- refresh
      // status separately so `status.loop` reflects the change.
      await refreshStatus();
    }
  }

  @override
  void dispose() {
    _statusSub?.cancel();
    super.dispose();
  }
}
