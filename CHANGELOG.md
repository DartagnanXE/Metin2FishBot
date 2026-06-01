# Changelog

Alle nennenswerten Aenderungen an diesem Projekt werden hier festgehalten.
Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

## [1.0.4] — 2026-06-01

Grosses UI- und Funktions-Update: komplett neu gestaltete, kompakte Oberflaeche
plus viele neue Komfort- und Erkennungs-Funktionen. Empfohlenes Update fuer alle.

### Neue Oberflaeche (Cockpit-Sidebar)

- Komplett neues, **kompaktes** Single-Window-Layout mit schlanker **Icon-
  Navigationsleiste** links: Angeln, Puzzle, Console, Roadmap, Einstellungen.
- **START/STOP ganz oben** (zeigt waehrend des Laufs, ob Angeln oder Puzzle
  laeuft) mit **Lauf-Timer daneben** (zaehlt bei gesetztem Limit herunter, sonst
  die Laufzeit hoch).
- Spiel-Erkennung dezent unten rechts: **blendet sich aus**, sobald Metin2
  (800x600) gefunden ist; **prueft jetzt auch die Fenstergroesse** und bietet bei
  falscher Groesse einen **Ein-Klick "Auf 800x600 setzen"** (resized das Spiel).
- Inhalt oben gruppiert, feste Fenstergroesse, **kein Scrollen** noetig.
- Dezente **Versions-/Update-Anzeige** unten links (leuchtet nur bei verfuegbarem
  Update auf) mit Herkunfts-Tooltip.

### Neue Einstellungen

- **In den Tray minimieren**, **Immer im Vordergrund**, **Schliessen wenn Metin2
  schliesst**, **Schliessen wenn der Timer ablaeuft**, **Angel-Hotkeys umbelegen**
  (Koeder-/Angel-Taste frei waehlbar), **Overlay-Deckkraft** regelbar.
- **Einstellungen zuruecksetzen** (Werkseinstellungen, mit Bestaetigung).

### Board-Erkennung

- **"?"-Hilfebild** zurueck (zeigt, wo die Punkte hingehoeren).
- Detection-Modi mit **Sicht-Overlay**: **Default/Auto** zeigen ~5 s die Punkte
  ueber dem Desktop (Ausrichtung pruefen); **"Manuell"** (vorher "Mark") oeffnet
  beim Umschalten direkt das Markier-Overlay. **Overlay-Deckkraft** einstellbar.
- Mehrere Metin2-Fenster offen? **Fenster-Auswahl per Klick**.

### Sonstiges

- **Deutsch jetzt mit echten Umlauten** (ae/oe/ue/ss -> ä/ö/ü/ß).
- Kleiner **"Testfenster"-Knopf** unter Console (oeffnet ein Test-"METIN2"-Fenster
  zum Ausprobieren ohne echtes Spiel).
- Neuer **Roadmap-Tab** mit den geplanten Funktionen.
- **Installer entfaellt:** Auslieferung jetzt ausschliesslich als **Portable**
  (eine `.exe`, kein Setup, keine Installation) — ein Download, weniger Reibung.

## [1.0.3] — 2026-05-31

Zwei neue Funktionen: **eingebaute Update-Benachrichtigung** und eine
**konfigurierbare Goldener-Thunfisch-Aktion**.

### Neu

- **Auto-Update (ab jetzt eingebaut):** Beim Start prueft die App im Hintergrund
  (eigener Thread, blockiert das UI nie) die GitHub-Releases. Gibt es eine
  neuere Version, erscheint ein dezentes Banner — **ein Klick laedt die neue
  Portable, ersetzt sie an Ort und Stelle und startet neu.** Bewusst
  **nutzer-initiiert** (kein stilles Auto-Download -> schont die AV-Lage),
  Admin-bewusst. Die Installer-Variante oeffnet stattdessen die Release-Seite.
  Neue `version.py` als einzige Versions-Quelle (auch fuer beide Specs).
