import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:dmxreplay_controller/api/dmxreplay_exception.dart';
import 'package:dmxreplay_controller/api/dmxreplay_rest_client.dart';
import 'package:dmxreplay_controller/api/models.dart';

DmxReplayRestClient _clientWith(Future<http.Response> Function(http.Request) handler) {
  return DmxReplayRestClient(
    endpoint: const DeviceEndpoint(name: 'Test Pi', host: '127.0.0.1', port: 8080),
    token: 'test-token',
    httpClient: MockClient(handler),
  );
}

http.Response _ok(Map<String, dynamic> body) => http.Response(jsonEncode(body), 200);

void main() {
  group('DmxReplayRestClient command()', () {
    test('sends POST /api/v1/command with the bearer token and JSON body', () async {
      http.Request? captured;
      final client = _clientWith((request) async {
        captured = request;
        return _ok({'ok': true, 'command': 'SEEK', 'result': {'loaded': true, 'playing': true}});
      });

      await client.seek(const Duration(milliseconds: 42500));

      expect(captured, isNotNull);
      expect(captured!.method, 'POST');
      expect(captured!.url.path, '/api/v1/command');
      expect(captured!.headers['Authorization'], 'Bearer test-token');
      final sentBody = jsonDecode(captured!.body) as Map<String, dynamic>;
      expect(sentBody['command'], 'SEEK');
      expect(sentBody['params'], {'seconds': 42.5});
    });

    test('PLAY/PAUSE/STOP/NEXT/PREVIOUS each send exactly their own command name', () async {
      final sentCommands = <String>[];
      final client = _clientWith((request) async {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        sentCommands.add(body['command'] as String);
        return _ok({'ok': true, 'command': body['command'], 'result': <String, dynamic>{}});
      });

      await client.play();
      await client.pause();
      await client.stop();
      await client.next();
      await client.previous();

      expect(sentCommands, ['PLAY', 'PAUSE', 'STOP', 'NEXT', 'PREVIOUS']);
    });

    test('a 401 response raises UnauthorizedException', () async {
      final client = _clientWith((request) async {
        return http.Response(jsonEncode({'ok': false, 'error': 'unauthorized'}), 401);
      });

      expect(client.play(), throwsA(isA<UnauthorizedException>()));
    });

    test('a 404 response raises UnknownCommandException naming the command', () async {
      final client = _clientWith((request) async {
        return http.Response(jsonEncode({'ok': false, 'error': "unknown command 'PLAY'"}), 404);
      });

      await expectLater(
        client.play(),
        throwsA(isA<UnknownCommandException>().having((e) => e.command, 'command', 'PLAY')),
      );
    });

    test('a 409 response raises CommandFailedException with the server error message', () async {
      final client = _clientWith((request) async {
        return http.Response(
          jsonEncode({'ok': false, 'error': 'this server has no Recorder service configured'}),
          409,
        );
      });

      await expectLater(
        client.recordStart('x.dmxr'),
        throwsA(
          isA<CommandFailedException>().having(
            (e) => e.message,
            'message',
            'this server has no Recorder service configured',
          ),
        ),
      );
    });

    test('non-JSON body raises MalformedResponseException', () async {
      final client = _clientWith((request) async => http.Response('not json', 200));
      expect(client.play(), throwsA(isA<MalformedResponseException>()));
    });
  });

  group('DmxReplayRestClient convenience getters', () {
    test('getStatus() decodes GET /api/v1/status into a PlayerStatus', () async {
      final client = _clientWith((request) async {
        expect(request.method, 'GET');
        expect(request.url.path, '/api/v1/status');
        return _ok({'ok': true, 'result': {'loaded': true, 'show_name': 'A.dmxr', 'playing': false}});
      });

      final status = await client.getStatus();
      expect(status.loaded, isTrue);
      expect(status.showName, 'A.dmxr');
    });

    test('getShows() decodes GET /api/v1/shows into a list of names', () async {
      final client = _clientWith((request) async {
        expect(request.url.path, '/api/v1/shows');
        return _ok({'ok': true, 'result': ['A.dmxr', 'B.dmxr']});
      });

      expect(await client.getShows(), ['A.dmxr', 'B.dmxr']);
    });

    test('checkVersion() hits /api/v1/version with no Authorization header', () async {
      final client = _clientWith((request) async {
        expect(request.url.path, '/api/v1/version');
        expect(request.headers.containsKey('Authorization'), isFalse);
        return _ok({'api_version': '1.0', 'auth_required': true});
      });
      final version = await client.checkVersion();
      expect(version['api_version'], '1.0');
    });
  });

  group('DmxReplayRestClient recorder commands', () {
    test('getRecorderStatus() sends GET_RECORDER_STATUS and never restarts recording', () async {
      final sentCommands = <String>[];
      final client = _clientWith((request) async {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        sentCommands.add(body['command'] as String);
        return _ok({
          'ok': true,
          'command': body['command'],
          'result': {'recording': true, 'duration_seconds': 3.0, 'frame_count': 90},
        });
      });

      final first = await client.getRecorderStatus();
      final second = await client.getRecorderStatus();

      expect(sentCommands, ['GET_RECORDER_STATUS', 'GET_RECORDER_STATUS']);
      expect(sentCommands, isNot(contains('RECORD_START')));
      expect(first.recording, isTrue);
      expect(second.recording, isTrue);
    });
  });
}
