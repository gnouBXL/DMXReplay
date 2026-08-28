import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import 'dmxreplay_exception.dart';
import 'models.dart';

/// HTTP half of the DMXReplay Control API (docs/MOBILE_API.md §1/§5/§6/§7).
///
/// Every mutating call here maps 1:1 to a command name in
/// `dmxreplay.control.CommandRouter` (docs/API.md §10) -- this client sends
/// exactly those named commands and nothing else. **It never sends
/// individual DMX values or frame data**; the device's own master timeline
/// (`Player._run_loop()`) is what actually paces DMX output, continuously,
/// independent of whether this client is even connected
/// (docs/MOBILE_API.md §2, docs/ARCHITECTURE.md §4's acceptance test).
class DmxReplayRestClient {
  DmxReplayRestClient({
    required this.endpoint,
    this.token,
    http.Client? httpClient,
    this.timeout = const Duration(seconds: 5),
  }) : _http = httpClient ?? http.Client();

  final DeviceEndpoint endpoint;

  /// The pairing token (docs/MOBILE_API.md §4). Null only for a device
  /// explicitly started with `--no-auth` (local dev, never a real
  /// deployment) -- the app still functions, it just sends no
  /// `Authorization` header.
  final String? token;

  final Duration timeout;
  final http.Client _http;

  Map<String, String> get _authHeaders =>
      token == null ? const {} : {'Authorization': 'Bearer $token'};

  /// `GET /api/v1/version` -- the one endpoint that needs no token
  /// (docs/MOBILE_API.md §3), so this is what a "manual IP connection"
  /// screen calls first to confirm there's actually a DMXReplay device at
  /// that address before asking for a token at all.
  Future<Map<String, dynamic>> checkVersion() async {
    final uri = endpoint.httpBase().replace(path: '/api/v1/version');
    final response = await _send(() => _http.get(uri).timeout(timeout));
    return _decodeJsonObject(response.body);
  }

  Future<PlayerStatus> getStatus() async {
    final json = await _getJson('/api/v1/status');
    return PlayerStatus.fromJson(json['result'] as Map<String, dynamic>);
  }

  Future<List<String>> getShows() async {
    final json = await _getJson('/api/v1/shows');
    return (json['result'] as List<dynamic>).cast<String>();
  }

  // --- Player transport (docs/MOBILE_API.md §5's command table) -----------

  Future<PlayerStatus> loadShow(String name) async =>
      _playerCommand('LOAD_SHOW', {'name': name});

  Future<PlayerStatus> play() async => _playerCommand('PLAY');

  Future<PlayerStatus> pause() async => _playerCommand('PAUSE');

  Future<PlayerStatus> stop() async => _playerCommand('STOP');

  Future<PlayerStatus> seek(Duration position) async =>
      _playerCommand('SEEK', {'seconds': position.inMilliseconds / 1000.0});

  Future<PlayerStatus> next() async => _playerCommand('NEXT');

  Future<PlayerStatus> previous() async => _playerCommand('PREVIOUS');

  // --- Recording ------------------------------------------------------------

  Future<RecorderStatus> recordStart(String filename) async {
    final result = await command('RECORD_START', {'filename': filename});
    return RecorderStatus.fromJson(result);
  }

  Future<RecorderStatus> recordStop() async {
    final result = await command('RECORD_STOP');
    return RecorderStatus.fromJson(result);
  }

  /// `GET_RECORDER_STATUS` (docs/MOBILE_API.md §5) -- a read-only poll of
  /// live recording duration/frame/packet counts. Unlike [recordStart],
  /// calling this repeatedly does not restart the recording; it's what
  /// [RecorderController]'s polling timer uses to keep the recording
  /// screen live between `RECORD_START` and `RECORD_STOP`.
  Future<RecorderStatus> getRecorderStatus() async {
    final result = await command('GET_RECORDER_STATUS');
    return RecorderStatus.fromJson(result);
  }

  // --- Configuration ----------------------------------------------------------

  Future<DeviceConfig> getConfig() async {
    final result = await command('GET_CONFIG');
    return DeviceConfig.fromJson(result);
  }

  Future<DeviceConfig> getNetworkStatus() async {
    final result = await command('GET_NETWORK_STATUS');
    return DeviceConfig.fromJson(<String, dynamic>{
      // GET_NETWORK_STATUS's result carries only the output fields
      // (docs/MOBILE_API.md §5) -- default the playback fields DeviceConfig
      // also has so this can share the one model rather than needing a
      // second, near-identical one.
      'loop': false,
      'speed': 1.0,
      ...result,
    });
  }

