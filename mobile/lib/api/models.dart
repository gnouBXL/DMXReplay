/// Data models mirroring the JSON shapes DMXReplay's Control API returns.
/// See ../../../docs/MOBILE_API.md §6 -- field names and types here are
/// kept in exact lockstep with that document (and, ultimately, with
/// `dmxreplay.service.PlayerStatus`/`RecorderStatus` on the Python side,
/// `docs/API.md` §9) rather than reshaped for Dart convenience, so a
/// client author cross-checking the two never finds them disagreeing.
library;

/// Mirrors `dmxreplay.service.PlayerStatus` (docs/API.md §9) exactly as
/// serialized by the Control API (docs/MOBILE_API.md §6).
class PlayerStatus {
  const PlayerStatus({
    required this.loaded,
    required this.showName,
    required this.universeCount,
    required this.durationNs,
    required this.positionNs,
    required this.playing,
    required this.loop,
    required this.speed,
    required this.fps,
    required this.hasAudio,
    required this.hasExternalVideo,
    required this.outputConfigured,
  });

  factory PlayerStatus.fromJson(Map<String, dynamic> json) {
    return PlayerStatus(
      loaded: json['loaded'] as bool? ?? false,
      showName: json['show_name'] as String?,
      universeCount: json['universe_count'] as int? ?? 0,
      durationNs: (json['duration_ns'] as num?)?.toInt() ?? 0,
      positionNs: (json['position_ns'] as num?)?.toInt() ?? 0,
      playing: json['playing'] as bool? ?? false,
      loop: json['loop'] as bool? ?? false,
      speed: (json['speed'] as num?)?.toDouble() ?? 1.0,
      fps: (json['fps'] as num?)?.toDouble(),
      hasAudio: json['has_audio'] as bool? ?? false,
      hasExternalVideo: json['has_external_video'] as bool? ?? false,
      outputConfigured: json['output_configured'] as bool? ?? false,
    );
  }

  final bool loaded;
  final String? showName;
  final int universeCount;
  final int durationNs;
  final int positionNs;
  final bool playing;
  final bool loop;
  final double speed;
  final double? fps;
  final bool hasAudio;
  final bool hasExternalVideo;
  final bool outputConfigured;

  Duration get duration => Duration(microseconds: durationNs ~/ 1000);
  Duration get position => Duration(microseconds: positionNs ~/ 1000);

  /// A status with nothing loaded -- the app's initial/disconnected state,
  /// so widgets never have to null-check a `PlayerStatus?` throughout the
  /// UI layer (see PlayerController's own doc comment).
  static const PlayerStatus empty = PlayerStatus(
    loaded: false,
    showName: null,
    universeCount: 0,
    durationNs: 0,
    positionNs: 0,
    playing: false,
    loop: false,
    speed: 1.0,
    fps: null,
    hasAudio: false,
    hasExternalVideo: false,
    outputConfigured: false,
  );
}

/// Mirrors `dmxreplay.recorder.RecorderStatus` (docs/API.md §4) exactly as
/// serialized by the Control API (docs/MOBILE_API.md §6).
class RecorderStatus {
  const RecorderStatus({
    required this.recording,
    required this.durationSeconds,
    required this.universeCount,
    required this.frameCount,
    required this.totalPackets,
    required this.malformedPackets,
    required this.fileSizeBytes,
  });

  factory RecorderStatus.fromJson(Map<String, dynamic> json) {
    return RecorderStatus(
      recording: json['recording'] as bool? ?? false,
      durationSeconds: (json['duration_seconds'] as num?)?.toDouble() ?? 0.0,
      universeCount: json['universe_count'] as int? ?? 0,
      frameCount: json['frame_count'] as int? ?? 0,
      totalPackets: json['total_packets'] as int? ?? 0,
      malformedPackets: json['malformed_packets'] as int? ?? 0,
      fileSizeBytes: json['file_size_bytes'] as int?,
    );
  }

  final bool recording;
  final double durationSeconds;
  final int universeCount;
  final int frameCount;
  final int totalPackets;
  final int malformedPackets;
  final int? fileSizeBytes;

  static const RecorderStatus empty = RecorderStatus(
    recording: false,
    durationSeconds: 0.0,
    universeCount: 0,
    frameCount: 0,
    totalPackets: 0,
    malformedPackets: 0,
    fileSizeBytes: null,
  );
}

/// Merges `GET_CONFIG`'s playback fields with its embedded output/network
/// fields (docs/MOBILE_API.md §5's `SET_CONFIG` table -- the two are one
/// command/response on the wire, deliberately not split into two models
/// here either).
class DeviceConfig {
  const DeviceConfig({
    required this.loop,
    required this.speed,
    required this.fps,
    required this.outputProtocol,
    required this.interfaceIp,
    required this.destinationIp,
    required this.port,
    required this.priority,
  });

  factory DeviceConfig.fromJson(Map<String, dynamic> json) {
    return DeviceConfig(
      loop: json['loop'] as bool? ?? false,
      speed: (json['speed'] as num?)?.toDouble() ?? 1.0,
      fps: (json['fps'] as num?)?.toDouble(),
      outputProtocol: json['output_protocol'] as String?,
      interfaceIp: json['interface_ip'] as String? ?? '0.0.0.0',
      destinationIp: json['destination_ip'] as String?,
      port: json['port'] as int?,
      priority: json['priority'] as int? ?? 100,
    );
  }

  final bool loop;
  final double speed;
  final double? fps;
  final String? outputProtocol;
  final String interfaceIp;
  final String? destinationIp;
  final int? port;
  final int priority;
}

/// A DMXReplay device the app knows about -- either found via mDNS
/// (docs/NETWORKING.md §3) or entered manually by IP (the app must never
/// require discovery, docs/MOBILE_API.md §1).
class DeviceEndpoint {
  const DeviceEndpoint({
    required this.name,
    required this.host,
    required this.port,
    this.apiVersion,
    this.authRequired,
  });

  factory DeviceEndpoint.manual(String host, int port) {
    return DeviceEndpoint(name: host, host: host, port: port);
  }

  final String name;
  final String host;
  final int port;
  final String? apiVersion;
  final bool? authRequired;

  Uri httpBase() => Uri(scheme: 'http', host: host, port: port);
  Uri wsUri() => Uri(scheme: 'ws', host: host, port: port, path: '/api/v1/ws');

  @override
  String toString() => '$name ($host:$port)';
}
