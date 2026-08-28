import 'package:flutter_test/flutter_test.dart';

import 'package:dmxreplay_controller/discovery/device_discovery_service.dart';

void main() {
  group('parseDeviceTxtRecord', () {
    test('parses a newline-joined TXT record as multicast_dns decodes it', () {
      // What zeroconf's properties={"api_version": "1.0", "auth_required":
      // "true"} (src/dmxreplay/control/discovery.py) becomes on the wire,
      // as decoded by multicast_dns's TxtResourceRecord.text.
      final result = parseDeviceTxtRecord('api_version=1.0\nauth_required=true\n');
      expect(result, {'api_version': '1.0', 'auth_required': 'true'});
    });

    test('ignores blank lines and entries with no "="', () {
      final result = parseDeviceTxtRecord('api_version=1.0\n\ngarbage\nauth_required=false\n');
      expect(result, {'api_version': '1.0', 'auth_required': 'false'});
    });

    test('empty text yields an empty map', () {
      expect(parseDeviceTxtRecord(''), isEmpty);
    });

    test('a value containing "=" keeps everything after the first separator', () {
      final result = parseDeviceTxtRecord('note=a=b=c');
      expect(result['note'], 'a=b=c');
    });
  });
}
