# Credits

- **MeshOmit** by opensourcera (MIT, https://github.com/opensourcera/MeshOmit): the ideas behind the Desktop app's
  Chat page: an IRC-style feed of the mesh, a bot that answers test calls with per-station limits and rotating
  lines, beacons whose replies are counted, a 24-hour dashboard, and repeaters polled and logged to SQLite. The code
  here is a new implementation (a hardware-free engine tested with a fake radio, and a web page instead of a terminal
  screen). It differs on purpose: automatic replies say they are automatic and do not imitate a person.
- **MeshCore** by Scott Powell / Ripple Biz, MIT: the firmware this project is built on.


## Android design system
- **shadcn/ui** (MIT) and **Tailwind CSS** (MIT): the design language (colour tokens, radius, borders, type scale, component set) the Android app follows. They are web libraries, so the app uses its own Compose version of the design, not their code.
- **Lucide** (ISC), through the **Composables Icons Lucide** package (Apache 2.0): the icons.
