import 'package:flutter/material.dart';

/// A dismissible status/error message strip. Used across every screen for
/// the brief's "error/status messages" requirement -- one consistent
/// place a user learns to look, rather than each screen inventing its own
/// SnackBar/dialog convention.
class ErrorBanner extends StatelessWidget {
  const ErrorBanner({super.key, required this.message, this.onDismiss});

  /// Null/empty hides the banner entirely.
  final String? message;
  final VoidCallback? onDismiss;

  @override
  Widget build(BuildContext context) {
    final text = message;
    if (text == null || text.isEmpty) {
      return const SizedBox.shrink();
    }
    return Container(
      width: double.infinity,
      color: Theme.of(context).colorScheme.errorContainer,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: Row(
        children: [
          Icon(Icons.error_outline, color: Theme.of(context).colorScheme.onErrorContainer),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: TextStyle(color: Theme.of(context).colorScheme.onErrorContainer),
            ),
          ),
          if (onDismiss != null)
            IconButton(
              icon: Icon(Icons.close, color: Theme.of(context).colorScheme.onErrorContainer),
              onPressed: onDismiss,
              tooltip: 'Dismiss',
            ),
        ],
      ),
    );
  }
}
