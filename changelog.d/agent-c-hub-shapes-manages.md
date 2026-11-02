### Fixed

- web: `tools/hub-shapes.json` re-recorded after #1187, whose member lists carry `manages`; `hub/tests/test_web_shapes.py` failed on main since #1187 and #1192 crossed. The fixture's missing `manages` is in the baseline until #1189 brings it.
