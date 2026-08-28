/// Exceptions the API layer raises -- kept distinct so the UI layer can
/// tell "wrong/no token" apart from "the device rejected this specific
/// command" apart from "couldn't reach the device at all" and react
/// differently (docs/MOBILE_API.md §7's error table).
library;

/// Base class for every error this app's API layer raises.
sealed class DmxReplayException implements Exception {
  const DmxReplayException(this.message);

  final String message;

  @override
  String toString() => message;
}

/// The device returned 401 -- missing or wrong token
/// (docs/MOBILE_API.md §4/§7).
class UnauthorizedException extends DmxReplayException {
  const UnauthorizedException() : super('Not authorized -- check the pairing token.');
}

/// The device understood the command but could not carry it out (missing
/// param, no show loaded, required service not configured on the server,
/// ...) -- docs/MOBILE_API.md §7's 409 row.
class CommandFailedException extends DmxReplayException {
  const CommandFailedException(this.command, super.message);

  final String command;
}

/// The command name itself isn't one the device recognizes
/// (docs/MOBILE_API.md §7's 404 row) -- should not happen against a
/// matching API version; surfaced distinctly in case it does (e.g. an app
/// built against a newer API talking to an older device).
class UnknownCommandException extends DmxReplayException {
  const UnknownCommandException(this.command) : super("Device doesn't recognize command '$command'.");

  final String command;
}

/// Could not reach the device at all -- network unreachable, device
/// offline/rebooting, wrong IP, etc. (docs/MOBILE_API.md §8's disconnect
/// handling -- the reconnection logic in ConnectionController reacts to
/// this specifically).
class DeviceUnreachableException extends DmxReplayException {
  const DeviceUnreachableException(String message) : super(message);
}

/// The device responded, but not with valid JSON in the shape this app
/// expects -- most likely a very different API version or a non-DMXReplay
/// server on that IP/port.
class MalformedResponseException extends DmxReplayException {
  const MalformedResponseException(String message) : super(message);
}
