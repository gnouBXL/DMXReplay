import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/dmxreplay_exception.dart';
import '../api/dmxreplay_rest_client.dart';
import '../api/dmxreplay_websocket_client.dart';
import '../api/models.dart';

const String _prefKeyHost = 'dmxreplay.device.host';
const String _prefKeyPort = 'dmxreplay.device.port';
const String _prefKeyName = 'dmxreplay.device.name';
const String _prefKeyToken = 'dmxreplay.device.token';

/// Owns the connection to exactly one DMXReplay device at a time: the
/// paired [DeviceEndpoint]/token, the REST and WebSocket clients built
/// from them, and the last-known connection state. Every screen reads
/// connection status from here rather than probing the network itself.
///
/// **The Raspberry Pi remains the authoritative real-time engine and
/// master clock regardless of anything in this class** (docs/ARCHITECTURE.md
/// §4/§13-§15, docs/MOBILE_API.md §2/§8): this controller's job is issuing
/// commands and displaying status, never pacing playback. If [disconnect]
/// is called, or the app is backgrounded, or Wi-Fi drops, device playback
/// continues completely unaffected -- there is nothing in this class or
/// anywhere else in this app that the device depends on to keep playing.
class ConnectionController extends ChangeNotifier {
  ConnectionController({SharedPreferencesAsync? preferences})
      : _preferences = preferences ?? SharedPreferencesAsync();

  final SharedPreferencesAsync _preferences;

  DeviceEndpoint? _endpoint;
  String? _token;
  DmxReplayRestClient? _restClient;
  DmxReplayWebSocketClient? _wsClient;
  StreamSubscription<WsConnectionState>? _wsStateSub;

  WsConnectionState _connectionState = WsConnectionState.disconnected;
  String? _lastError;

  DeviceEndpoint? get endpoint => _endpoint;
  bool get isConnected => _endpoint != null;
  WsConnectionState get connectionState => _connectionState;
  String? get lastError => _lastError;

  /// The REST client for the currently-connected device -- null if
  /// nothing is connected. Screens should null-check this once and show a
  /// "not connected" state rather than each caller handling it separately.
  DmxReplayRestClient? get restClient => _restClient;

  /// Live status push from the device (docs/MOBILE_API.md §6). Empty
  /// stream (never emits) if not connected.
  Stream<PlayerStatus> get statusUpdates => _wsClient?.statusUpdates ?? const Stream<PlayerStatus>.empty();

  /// Restores the last-paired device from persistent storage, if any, and
  /// reconnects to it. Call once at app startup (see `app.dart`). Does
  /// nothing (not an error) if no device was ever paired.
  Future<void> restoreLastConnection() async {
    final host = await _preferences.getString(_prefKeyHost);
    if (host == null) {
      return;
    }
    final port = await _preferences.getInt(_prefKeyPort) ?? 8080;
    final name = await _preferences.getString(_prefKeyName) ?? host;
    final token = await _preferences.getString(_prefKeyToken);
    await connect(DeviceEndpoint(name: name, host: host, port: port), token: token, persist: false);
  }

  /// Connects to [device]. Verifies it's actually a DMXReplay device first
  /// (`GET /api/v1/version`, no auth needed, docs/MOBILE_API.md §3) before
  /// committing to it, so a wrong manually-typed IP fails fast with a
  /// clear error rather than silently "connecting" to nothing.
  Future<void> connect(DeviceEndpoint device, {String? token, bool persist = true}) async {
    await disconnect();
    _lastError = null;
    notifyListeners();

    final probeClient = DmxReplayRestClient(endpoint: device, token: token);
    try {
      final version = await probeClient.checkVersion();
      final authRequired = version['auth_required'] as bool? ?? true;
      if (authRequired && (token == null || token.isEmpty)) {
        throw const UnauthorizedException();
      }
    } on DmxReplayException catch (exc) {
      probeClient.close();
      _lastError = exc.message;
      notifyListeners();
      rethrow;
    }

    _endpoint = device;
    _token = token;
    _restClient = probeClient;
    _wsClient = DmxReplayWebSocketClient(endpoint: device, token: token);
    _wsStateSub = _wsClient!.connectionState.listen((state) {
      _connectionState = state;
      notifyListeners();
    });
    unawaited(_wsClient!.start());

    if (persist) {
      await _preferences.setString(_prefKeyHost, device.host);
      await _preferences.setInt(_prefKeyPort, device.port);
      await _preferences.setString(_prefKeyName, device.name);
      if (token != null) {
        await _preferences.setString(_prefKeyToken, token);
      } else {
        await _preferences.remove(_prefKeyToken);
      }
    }
    notifyListeners();
  }

  /// Disconnects deliberately (user action, e.g. "forget this device").
  /// This is a UI-side action only -- the device itself never knows or
  /// cares that this app disconnected, and keeps playing exactly as it
  /// was (docs/MOBILE_API.md §8).
  Future<void> disconnect() async {
    await _wsStateSub?.cancel();
    _wsStateSub = null;
    await _wsClient?.dispose();
    _wsClient = null;
    _restClient?.close();
    _restClient = null;
    _endpoint = null;
    _token = null;
    _connectionState = WsConnectionState.disconnected;
    notifyListeners();
  }

  Future<void> forgetSavedDevice() async {
    await disconnect();
    await _preferences.remove(_prefKeyHost);
    await _preferences.remove(_prefKeyPort);
    await _preferences.remove(_prefKeyName);
    await _preferences.remove(_prefKeyToken);
  }

  @override
  void dispose() {
    unawaited(disconnect());
    super.dispose();
  }
}
