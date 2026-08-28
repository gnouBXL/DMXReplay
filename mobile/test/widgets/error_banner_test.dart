import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:dmxreplay_controller/widgets/error_banner.dart';

void main() {
  testWidgets('renders nothing when message is null', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: ErrorBanner(message: null))));
    expect(find.byType(ErrorBanner), findsOneWidget);
    expect(find.text(''), findsNothing);
    expect(find.byIcon(Icons.error_outline), findsNothing);
  });

  testWidgets('renders the message and calls onDismiss', (tester) async {
    var dismissed = false;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ErrorBanner(
            message: 'Could not reach the device.',
            onDismiss: () => dismissed = true,
          ),
        ),
      ),
    );

    expect(find.text('Could not reach the device.'), findsOneWidget);
    await tester.tap(find.byIcon(Icons.close));
    expect(dismissed, isTrue);
  });
}
