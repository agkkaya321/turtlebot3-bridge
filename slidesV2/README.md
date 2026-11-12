# NextStep — Presentation 2 (web, 12 slides)

Double-click `start.command` (or `python3 -m http.server 8770 --bind 127.0.0.1` in this folder) and open http://localhost:8770.
No internet needed: three.js r183 is in `vendor/`, the fonts and models are local.

- `js/slides.js`: slide texts and speaker notes (English). `NOTES.md` is a readable copy of the notes.
- `js/scene.js`: the 3D scene. One stage per slide; the walking cycle is ported from presentation 1 (`../dist`).
- `models/`: `robot.glb` (TurtleBot3 Burger, Meshy), `person.glb`, `laser-mount.glb` (= `../abenics-laser.glb`).
- Keys: ←/→ change slide, N speaker notes, F full screen, Space pause, R restart. `#5` in the URL opens slide 5.

The first presentation in `../dist` is unchanged.
