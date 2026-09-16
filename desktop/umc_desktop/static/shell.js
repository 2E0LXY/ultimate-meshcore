// Ultimate MeshCore Desktop: connection bar added to the device's web interface.
(() => {
  "use strict";
  const top = document.querySelector("header.top");
  if (!top) return;
  const pill = document.createElement("span");
  pill.className = "pill";
  pill.id = "deskLink";
  const btn = document.createElement("button");
  btn.className = "btn sm";
  btn.textContent = "Connections";
  btn.title = "Disconnect and choose another radio";
  const logout = document.getElementById("logoutBtn");
  top.insertBefore(pill, logout);
  top.insertBefore(btn, logout);
  btn.onclick = async () => {
    if (!confirm("Disconnect from this radio?")) return;
    await fetch("/desk/disconnect", {method: "POST"}).catch(() => {});
    sessionStorage.clear();
    location.href = "/connect";
  };
  let wasConnected = true;
  const tick = async () => {
    // radios without WiFi (other companion radios, Bluetooth-only): the WiFi pill means nothing here
    const net = document.getElementById("pillNet");
    if (net && typeof INFO !== "undefined" && INFO && !(INFO.features || []).includes("wifi")) net.style.display = "none";
    try {
      const st = await (await fetch("/desk/status", {cache: "no-store"})).json();
      const text = st.note === "installing" ? "Installing firmware…" : st.note === "restarting" ? "Restarting…" : st.label || "Not connected";
      pill.textContent = text;
      pill.className = "pill " + (st.connected && (!st.state || st.state === "connected") ? "ok" : "warn");
      if (!st.connected && !st.note && wasConnected) {
        wasConnected = false;
        setTimeout(async () => {
          const again = await (await fetch("/desk/status", {cache: "no-store"})).json().catch(() => ({}));
          if (!again.connected && !again.note) location.href = "/connect";
          else wasConnected = true;
        }, 6000);
      }
    } catch {
      pill.textContent = "Desktop app closed";
      pill.className = "pill bad";
    }
  };
  tick();
  setInterval(tick, 3000);
})();
