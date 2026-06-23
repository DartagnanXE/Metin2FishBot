# Test-Paket fuer die reine Solver-Logik des Metin2MultiTool.
#
# Enthaelt ausschliesslich stdlib-'unittest'-Tests, die NUR tetris.py und
# piece.py importieren (keine Fremd-Dependencies wie numpy/cv2/win32/
# pydirectinput). So laufen die Tests auch unter WSL/Linux gruen, wo die
# Capture-/Eingabe-Bibliotheken nicht installierbar sind.
