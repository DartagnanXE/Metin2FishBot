# Metin2 Fishing Bot — Benutzung & Build

Anleitung zur überarbeiteten Version. Der **Angel-Teil** ist funktional
unverändert (byte-stabil). Neu: ein modernes **Single-Window-UI**
(CustomTkinter), integriertes **Live-Log**, drei **Board-Detection-Modi** fürs
Puzzle, **Color-Sampling-Toggle**, optionaler **Trained-Solver** — und ein
gehärteter **Portable**-Build gegen False-Positive-Virenwarnungen.

---

## 1. Was neu ist

- **Modernes UI** (dark/teal), ein Fenster, ein großer **START/STOP**-Button,
  Umschalter **Fishing | Puzzle** (während des Laufs gesperrt; beides nie
  gleichzeitig).
- **Settings** direkt im Fenster: Delays (0.1–20 s), Board Detection
  (Default / Auto / Mark), Color Sampling (Single / Multi), Stop-after-Time,
  Puzzle-Solver (**Default | KI optimiert**). Alles wird in **`config.json`**
  neben der EXE gespeichert.
- **Optionaler KI-Solver fürs Puzzle** („KI optimiert"): legt die Steine
  mathematisch optimal (kostet im Schnitt die wenigsten Steine bis das Brett
  voll ist). Der **erste** KI-Lauf rechnet **einmalig ~12 s** eine
  Strategie-Tabelle und speichert sie als **`trained_V.npy`** neben der EXE;
  danach startet er **sofort**. Der bisherige Standard-Solver bleibt Default
  und unverändert.
- **Live-Log im UI** (`● live`) — zeigt die `debuglog`-Events in Echtzeit. Die
  Datei `puzzle_debug.log` wird **zusätzlich** weiter geschrieben.
- **Mark-Kalibrierung** des Spielfelds: transparentes Overlay über dem Spiel,
  Raster aufziehen + optionale Sonderpunkte — mit mitgeliefertem **Referenzbild**
  als Vorlage (Details in §5).
- **Gehärteter Build:** Portable EXE ohne UPX, mit echten **PE-Metadaten** und
  gepinnten Abhängigkeiten. Das senkt generische Virenwarnungen (Wacatac & Co.)
  — Details + ehrliches Restrisiko in §8.
- **126 automatische Tests** sichern die Solver- und Erkennungs-Logik ab.

---

## 2. Build (auf einem Windows-Rechner)

> Eine Windows-`.exe` muss **auf Windows** gebaut werden (nicht plattform-
> übergreifend). Empfohlen: **Python 3.11 oder 3.12** (64-bit).

**Doppelklick-Weg:** **`build.bat`** ausführen. Das Skript:

1. installiert die **gepinnten** Abhängigkeiten aus `requirements.txt`,
2. baut die **Portable** → `dist_onefile\Metin2FishBot.exe` (eine einzige Datei,
   mit allen Libraries + eingebetteten Assets im Bundle).

Das ist alles — am Ende liegt **eine** `.exe` bereit, die du direkt weitergeben
kannst.

### Verteilung an Nutzer

- Die **eine** Datei `dist_onefile\Metin2FishBot.exe` weitergeben — fertig.
  Doppelklick startet sie direkt, keine Installation, keine Begleitdateien.

> Pins prüfen (einmalig vor Release): `py -m pip install -r requirements.txt`
> dann `py -m pip freeze > installed.txt` und die Versionen in
> `requirements.txt` ggf. angleichen (v. a. `pywin32`/`PyDirectInput` hängen am
> Interpreter).

---

## 3. Starten

- App **als Administrator** starten — die `Metin2FishBot.exe` **fordert Admin
  automatisch an** (UAC-Abfrage bestätigen).
- Spiel in **800×600**, **nicht** Vollbild. Fenster sichtbar lassen.
- Fisch-Skill auf Hotkey `1`, Köder auf `2`, Angel ausgerüstet.
- Im UI Modus **Fishing** oder **Puzzle** wählen, ggf. Settings anpassen,
  **START** drücken. Fürs Puzzle das Minispiel öffnen und das
  Minispiel-Fenster **nicht verschieben**.

> Während der Bot läuft, sind Modus-Umschalter und alle Settings **gesperrt**.
> Zum Ändern erst **STOP** drücken. Deine Einstellungen werden beim Schließen in
> `config.json` gespeichert und beim nächsten Start automatisch geladen.

---

## 4. Alle Einstellungen erklärt (für Einsteiger)

Alles, was du hier umstellst, landet in `config.json` neben der EXE. Wenn du
unsicher bist: Die **Standard-Werte sind sicher** — sie verhalten sich exakt wie
die alte Version. Neue Funktionen musst du bewusst einschalten.

### 4.1 Delays (Sekunden) — gilt fürs Angeln

Drei Schieberegler, jeweils **0,1 s bis 20 s** (in 0,1-Schritten):

- **Wait to put bait** — Wartezeit, bevor der Köder in die Angel kommt.
- **Wait to throw** — Wartezeit, bevor ausgeworfen wird.
- **Wait to start game** — Wartezeit, bevor das Fisch-Minispiel startet.

Höher = mehr Puffer auf langsameren PCs / bei Lags, aber langsamer. Im Zweifel
beim Standard (2 s) bleiben.

**Stop after time (min):** Häkchen setzen und Minuten eintragen, dann stoppt der
Bot nach Ablauf der Zeit von selbst.

### 4.2 Board Detection — 3 Modi, wie das Spielfeld gefunden wird (Puzzle)

Das Puzzle-Feld muss exakt getroffen werden, sonst klickt der Bot daneben.

- **Default** — feste Standard-Position. Funktioniert, wenn dein Spiel im
  unterstützten 800×600-Fenster an gewohnter Stelle liegt. **Empfohlen zum
  Einstieg.**
- **Auto** — der Bot **sucht das Feld automatisch** per Bildvergleich. Findet er
  es nicht sicher, fällt er **automatisch auf Default zurück** und schreibt den
  Grund ins Log (kein Absturz).
- **Mark** — du markierst das Feld **einmal selbst** (siehe §5). Genau das
  Richtige, wenn Default/Auto bei dir nicht sitzen. Ist keine gültige Markierung
  gespeichert, wird ebenfalls auf Default zurückgefallen.

Der **„Mark board region…"**-Button startet die Markier-Hilfe (§5).

### 4.3 Color Sampling — wie Stein-/Feldfarben gelesen werden (Puzzle)

- **Single** — liest **1 Pixel** pro Zelle (wie bisher, schnell, byte-stabil).
- **Multi** — mittelt einen **kleinen Bereich** (3×3 oder 5×5 Pixel) um den
  Mittelpunkt und ordnet die Farbe der **nächstgelegenen Referenzfarbe** zu. Das
  ist **robuster gegen leichte Farb­abweichungen**. Nutze Multi, wenn im Log
  öfter „Stein-Farbe nicht erkannt" mit ansonsten plausibler Farbe steht.

### 4.4 Puzzle Solver — Default oder KI optimiert (Puzzle)

- **Default** — die bewährte Standard-Logik. **Unverändert** und voreingestellt.
- **KI optimiert** — eine **mathematisch optimale** Platzier-Strategie: sie wählt
  Züge so, dass im Schnitt die **wenigsten Steine** verbraucht werden, bis das
  Brett voll ist.
  - **Wichtig — einmalige Wartezeit beim ersten Lauf:** Der allererste KI-Lauf
    berechnet **einmalig ca. 12 Sekunden** eine Strategie-Tabelle und speichert
    sie als **`trained_V.npy`** neben der EXE. **Ab dann startet die KI sofort**
    (die Tabelle wird nur noch geladen). Lösche `trained_V.npy` nicht — sonst
    wird einmalig neu gerechnet.
  - Verläuft die Berechnung oder das Laden schief (z. B. schreibgeschützter
    Ordner), arbeitet der Bot trotzdem weiter; im schlimmsten Fall wird die
    Tabelle pro Start neu berechnet.

---

## 5. Mark-Kalibrierung: Spielfeld einmal selbst markieren

Wähle **Board Detection = Mark** oder klicke **„Mark board region…"**. Es öffnet
sich ein **halbtransparentes Overlay über dem ganzen Bildschirm**.

**So markierst du das Raster:**

1. Du siehst zwei eckige **Griffe „TL"** (oben-links) und **„BR"** (unten-rechts)
   sowie ein vorgezeichnetes 4×6-Punkteraster dazwischen.
2. Ziehe **TL** auf die **Mitte der Zelle oben-links** und **BR** auf die
   **Mitte der Zelle unten-rechts** deines Puzzle-Felds. Die 24 Vorschau-Punkte
   sollten dann auf den Zellmitten liegen.

**Optionale Sonderpunkte** (nur nötig, wenn nötig): Über die Kästchen oben kannst
du vier Spezial-Punkte einzeln aktivieren und an die richtige Stelle ziehen:

| Marker    | Bedeutung                                       |
| --------- | ----------------------------------------------- |
| **Color** | Stelle, an der die Stein-**Farbe** gelesen wird |
| **Piece** | Stelle „neuer Stein / Feld voll"                |
| **OK**    | **Bestätigen / Wegwerfen**-Punkt                |
| **Cake**  | **Belohnungs**-Punkt                            |

**Abschließen:** **Enter** (oder **„Confirm"**) speichert die Markierung und
schaltet automatisch auf den Modus **Mark**. **Esc** (oder **„Cancel"**) bricht
ab, ohne etwas zu ändern. Die Markierung wird **auflösungsunabhängig** gespeichert.

> **Referenzbild als Vorlage:** Unter `images/calibration_reference.png` liegt ein
> annotiertes Beispielbild, das die **24 Rasterpunkte** und die **4 Sonderpunkte**
> auf einem sauberen Puzzle-Screenshot zeigt — schau es dir an, dann ist klar,
> was wohin gehört. (Das Bild lässt sich mit `python make_reference.py` neu
> erzeugen.)

> **Hinweis:** Das Overlay braucht eine echte Windows-Oberfläche. Auf einem
> System ohne Anzeige (z. B. reine Test-/Build-Umgebung) öffnet es sich nicht.

---

## 6. Wenn das Puzzle stoppt: Live-Log / `puzzle_debug.log` lesen

Das Live-Log steht direkt im Fenster; zusätzlich liegt `puzzle_debug.log` neben
der EXE. Achte auf:

| Logzeile                                                               | Bedeutung / Maßnahme                                                                                                                                                                                |
| ---------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Stein-Farbe erkannt \| piece_type=...`                                | Alles gut — Stein wurde erkannt.                                                                                                                                                                    |
| `Stein-Farbe nicht erkannt \| ... b=.. g=.. r=..` + `PIECE_COLOR_MISS` | Stein **nicht** erkannt. **b=g=r nahe 0** → Fenster falsch positioniert / Auflösung falsch. **Plausible Farbe** → Color-Sampling auf **Multi** stellen, sonst BGR-Bereiche in `puzzle.py` anpassen. |
| `Detection fallback \| mode=... reason=...`                            | Auto/Mark-Detection hat nicht gegriffen → es wird die **Default-Position** genutzt. Modus prüfen oder neu **Mark**-en.                                                                              |
| `Puzzle-Region ungueltig -> Stop. Ursachen: ...`                       | Positions-/Auflösungsproblem. Auflösung 800×600? Fenster verschoben?                                                                                                                                |
| `Spielfeld voll, aber Truhe NICHT gefunden`                            | `images/fish_jigsaw_chest.png` passt nicht zum Client, oder keine Truhe im Inventar.                                                                                                                |
| `Puzzle-Crash in runHack` + Traceback                                  | Unerwarteter Fehler mit vollem Stacktrace — diesen Block melden.                                                                                                                                    |

---

## 7. Tests selbst laufen lassen (optional)

```bash
python -m unittest discover -s tests -v
```

Erwartung: `Ran 126 tests ... OK`. (Diese Tests prüfen reine Logik —
Solver, KI-Solver, Config, Farb- und Board-Erkennung — ohne GUI/Windows.)

---

## 8. Virenwarnung (False Positive) — Nutzer-Aufgaben & ehrliches Restrisiko

Selbstgebaute Bots aus PyInstaller werden von Microsoft Defender & anderen
Scannern **regelmäßig generisch geflaggt** (z. B. `Trojan:Win32/Wacatac.*`,
`Sabsik`, `Wacapew`). Das ist **fast immer ein False Positive**: PyInstaller-
Stubs, fehlende Code-Signatur und Eingabe-/Screen-Capture-Verhalten triggern
die Heuristik — **nicht** tatsächlicher Schadcode.

### Was dieser Build bereits dagegen tut

- **Kein UPX** (`upx=False`) — UPX-gepackte EXEs sind ein Haupt-Trigger.
- **Echte PE-Metadaten** (Firmenname, Produkt, Version, Copyright).
- **Gepinnte, reproduzierbare** Abhängigkeiten.

Das senkt die FP-Rate, **eliminiert sie aber nicht garantiert** (siehe
Restrisiko unten). Die Portable ist eine **Single-File-EXE** (entpackt sich beim
Start selbst) — der bequemste Weg für Nutzer, kann aber etwas eher die Heuristik
triggern als ein entpackter Ordner; die Gegenmaßnahmen unten gelten.

### Deine Aufgaben als Verteiler/Nutzer

1. **Selbst gegenprüfen — VirusTotal.** Lade die `Metin2FishBot.exe` hoch:
   <https://www.virustotal.com/gui/home/upload> — so siehst du, **welche**
   Engines anschlagen. Bei reinen FPs sind es meist nur wenige, namhafte
   Engines bleiben sauber.

2. **False Positive bei Microsoft melden** (entfernt die Warnung für alle
   Nutzer, meist binnen Tagen). Formular „Submit a file for malware analysis":
   <https://www.microsoft.com/en-us/wdsi/filesubmission>
   - Dort **„Microsoft Defender" / „Incorrectly detected as malware (False
     Positive)"** wählen, Datei hochladen, kurzen Hinweis ergänzen
     („Open-source PyInstaller-built game helper, no malicious payload").
   - Fehlklassifikationen anderer Hersteller ggf. analog über deren
     FP-Meldeformulare einreichen (Link je Hersteller).

3. **Optional, aber am wirksamsten: Code-Signing.** Ein **Code-Signing-
   Zertifikat** (idealerweise **EV**, für sofortige SmartScreen-Reputation)
   signiert die EXE und lässt die meisten Warnungen sofort verschwinden:
   `signtool sign /fd sha256 /a /tr http://timestamp.digicert.com /td sha256 dist_onefile\Metin2FishBot.exe`
   Zertifikate gibt es bei den bekannten CAs (DigiCert, Sectigo, …).

4. **Falls du die Warnung lokal überstimmen musst:** den Programmordner in
   Defender als **Ausnahme** hinzufügen (_Windows-Sicherheit ▸ Viren- &
   Bedrohungsschutz ▸ Einstellungen verwalten ▸ Ausschlüsse_). Nur tun, wenn du
   der Quelle vertraust (eigener Build).

### Ehrliches Restrisiko

- **Eine FP-Warnung kann trotz aller Maßnahmen auftreten.** Ohne gültige
  Code-Signatur bleibt insbesondere **SmartScreen** („unbekannter Herausgeber")
  möglich; manche AV-Heuristiken flaggen PyInstaller-EXEs prinzipbedingt.
- **Garantierte FP-Freiheit gibt es nur mit (EV-)Code-Signing** und – bei
  SmartScreen – erst nach aufgebauter Reputation. Das kostet (Zertifikat) und
  liegt außerhalb dessen, was der Build allein leisten kann.
- **Die Detection-Module** (Screen-Capture, Mausklicks, Auto-Detection) sind
  Windows-abhängig und konnten in der Build-Umgebung nur **kompiliert**, nicht
  am laufenden Spiel getestet werden → bitte **einmal real verifizieren**
  (loggt jeder Stein `Stein-Farbe erkannt`? Laufen Angeln **und** Puzzle?).
- **Eine Datei:** Die Portable ist **eine** `.exe` — einfach genau diese Datei
  weitergeben (keine Begleitdateien nötig).
- **`config.json`** liegt neben der EXE und merkt sich deine Einstellungen.
  **`puzzle_debug.log`** wird pro Start neu angelegt — zum Festhalten eines
  Fehlers vorher wegkopieren.

---

_Build-Härtung: upx=False, Portable (onefile), PE-Versions-Ressource, gepinnte
Deps. Angel-Teil bewusst byte-stabil._