- **Goldener-Thunfisch-Aktion waehlbar:** In den Einstellungen festlegen, was der
  Bot beim Fang eines goldenen Thunfischs tut — **1 = Freilassen, 2 =
  Aufschneiden, 3 = Als Koeder benutzen**. **Default jetzt 3** (vorher das
  mittlere Feld). Der Bot loggt die geklickte Position zur Verifikation.

## [1.0.2] — 2026-05-31

**Wichtiges Fix-Update — behebt, dass das Angeln in der EXE nicht funktionierte.**

### Behoben (kritisch)

- **Angeln erkannte das Minispiel nie / spielte es nicht** (in der gepackten
  EXE): Die Angel-Vorlagenbilder (`fiss.jpg`, `clock.jpg`) wurden mit einem
  nackten Pfad geladen, der nur im Quellcode-Start (Arbeitsverzeichnis = Projekt)
  funktioniert — **in der EXE lagen sie im PyInstaller-Bundle und wurden zu
  `None`**, sodass die Bilderkennung nie etwas fand. Jetzt ueber `resource_path()`
  geladen (wie das Puzzle es bereits tat). Der Bot warf zuvor brav Koeder/Angel
  aus, „sah" das Spiel aber nicht.
- **Eingaben erreichten das Spiel nicht** (Maus bewegte sich, Klicks/Tasten kamen
  nicht an): Das Spiel laeuft meist als Administrator, die EXE nicht — Windows
  **UIPI** blockt dann die Eingaben. Die EXE **fordert jetzt automatisch Admin an**
  (UAC-Manifest, `uac_admin`); kein „Als Administrator ausfuehren" mehr noetig.

### Verbessert (Selbstdiagnose)

- Beim Start wird klar geloggt, falls Vorlagenbilder **nicht geladen** werden
  konnten (statt stiller Fehlerkennung).
- Pro Angel-Runde wird die **Minispiel-Trefferguete** geloggt (`>0,90 = erkannt`)
  — so ist sofort sichtbar, ob die Uhr erkannt wird oder die Schwelle/Position
  nachjustiert werden muss.

## [1.0.1] — 2026-05-31

Stabilitaets- und Diagnose-Update ueber 1.0.0 (gleiche Funktionen, nur robuster
und mit klareren Logs). Empfohlenes Update fuer alle.

### Behoben

- **Angeln stuerzte auf manchen Systemen sofort ab** (`cv2.matchTemplate`-
  Assertion bei abweichender Capture-Form/DPI-Skalierung). Die Vorlagensuche ist
  jetzt robust (kontiguierlich, Kanal-/Groessen-Abgleich, jeder cv2-Fehler
  abgefangen) -> **kein Absturz mehr**; im Zweifel „nicht erkannt" statt Crash.
- **UI verschob die `Bot | Console`- und `EN | DE`-Schalter**, wenn der Status-
  Text laenger wurde -> die Buttons sind jetzt fest am rechten Rand verankert.
- Puzzle-Stopmeldung zeigte unausgefuellte Platzhalter (`{valid}` …) -> echte
  Zahlen.

### Verbessert (Selbstdiagnose)

- **Angeln meldet sich selbst:** unterscheidet „echte Runde beendet" von
  **„kein Biss — kein Minispiel erschienen"** und warnt nach mehreren Leer-
  Auswuerfen klar mit Checkliste (Angel ausgeworfen? Koeder auf Taste 2? Spiel
  in 800x600?). Stoppt nicht — meldet aber, statt stumm weiterzuloopen.
- **Puzzle-Erkennung praeziser:** klassifiziert die 24 Zellen in _echte
  Steinfarbe / leer / Garbage_ und unterscheidet sauber **leeres Brett /
  volles Brett / „Board nicht erkannt"** (z.B. falsche Fensterposition / kein
  echtes Puzzle) — jeder Stopp mit glasklarer Begruendung.

## [1.0.0] — 2026-05-31

