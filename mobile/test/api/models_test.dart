import 'package:flutter_test/flutter_test.dart';

import 'package:dmxreplay_controller/api/models.dart';

void main() {
  group('PlayerStatus.fromJson', () {
    test('parses a fully-populated GET_STATUS response (docs/MOBILE_API.md §6)', () {
      final status = PlayerStatus.fromJson(const {
        'loaded': true,
        'show_name': 'MyShow.dmxr',
        'universe_count': 2,
        'duration_ns': 342000000000,
        'position_ns': 15230000000,
        'playing': true,
        'loop': false,
        'speed': 1.0,
        'fps': null,
        'has_audio': true,
        'has_external_video': false,
        'output_configured': true,
      });

      expect(status.loaded, isTrue);
      expect(status.showName, 'MyShow.dmxr');
      expect(status.universeCount, 2);
      expect(status.playing, isTrue);
      expect(status.hasAudio, isTrue);
      expect(status.hasExternalVideo, isFalse);
      expect(status.outputConfigured, isTrue);
      expect(status.duration, const Duration(seconds: 342));
      expect(status.position.inMilliseconds, 15230);
    });

    test('empty is a safe, fully-unloaded default', () {
      const status = PlayerStatus.empty;
      expect(status.loaded, isFalse);
      expect(status.showName, isNull);
      expect(status.duration, Duration.zero);
      expect(status.position, Duration.zero);
    });

    test('missing optional fields fall back to sensible defaults', () {
      final status = PlayerStatus.fromJson(const {});
      expect(status.loaded, isFalse);
      expect(status.speed, 1.0);
      expect(status.fps, isNull);
    });
  });

  group('RecorderStatus.fromJson', () {
    test('parses a fully-populated RECORD_START/RECORD_STOP response', () {
      final status = RecorderStatus.fromJson(const {
        'recording': true,
        'duration_seconds': 12.4,
        'universe_count': 3,
        'frame_count': 812,
        'total_packets': 815,
        'malformed_packets': 0,
        'file_size_bytes': 4213004,
      });

      expect(status.recording, isTrue);
      expect(status.durationSeconds, 12.4);
      expect(status.frameCount, 812);
      expect(status.totalPackets, 815);
      expect(status.fileSizeBytes, 4213004);
    });

    test('empty defaults file_size_bytes to null', () {
      expect(RecorderStatus.empty.fileSizeBytes, isNull);
      expect(RecorderStatus.empty.recording, isFalse);
    });
  });

  group('DeviceConfig.fromJson', () {
    test('parses GET_CONFIG/SET_CONFIG output', () {
      final config = DeviceConfig.fromJson(const {
        'loop': true,
        'speed': 1.5,
        'fps': null,
        'output_protocol': 'Art-Net',
        'interface_ip': '192.168.1.10',
        'destination_ip': '192.168.1.255',
        'port': 6454,
        'priority': 100,
      });

      expect(config.loop, isTrue);
      expect(config.speed, 1.5);
      expect(config.outputProtocol, 'Art-Net');
      expect(config.destinationIp, '192.168.1.255');
      expect(config.port, 6454);
    });

    test('a GET_NETWORK_STATUS-shaped map (no protocol) defaults sensibly', () {
      final config = DeviceConfig.fromJson(const {
        'interface_ip': '0.0.0.0',
        'destination_ip': null,
        'port': null,
        'priority': 100,
      });
      expect(config.outputProtocol, isNull);
      expect(config.interfaceIp, '0.0.0.0');
    });
  });

  group('DeviceEndpoint', () {
    test('httpBase/wsUri build the right URIs from host/port', () {
      const endpoint = DeviceEndpoint(name: 'Stage Pi', host: '10.0.0.5', port: 8080);
      expect(endpoint.httpBase().toString(), 'http://10.0.0.5:8080');
      expect(endpoint.wsUri().toString(), 'ws://10.0.0.5:8080/api/v1/ws');
    });

    test('manual() uses the host as its display name', () {
      final endpoint = DeviceEndpoint.manual('10.0.0.9', 9090);
      expect(endpoint.name, '10.0.0.9');
      expect(endpoint.port, 9090);
    });
  });
}
