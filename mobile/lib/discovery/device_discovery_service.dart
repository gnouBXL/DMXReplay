import 'dart:async';
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:multicast_dns/multicast_dns.dart';

import '../api/models.dart';

/// Whether mDNS discovery is even meaningful on this platform --
/// `Platform.isAndroid`/`isIOS` throw on web (no `dart:io` there), and web
/// has no multicast socket access anyway, so the discovery screen uses
/// this to decide whether to show the "Discover" button at all versus
/// falling back straight to manual IP entry (docs/MOBILE.md's platform
/// notes).
bool get isAndroidPlatform => !kIsWeb && Platform.isAndroid;
bool get isIOSPlatform => !kIsWeb && Platform.isIOS;

/// Browses the local network for DMXReplay devices via mDNS
/// (docs/NETWORKING.md §3) -- the Dart-side counterpart to
/// `dmxreplay.control.discovery.discover_devices()` on the Python side
/// (src/dmxreplay/control/discovery.py), using the platform's real mDNS
/// resolver through the Flutter team's own `multicast_dns` package rather
/// than embedding a second implementation of the mDNS wire protocol.
///
/// Discovery is always optional (docs/MOBILE_API.md §1) -- manual IP entry
/// (`DeviceEndpoint.manual`, wired up directly in the discovery screen)
/// works with zero dependency on this class, matching
/// `docs/ARCHITECTURE.md` §5's rule that discovery must never gate the
/// underlying API.
class DeviceDiscoveryService {
  DeviceDiscoveryService({MDnsClient? client}) : _client = client ?? MDnsClient();

  static const String serviceType = '_dmxreplay._tcp.local';

  final MDnsClient _client;

  /// Browses for [timeout] and returns every DMXReplay device found. Each
  /// device requires a full PTR -> SRV -> A -> TXT resolution chain
  /// (standard mDNS/DNS-SD, RFC 6763) -- this method does all four lookups
  /// per device before returning it.
  Future<List<DeviceEndpoint>> discover({Duration timeout = const Duration(seconds: 4)}) async {
    final List<DeviceEndpoint> found = <DeviceEndpoint>[];
    await _client.start();
    try {
      await for (final PtrResourceRecord ptr in _client
          .lookup<PtrResourceRecord>(ResourceRecordQuery.serverPointer(serviceType))
          .timeout(timeout, onTimeout: (sink) => sink.close())) {
        final DeviceEndpoint? device = await _resolve(ptr.domainName);
        if (device != null) {
          found.add(device);
        }
      }
    } finally {
      _client.stop();
    }
    return found;
  }

  Future<DeviceEndpoint?> _resolve(String instanceName) async {
    final SrvResourceRecord? srv = await _client
        .lookup<SrvResourceRecord>(ResourceRecordQuery.service(instanceName))
        .firstOrNullWithin(const Duration(seconds: 2));
    if (srv == null) {
      return null;
    }

    final IPAddressResourceRecord? address = await _client
        .lookup<IPAddressResourceRecord>(ResourceRecordQuery.addressIPv4(srv.target))
        .firstOrNullWithin(const Duration(seconds: 2));
    if (address == null) {
      return null;
    }

    final TxtResourceRecord? txt = await _client
        .lookup<TxtResourceRecord>(ResourceRecordQuery.text(instanceName))
        .firstOrNullWithin(const Duration(seconds: 2));
    final Map<String, String> properties = txt == null ? const {} : parseDeviceTxtRecord(txt.text);

    // Strip the trailing ".<serviceType>" suffix and the "DMXReplay-"
    // prefix this project's own server always advertises with
    // (src/dmxreplay/control/discovery.py's _service_name()), leaving just
    // the human device name.
    var displayName = instanceName;
    final suffix = '.$serviceType.';
    if (displayName.endsWith(suffix)) {
      displayName = displayName.substring(0, displayName.length - suffix.length);
    } else if (displayName.endsWith('.$serviceType')) {
      displayName = displayName.substring(0, displayName.length - '.$serviceType'.length);
    }
    const prefix = 'DMXReplay-';
    if (displayName.startsWith(prefix)) {
      displayName = displayName.substring(prefix.length);
    }

    return DeviceEndpoint(
      name: displayName,
      host: address.address.address,
      port: srv.port,
      apiVersion: properties['api_version'],
      authRequired: properties['auth_required'] == 'true',
    );
  }

}

/// `multicast_dns`'s `TxtResourceRecord.text` joins every length-prefixed
/// TXT sub-string with a newline (confirmed against the package's own
/// packet-decoding source, not assumed) -- so a record built from
/// `zeroconf`'s `properties={"api_version": "1.0", "auth_required":
/// "true"}` (src/dmxreplay/control/discovery.py) decodes here as
/// `"api_version=1.0\nauth_required=true\n"`. A top-level function (not a
/// private method) so it can be unit-tested directly without standing up
/// an [MDnsClient].
Map<String, String> parseDeviceTxtRecord(String text) {
  final Map<String, String> result = {};
  for (final line in text.split('\n')) {
    if (line.isEmpty) {
      continue;
    }
    final separator = line.indexOf('=');
    if (separator == -1) {
      continue;
    }
    result[line.substring(0, separator)] = line.substring(separator + 1);
  }
  return result;
}

extension _FirstOrNullWithin<T> on Stream<T> {
  Future<T?> firstOrNullWithin(Duration timeout) async {
    try {
      return await first.timeout(timeout);
    } on StateError {
      return null; // stream closed with no elements
    } on TimeoutException {
      return null;
    }
  }
}