Erste oeffentliche Version dieser ueberarbeiteten Fassung. Sie basiert als Fork
auf [vncsms/Metin2FishBot](https://github.com/vncsms/Metin2FishBot) (Angel-
Mechanik und Puzzle-Erkennungs-Basis); alles Weitere ist neu/ueberarbeitet —
dateigenaue Herkunft in [`NOTICE`](NOTICE). Die urspruenglichen Faehigkeiten
bleiben als **Default** erhalten (byte-stabil); alle Neuerungen sind **optional**
im UI zuschaltbar.

### Neues Single-Window-UI (CustomTkinter, Dark/Teal)

- **Zweisprachig (EN/DE), live umschaltbar** ueber einen dezenten Schalter oben
  rechts: UI, Hinweise UND alle Log-Zeilen wechseln sofort; die Wahl wird in
  `config.json` gespeichert (Standard: Englisch). UI kompakt skaliert -> alles
  ohne Scrollen auf einer Seite.
- Ein Fenster mit Umschalter **Bot ⇄ Console** (integrierte Live-Konsole statt
  separatem Debug-Tool) — Konsole mit **Kopieren / Logdatei oeffnen / Leeren**.
- Grosser **START/STOP**-Button, Umschalter **Fishing | Puzzle** (exklusiv,
  waehrend des Laufs gesperrt).
- **Spiel-Erkennung im Status:** „● Metin2 detected — ready" (gruen), sobald das
  Spiel-Fenster gefunden ist, sonst „○ Waiting for Metin2…". Rein passiver
  Fenster-Check (`FindWindow`) — kein Prozessspeicher-Zugriff.
- Robuste Auswahl-Schalter (eigene Buttons statt des leer rendernden
  CTkSegmentedButton), **scrollbares** Layout (resize-fest), eigenes
  **Musketier-Icon** (Fenster + Taskleiste), Sofort-Render, **Auto-Speichern**
  der Einstellungen, **„?"-Hilfen** mit Referenzbild.
- Delay-Schieberegler **0.1–20 s** (Koeder / Auswurf / Minispiel-Start) plus
  „Stop nach X Minuten".

### Puzzle-Features (optional — Default bleibt unveraendert)

- **Solver-Methode:** _Default_ (Original-Greedy + Eroeffnungsbuch) oder
  _KI optimiert_ (beweisbar optimale Strategie per exakter MDP-Wertiteration;
  Tabelle wird einmalig in ~12 s berechnet und als `trained_V.npy` gecacht).
- **Board-Erkennung:** _Default_ (feste Position) / _Auto_ (Bildabgleich) /
  _Mark_ (selbst kalibrieren per Vollbild-Overlay mit Raster-Griffen, 4
  Sonderpunkten und eingeblendetem **Referenzbild**). Aufloesungsunabhaengig.
- **Farb-Sampling:** _Single_ (1 Pixel, Default) oder _Multi_ (robuster gegen
  leichte Farbabweichungen).

### Build & Auslieferung

- **Portable** (eine `.exe`, kein Install) **und Installer** (Inno Setup, mit
  Start-Menue-/Desktop-Verknuepfung und echtem Deinstaller).
- Gegen generische Viren-Heuristik gehaertet: **kein UPX**, echte **PE-Metadaten**,
  onedir-Variante. (Ohne Code-Signatur nicht garantiert eliminierbar — siehe
  README-Abschnitt zu Virenwarnungen.)
- Abhaengigkeiten als flexible Mindest-Versionen (laeuft auf Python 3.11–3.13).

### Tests

- Headless-Testsuite (reine Logik, ohne GUI/Spiel): **126 Tests gruen**.

### Unveraendert (bewusst, byte-stabil)

- **Angeln** (`fishingbot.py`, `fishfilter.py`, `hsvfilter.py`) und der
  **Standard-Puzzle-Solver** (Greedy in `tetris.py`): Verhalten wie im Original.
  Die KI bzw. die optionalen Modi laufen ausschliesslich, wenn explizit gewaehlt.
