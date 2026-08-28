import 'package:flutter/material.dart';

import '../api/dmxreplay_exception.dart';
import '../api/models.dart';
import '../discovery/device_discovery_service.dart';
import '../state/connection_controller.dart';
import '../widgets/error_banner.dart';

/// First screen a user with no paired device sees: browse for a
/// DMXReplay Raspberry Pi on the local network (mDNS,
/// docs/NETWORKING.md §3) or type its IP address directly. Discovery is
/// always optional here -- manual entry works with zero dependency on it
/// (docs/MOBILE_API.md §1).
class DiscoveryScreen extends StatefulWidget {
  const DiscoveryScreen({super.key, required this.connection});

  final ConnectionController connection;

  @override
  State<DiscoveryScreen> createState() => _DiscoveryScreenState();
}

class _DiscoveryScreenState extends State<DiscoveryScreen> {
  final DeviceDiscoveryService _discovery = DeviceDiscoveryService();
  List<DeviceEndpoint> _found = const [];
  bool _scanning = false;
  String? _error;

  final _hostController = TextEditingController();
  final _portController = TextEditingController(text: '8080');

  @override
  void initState() {
    super.initState();
    if (isAndroidPlatform || isIOSPlatform) {
      _scan();
    }
  }

  @override
  void dispose() {
    _hostController.dispose();
    _portController.dispose();
    super.dispose();
  }

  Future<void> _scan() async {
    setState(() {
      _scanning = true;
      _error = null;
    });
    try {
      final found = await _discovery.discover();
      if (!mounted) {
        return;
      }
      setState(() => _found = found);
    } catch (exc) {
      if (!mounted) {
        return;
      }
      setState(() => _error = 'Discovery failed: $exc');
    } finally {
      if (mounted) {
        setState(() => _scanning = false);
      }
    }
  }

  Future<void> _connectTo(DeviceEndpoint device) async {
    final token = await _promptForToken(device.authRequired ?? true);
    if (token == null && (device.authRequired ?? true)) {
      return; // user cancelled the token dialog
    }
    await _tryConnect(device, token);
  }

  Future<void> _connectManually() async {
    final host = _hostController.text.trim();
    if (host.isEmpty) {
      setState(() => _error = 'Enter a device IP address or hostname.');
      return;
    }
    final port = int.tryParse(_portController.text.trim()) ?? 8080;
    final token = await _promptForToken(true);
    if (token == null) {
      return;
    }
    await _tryConnect(DeviceEndpoint.manual(host, port), token);
  }

  Future<String?> _promptForToken(bool required) async {
    final controller = TextEditingController();
    return showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Pairing token'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Enter the token shown on the Raspberry Pi\'s console/logs, or its '
              'local web config page, when dmxreplay-server first started.',
            ),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              autofocus: true,
              decoration: const InputDecoration(labelText: 'Token'),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(required ? null : ''),
            child: Text(required ? 'Cancel' : 'Skip (no auth)'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(controller.text.trim()),
            child: const Text('Connect'),
          ),
        ],
      ),
    );
  }

  Future<void> _tryConnect(DeviceEndpoint device, String? token) async {
    setState(() => _error = null);
    try {
      await widget.connection.connect(device, token: token == '' ? null : token);
    } on DmxReplayException catch (exc) {
      if (!mounted) {
        return;
      }
      setState(() => _error = exc.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Connect to a device'),
        actions: [
          IconButton(
            onPressed: _scanning ? null : _scan,
            icon: _scanning
                ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.refresh),
            tooltip: 'Scan again',
          ),
        ],
      ),
      body: Column(
        children: [
          ErrorBanner(message: _error, onDismiss: () => setState(() => _error = null)),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.all(12),
              children: [
                Text('Discovered devices', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                if (_found.isEmpty && !_scanning)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 12),
                    child: Text('No devices found yet. Make sure the Raspberry Pi is powered on and on the same network.'),
                  ),
                for (final device in _found)
                  Card(
                    child: ListTile(
                      leading: const Icon(Icons.developer_board),
                      title: Text(device.name),
                      subtitle: Text('${device.host}:${device.port} — API v${device.apiVersion ?? "?"}'),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => _connectTo(device),
                    ),
                  ),
                const Divider(height: 32),
                Text('Manual connection', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                TextField(
                  controller: _hostController,
                  decoration: const InputDecoration(labelText: 'IP address or hostname'),
                  keyboardType: TextInputType.url,
                ),
                const SizedBox(height: 8),
                TextField(
                  controller: _portController,
                  decoration: const InputDecoration(labelText: 'Port'),
                  keyboardType: TextInputType.number,
                ),
                const SizedBox(height: 12),
                FilledButton.icon(
                  onPressed: _connectManually,
                  icon: const Icon(Icons.link),
                  label: const Text('Connect'),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
