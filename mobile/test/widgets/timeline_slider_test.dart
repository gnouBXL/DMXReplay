import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:dmxreplay_controller/widgets/timeline_slider.dart';

void main() {
  testWidgets('shows formatted elapsed and total time', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TimelineSlider(
            position: const Duration(minutes: 1, seconds: 5),
            duration: const Duration(minutes: 5, seconds: 42),
            enabled: true,
            onSeekEnd: (_) {},
          ),
        ),
      ),
    );

    expect(find.text('01:05'), findsOneWidget);
    expect(find.text('05:42'), findsOneWidget);
  });

  testWidgets('disables the slider when not enabled', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TimelineSlider(
            position: Duration.zero,
            duration: const Duration(minutes: 1),
            enabled: false,
            onSeekEnd: (_) {},
          ),
        ),
      ),
    );

    final slider = tester.widget<Slider>(find.byType(Slider));
    expect(slider.onChanged, isNull);
  });

  testWidgets('calls onSeekEnd with the dragged position', (tester) async {
    Duration? seeked;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TimelineSlider(
            position: Duration.zero,
            duration: const Duration(seconds: 100),
            enabled: true,
            onSeekEnd: (d) => seeked = d,
          ),
        ),
      ),
    );

    final sliderFinder = find.byType(Slider);
    await tester.drag(sliderFinder, const Offset(50, 0));
    await tester.pumpAndSettle();

    expect(seeked, isNotNull);
  });
}
