import 'dart:async';

import 'package:flutter/foundation.dart';

import '../api/dmxreplay_exception.dart';
import '../api/models.dart';
import 'connection_controller.dart';

/// Recorder-side state and commands. Unlike [PlayerController], the
/// Control API has no WebSocket broadcast for recorder status
/// (docs/MOBILE_API.md §6 -- the server only pushes `PlayerStatus`), so
/// this polls `GET_RECORDER_STATUS` on a short timer while actively
/// recording instead. Same rule as everywhere else in this app: only ever
/// sends named commands (`RECORD_START`/`RECORD_STOP`/`GET_RECORDER_STATUS`),
/// never DMX data.
class RecorderController extends ChangeNotifier {
  RecorderController(this._connection);

  final ConnectionController _connection;
  Timer? _pollTimer;

  RecorderStatus _status = RecorderStatus.empty;
  String? _lastError;
  bool _busy = false;

  RecorderStatus get status => _status;
  String? get lastError => _lastError;
  bool get busy => _busy;

  Future<void> start(String filename) async {
    final client = _connection.restClient;
    if (client == null) {
      _lastError = 'Not connected to a device.';
      notifyListeners();
      return;
    }
    _busy = true;
    _lastError = null;
    notifyListeners();
    try {
      _status = await client.recordStart(filename);
      _startPolling();
    } on DmxReplayException catch (exc) {
      _lastError = exc.message;
    } finally {
      _busy = false;
      notifyListeners();
    }
  }

  Future<void> stop() async {
    final client = _connection.restClient;
    if (client == null) {
      return;
    }
    _busy = true;
    notifyListeners();
    try {
      _status = await client.recordStop();
    } on DmxReplayException catch (exc) {
      _lastError = exc.message;
    } finally {
      _stopPolling();
      _busy = false;
      notifyListeners();
    }
  }

  void _startPolling() {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(const Duration(seconds: 2), (_) async {
      final client = _connection.restClient;
      if (client == null) {
        return;
      }
      try {
        _status = await client.getRecorderStatus();
        if (!_status.recording) {
          // Stopped on the device side (e.g. disk full, source lost) --
          // stop polling rather than keep hitting a recorder that's no
          // longer recording.
          _stopPolling();
        }
        notifyListeners();
      } on DmxReplayException {
        // Intentionally swallowed -- a transient poll failure shouldn't
        // surface as a user-facing error on top of whatever
        // ConnectionController's own reconnect handling is already doing.
      }
    });
  }

  void _stopPolling() {
    _pollTimer?.cancel();
    _pollTimer = null;
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    super.dispose();
  }
}
