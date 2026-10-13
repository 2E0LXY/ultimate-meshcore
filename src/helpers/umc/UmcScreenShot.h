#pragma once

#include <stddef.h>
#include <stdint.h>

// Screenshots of a device's own screen, served by the web server.
//
// A board with a screen registers a capture function during start-up. It renders the page
// asked for into an off-screen buffer - the real display is not touched - and hands back
// the pixels as RGB565, row by row from the top. The capture is called from the web
// server's task and must block until the picture is ready.
//
// "page" is a short name the board understands ("home", "msgs", "setup/radio", ...).
typedef bool (*UmcShotFn)(const char* page, const uint16_t** pixels, int* width, int* height);

void umcSetScreenShot(UmcShotFn fn);
UmcShotFn umcScreenShot();

// Screenshots show messages, so they need permission too: opened from the device itself
// ("screen share 10" on the console) and closed again on their own.
void umcOpenScreenShare(uint32_t for_ms);
void umcCloseScreenShare();
bool umcScreenShareOpen();
