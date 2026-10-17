#pragma once

#include <helpers/BaseChatMesh.h>
#include <stdint.h>

// On-device screens (the T-Deck) ask for the things a phone app normally asks for: log in to a
// repeater, read its status, run commands on it, trace a route. While such a screen is open it
// registers one of these with the companion, and the replies it asked for come here instead of
// going out over the app link. Each callback returns true when it took the reply (so it is not
// passed on), false when the reply was not for it.
class UmcRepeaterTap {
public:
  virtual ~UmcRepeaterTap() {}
  // login, status or telemetry reply: data starts with the 4 byte tag, then the payload
  virtual bool onContactResponse(const ContactInfo& from, const uint8_t* data, uint8_t len) = 0;
  // the text a repeater answers a command with
  virtual bool onCommandReply(const ContactInfo& from, const char* text) = 0;
  // a trace that came back: path_len id bytes, one SNR (x4) per hop, and the SNR of the last hop to us
  virtual bool onTrace(uint32_t tag, const uint8_t* hashes, const uint8_t* snrs, uint8_t path_len, uint8_t flags,
                       int8_t final_snr_x4) = 0;
};
