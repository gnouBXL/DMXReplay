import 'package:flutter/material.dart';

import '../api/dmxreplay_exception.dart';
import '../api/models.dart';
import '../state/connection_controller.dart';
import '../widgets/connection_status_banner.dart';
import '../widgets/error_banner.dart';
import '../widgets/network_status_card.dart';

/// Basic Raspberry Pi configuration (`GET_CONFIG`/`SET_CONFIG`,
/// docs/MOBILE_API.md §5) -- the brief's "Basic Raspberry Pi
/// configuration" requirement: Art-Net/sACN protocol, network interface,
/// destination IP/port/priority. This intentionally covers only the
/// fields the Control API exposes today; anything beyond that (Wi-Fi
/// setup, OS-level networking, restart/shutdown) is the local web config
/// UI (docs/API.md §10, served on the device itself at `/config`), out of
/// scope for this JSON-API-only screen (docs/MOBILE_API.md §9).
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key, required this.connection});

  final ConnectionController connection;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  DeviceConfig? _config;
  bool _loading = false;
  String? _error;

  String _protocol = 'Art-Net';
  final _interfaceController = TextEditingController(text: '0.0.0.0');
  final _destinationController = TextEditingController();
  final _portController = TextEditingController();
  final _priorityController = TextEditingController(text: '100');

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _interfaceController.dispose();
    _destinationController.dispose();
    _portController.dispose();
    _priorityController.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final client = widget.connection.restClient;
    if (client == null) {
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final config = await client.getConfig();
      if (!mounted) {
        return;
      }
      setState(() {
        _config = config;
        _protocol = config.outputProtocol ?? 'Art-Net';
        _interfaceController.text = config.interfaceIp;
        _destinationController.text = config.destinationIp ?? '';
        _portController.text = config.port?.toString() ?? '';
        _priorityController.text = config.priority.toString();
      });
    } on DmxReplayException catch (exc) {
      if (mounted) {
        setState(() => _error = exc.message);
      }
    } finally {
      if (mounted) {
        setState(() => _loading = false);
      }
    }
  }

  Future<void> _save() async {
    final client = widget.connection.restClient;
    if (client == null) {
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final config = await client.setConfig(
        protocol: _protocol,
        interfaceIp: _interfaceController.text.trim(),
        destinationIp: _destinationController.text.trim().isEmpty ? null : _destinationController.text.trim(),
        port: int.tryParse(_portController.text.trim()),
        priority: int.tryParse(_priorityController.text.trim()) ?? 100,
      );
      if (!mounted) {
        return;
      }
      setState(() => _config = config);
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Output configuration saved.')));
    } on DmxReplayException catch (exc) {
      if (mounted) {
        setState(() => _error = exc.message);
      }
    } finally {
      if (mounted) {
        setState(() => _loading = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final endpoint = widget.connection.endpoint;
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: SafeArea(
        child: Column(
          children: [
            ConnectionStatusBanner(connection: widget.connection),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  ErrorBanner(message: _error, onDismiss: () => setState(() => _error = null)),
                  const SizedBox(height: 8),
                  NetworkStatusCard(config: _config, outputConfigured: _config?.outputProtocol != null),
                  const Divider(height: 32),
                  Text('Output configuration', style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 8),
                  DropdownButtonFormField<String>(
                    value: _protocol,
                    decoration: const InputDecoration(labelText: 'Protocol'),
                    items: const [
                      DropdownMenuItem(value: 'Art-Net', child: Text('Art-Net')),
                      DropdownMenuItem(value: 'sACN', child: Text('sACN (E1.31)')),
                    ],
                    onChanged: (value) => setState(() => _protocol = value ?? 'Art-Net'),
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    controller: _interfaceController,
                    decoration: const InputDecoration(
                      labelText: 'Network interface IP',
                      helperText: '0.0.0.0 sends from the default interface',
                    ),
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    controller: _destinationController,
                    decoration: const InputDecoration(
                      labelText: 'Destination IP (optional)',
                      helperText: 'Blank = broadcast (Art-Net) or multicast (sACN)',
                    ),
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    controller: _portController,
                    decoration: const InputDecoration(labelText: 'Port (optional)'),
                    keyboardType: TextInputType.number,
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    controller: _priorityController,
                    decoration: const InputDecoration(labelText: 'sACN priority'),
                    keyboardType: TextInputType.number,
                  ),
                  const SizedBox(height: 16),
                  FilledButton.icon(
                    onPressed: _loading ? null : _save,
                    icon: const Icon(Icons.save),
                    label: const Text('Save output configuration'),
                  ),
                  const Divider(height: 32),
                  Text('Device', style: Theme.of(context).textTheme.titleMedium),
                  ListTile(
                    leading: const Icon(Icons.developer_board),
                    title: Text(endpoint?.name ?? '—'),
                    subtitle: Text(endpoint == null ? 'Not connected' : '${endpoint.host}:${endpoint.port}'),
                  ),
                  ListTile(
                    leading: const Icon(Icons.info_outline),
                    title: const Text('Advanced configuration'),
                    subtitle: const Text(
                      'For Wi-Fi, restart/shutdown, and log viewing, open this device\'s '
                      'local web config page (http://<device-ip>:8080/config) from a browser.',
                    ),
                  ),
                  const SizedBox(height: 12),
                  OutlinedButton.icon(
                    onPressed: () => _confirmForget(context),
                    icon: const Icon(Icons.link_off),
                    label: const Text('Forget this device'),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _confirmForget(BuildContext context) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Forget this device?'),
        content: const Text(
          'This only removes it from this app. It does not affect the Raspberry '
          'Pi or anything it is currently playing.',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.of(context).pop(true), child: const Text('Forget')),
        ],
      ),
    );
    if (confirmed == true) {
      await widget.connection.forgetSavedDevice();
    }
  }
}