  /// `SET_CONFIG` (docs/MOBILE_API.md §5): output fields (`protocol`/
  /// `interfaceIp`/`destinationIp`/`port`/`priority`) are only applied when
  /// [protocol] is given, matching the server's own rule -- never inferred
  /// from a partial set of the other fields.
  Future<DeviceConfig> setConfig({
    bool? loop,
    double? speed,
    double? fps,
    String? protocol,
    String? interfaceIp,
    String? destinationIp,
    int? port,
    int? priority,
  }) async {
    final params = <String, dynamic>{
      if (loop != null) 'loop': loop,
      if (speed != null) 'speed': speed,
      if (fps != null) 'fps': fps,
      if (protocol != null) 'protocol': protocol,
      if (interfaceIp != null) 'interface_ip': interfaceIp,
      if (destinationIp != null) 'destination_ip': destinationIp,
      if (port != null) 'port': port,
      if (priority != null) 'priority': priority,
    };
    final result = await command('SET_CONFIG', params);
    return DeviceConfig.fromJson(result);
  }

  // --- Low-level command dispatch -------------------------------------------

  Future<PlayerStatus> _playerCommand(String name, [Map<String, dynamic>? params]) async {
    final result = await command(name, params);
    return PlayerStatus.fromJson(result);
  }

  /// Sends one command over `POST /api/v1/command` (docs/MOBILE_API.md
  /// §5) and returns its `result` object. This is the single place that
  /// actually talks to the device for every mutating call above --
  /// intentionally centralized so "how a command is sent" never diverges
  /// between transport/pause/seek/etc.
  Future<Map<String, dynamic>> command(String name, [Map<String, dynamic>? params]) async {
    final uri = endpoint.httpBase().replace(path: '/api/v1/command');
    final response = await _send(
      () => _http
          .post(
            uri,
            headers: {..._authHeaders, 'Content-Type': 'application/json'},
            body: jsonEncode({'command': name, if (params != null) 'params': params}),
          )
          .timeout(timeout),
    );
    return _handleCommandResponse(name, response);
  }

  Map<String, dynamic> _handleCommandResponse(String command, http.Response response) {
    final json = _decodeJsonObject(response.body);
    if (response.statusCode == 200 && json['ok'] == true) {
      return (json['result'] as Map<String, dynamic>?) ?? const <String, dynamic>{};
    }
    final errorMessage = json['error'] as String? ?? 'Unknown error';
    switch (response.statusCode) {
      case 401:
        throw const UnauthorizedException();
      case 404:
        throw UnknownCommandException(command);
      default:
        throw CommandFailedException(command, errorMessage);
    }
  }

  Future<Map<String, dynamic>> _getJson(String path) async {
    final uri = endpoint.httpBase().replace(path: path);
    final response = await _send(() => _http.get(uri, headers: _authHeaders).timeout(timeout));
    if (response.statusCode == 401) {
      throw const UnauthorizedException();
    }
    return _decodeJsonObject(response.body);
  }

  /// Wraps the actual network call: socket errors, DNS failures, and
  /// timeouts (device offline, rebooting, wrong IP, temporarily
  /// unreachable Wi-Fi -- docs/MOBILE_API.md §8's disconnect scenarios)
  /// all become one [DeviceUnreachableException] so
  /// ConnectionController doesn't need to know every underlying
  /// dart:io/http exception type to react to "can't reach the device".
  Future<http.Response> _send(Future<http.Response> Function() call) async {
    try {
      return await call();
    } on TimeoutException {
      throw DeviceUnreachableException('Timed out reaching ${endpoint.host}:${endpoint.port}.');
    } on SocketException catch (exc) {
      throw DeviceUnreachableException('Could not reach ${endpoint.host}:${endpoint.port}: ${exc.message}');
    } on http.ClientException catch (exc) {
      throw DeviceUnreachableException(exc.message);
    }
  }

  Map<String, dynamic> _decodeJsonObject(String body) {
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) {
        return decoded;
      }
      throw const FormatException('expected a JSON object');
    } on FormatException catch (exc) {
      throw MalformedResponseException('Device returned invalid JSON: ${exc.message}');
    }
  }

  void close() => _http.close();
}
