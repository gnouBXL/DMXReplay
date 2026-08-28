import 'package:flutter/material.dart';

import '../api/models.dart';

/// Read-only summary of the device's Art-Net/sACN output configuration
/// (`GET_NETWORK_STATUS`/`GET_CONFIG`, docs/MOBILE_API.md §5) -- the
/// brief's "Art-Net/sACN output status" and "network status" requirements.
/// This card only displays what the device reports; editing happens on
/// [SettingsScreen] via `SET_CONFIG`.
class NetworkStatusCard extends StatelessWidget {
  const NetworkStatusCard({super.key, required this.config, required this.outputConfigured});

  final DeviceConfig? config;
  final bool outputConfigured;

  @override
  Widget build(BuildContext context) {
    final c = config;
    return Card(
      margin: const EdgeInsets.all(12),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  outputConfigured ? Icons.wifi_tethering : Icons.wifi_tethering_off,
                  color: outputConfigured ? Colors.green : Colors.grey,
                ),
                const SizedBox(width: 8),
                Text(
                  outputConfigured ? 'Output configured' : 'Output not configured',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ],
            ),
            if (c != null) ...[
              const SizedBox(height: 8),
              _row('Protocol', c.outputProtocol ?? '—'),
              _row('Interface', c.interfaceIp),
              _row('Destination', c.destinationIp ?? '—'),
              _row('Port', c.port?.toString() ?? '—'),
              _row('Priority', c.priority.toString()),
            ],
          ],
        ),
      ),
    );
  }

  Widget _row(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: Colors.grey)),
          Text(value),
        ],
      ),
    );
  }
}
