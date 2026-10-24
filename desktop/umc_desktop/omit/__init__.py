"""Chat, test-reply bot, dashboard and repeater logging for a MeshCore companion node.

The ideas (an IRC-style feed, a bot that answers test calls, a 24 hour dashboard, repeaters polled
and logged) come from MeshOmit by opensourcera (MIT, https://github.com/opensourcera/MeshOmit).
This is a new implementation for the UMC Desktop app: the engine here has no screen and no radio
in it, so it is tested on a computer, and the Desktop app's web page is the interface (nothing to
type into a terminal). Differences by design: automatic replies say they are automatic, and there
is no "pretend to be a person" text mangling.
"""
