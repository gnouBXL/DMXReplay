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

  group('DmxReplayRestClient show management (Phase G)', () {
    test('getShowInfo() sends GET_SHOW_INFO with the show name', () async {
      http.Request? captured;
      final client = _clientWith((request) async {
        captured = request;
        return _ok({
          'ok': true,
          'command': 'GET_SHOW_INFO',
          'result': {'name': 'A.dmxr', 'duration_seconds': 12.0, 'universe_count': 1},
        });
      });

      final info = await client.getShowInfo('A.dmxr');

      final sentBody = jsonDecode(captured!.body) as Map<String, dynamic>;
      expect(sentBody['command'], 'GET_SHOW_INFO');
      expect(sentBody['params'], {'name': 'A.dmxr'});
      expect(info.name, 'A.dmxr');
      expect(info.universeCount, 1);
    });

    test('deleteShow() sends DELETE_SHOW and decodes its array result', () async {
      final client = _clientWith((request) async {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['command'], 'DELETE_SHOW');
        expect(body['params'], {'name': 'A.dmxr'});
        return _ok({'ok': true, 'command': 'DELETE_SHOW', 'result': ['B.dmxr']});
      });

      final remaining = await client.deleteShow('A.dmxr');

      expect(remaining, ['B.dmxr']);
    });

    test('deleteShow() on the currently-playing show surfaces the 409 as CommandFailedException', () async {
      final client = _clientWith((request) async {
        return http.Response(
          jsonEncode({'ok': false, 'error': "cannot delete 'A.dmxr' while it is playing -- stop it first"}),
          409,
        );
      });

      await expectLater(client.deleteShow('A.dmxr'), throwsA(isA<CommandFailedException>()));
    });

    test('uploadShowBytes() PUTs the raw bytes to /api/v1/shows/{name}', () async {
      http.Request? captured;
      final client = _clientWith((request) async {
        captured = request;
        return _ok({'ok': true, 'result': {'name': 'Uploaded.dmxr', 'size_bytes': 4}});
      });

      final result = await client.uploadShowBytes('Uploaded.dmxr', [1, 2, 3, 4]);

      expect(captured!.method, 'PUT');
      expect(captured!.url.path, '/api/v1/shows/Uploaded.dmxr');
      expect(captured!.headers['Authorization'], 'Bearer test-token');
      expect(captured!.headers['Content-Type'], 'application/octet-stream');
      expect(captured!.bodyBytes, [1, 2, 3, 4]);
      expect(result['name'], 'Uploaded.dmxr');
      expect(result['size_bytes'], 4);
    });

    test('uploadShowBytes() on an invalid file surfaces the 409', () async {
      final client = _clientWith((request) async {
        return http.Response(jsonEncode({'ok': false, 'error': "not a valid DMXReplay (.dmxr) file"}), 409);
      });

      await expectLater(client.uploadShowBytes('bad.dmxr', [0]), throwsA(isA<CommandFailedException>()));
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
