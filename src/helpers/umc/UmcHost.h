#pragma once

#include <stddef.h>
#include <stdint.h>

class UmcAppServer;

// Ultimate MeshCore (UMC) — interface every firmware role (repeater, companion,
// room server) implements so the shared network services can drive it.
//
// umcCommand() is always invoked from the Arduino loop task (UmcService marshals
// requests from the HTTP/telnet/BLE tasks), so implementations may touch mesh
// state freely.
class UmcHost {
public:
  virtual ~UmcHost() = default;

  // Run one CLI line exactly as if typed on USB serial. reply is NUL-terminated.
  virtual void umcCommand(const char* command, char* reply, size_t reply_size) = 0;

  virtual const char* umcAdminPassword() const = 0;
  virtual const char* umcNodeName() const = 0;
  virtual const char* umcRole() const = 0;           // "repeater" | "companion" | "room_server"
  virtual const char* umcFirmwareVersion() const = 0;
  virtual const char* umcBuildDate() const = 0;
  virtual const char* umcBoardName() const = 0;
  // Current mesh clock (UTC epoch seconds), 0 if unknown.
  virtual uint32_t umcEpoch() { return 0; }

  // Called just before an OTA image starts streaming into flash.
  virtual void umcPrepareForOta() {}
  // Called when the device is about to reboot on UMC's behalf (after OTA, factory reset...).
  virtual void umcBeforeReboot() {}

  // One MeshCore companion-protocol frame received from an app on TCP port 5000.
  // Reply with server.send(); the default rejects everything as unsupported.
  virtual void umcAppFrame(UmcAppServer& server, int client, const uint8_t* frame, size_t len);
};
