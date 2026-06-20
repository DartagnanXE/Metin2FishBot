# Changelog

Alle nennenswerten Aenderungen an diesem Projekt werden hier festgehalten.
Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

## [1.3.3] — 2026-06-20

### Energiesplitter: unbegrenzter Lauf (`max_actions=0`) + „Geld leer"-Hinweis

- **`max_actions=0` = UNBEGRENZT** (Default). Vorher wurde 0 auf `max(50, 3×stack_count)`
  „auto-abgeleitet" → der Lauf stoppte nach ~50 Aktionen mitten in der 2. Runde
  („kauft 20, verarbeitet, kauft 10, stoppt"). Der Dolch-Lauf ist bewusst
  open-ended und läuft jetzt Runde für Runde, **bis die Hammer-Stacks im Beutel
  aufgebraucht sind** (`_count_hammers()<=0 → done`) oder das **Geld/Yang ausgeht**
  (wirkungsloser Kauf → `buy_unverified`-Stop). Ein positiver Wert bleibt als
  harter Opt-in-Cap. Backstops (Hammer-Erschöpfung, `consecutive_unverified_stop`)
  bleiben aktiv.
- **Slot-Wechsel beim Stack-Verbrauch** wird weiterhin korrekt gehandhabt: der Bot
  liest Hammer-/Dolch-Slots **jede Aktion live** (`find_inventory_item`,
  `count_item`, Inventar-Diff) — wird ein Hammer-Stack leer, nutzt der nächste Scan
  automatisch den nächsten Stack, und ein frei gewordener Slot wird beim Kauf
  korrekt als neuer Dolch-Slot erkannt (kein gecachtes Slot-Layout, das driften
  könnte).
- **„Kein Geld"-Hinweis:** Bleibt ein Kauf trotz freiem Slot wirkungslos, loggt der
  Bot jetzt „evtl. kein Yang/Geld mehr" → der Stopgrund ist im Log lesbar.

### Puzzle: unbegrenzte Neustarts + schnellere Leer-Erkennung

- **Unbegrenzte produktive Neustarts:** Der Reopen-Zähler (`_box_reopen_tries`) wird
  bei **jedem erfolgreich gelesenen Stein auf 0 zurückgesetzt** → er zählt nur noch
  **aufeinanderfolgende** Neustarts OHNE Fortschritt (= echtes „Boxen aufgebraucht").
  Vorher akkumulierte er über die ganze Session → der Bot stoppte schon **nach dem
  1. Nachlegen**, obwohl er danach noch normal weiterspielte. Jetzt: unendliche
  Durchläufe, bis wirklich alles leer ist (verifiziert) oder gestoppt wurde.
- **Schnellere Leer-Erkennung:** `PIECE_COLOR_RETRY_S` 2.0 → 1.0 s. Das Retry-Fenster
  wurde NUR bei leeren Boxen voll ausgereizt (bei einem echten Stein endet es nach
  dem ersten gerenderten Frame) → die Leer-Erkennung war unnötig träge. 1.0 s ist
  ggü. ~0.3 s Renderzeit noch >3× Polster; der Streak=2-Debounce fängt einen
  einzelnen Aussetzer weiterhin ab.

## [1.3.2] — 2026-06-20

### Fix: Reopen klickte auf den Spaltenkopf „Name" statt auf den FISCHPUZZLESPIEL-Button

Der v1.3.1-Reopen lief korrekt durch (Strg+E → Übersicht → Klick), startete das
Puzzle aber **nicht** — das SOTA-Debug (`REOPEN_OK | overview_still_open=True`)
machte es sichtbar.

- **Ursache:** Das Erkennungs-Template `flow_fisch_label.png` war aus der
  **falschen Zeile** geschnitten — es enthielt den Spaltenkopf **„Name"**
  (ROI y=108–130) statt der Button-Beschriftung **„FISCHPUZZLESPIEL"** (y=139–151,
  eine Zeile tiefer). Der Klick (NCC=1.0) landete also exakt auf „Name" → die
  Eventübersicht blieb offen, das Spiel startete nie.
- **Fix:** Template neu aus der echten „FISCHPUZZLESPIEL"-Button-Beschriftung
  geschnitten (Self-NCC 1.0, nächstbester Fremd-Treffer 0.58 → Schwelle 0.82 mit
  Reserve). Die Vollbild-NCC-Suche findet den Button weiterhin **positions-
  unabhängig** im ganzen Übersichts-Bereich (wie beim Seherspiel) — Sortierung
  egal.
- **Ehrliche Erfolgs-Verifikation:** Ein Reopen gilt nur noch als erfolgreich,
  wenn das Brett offen **und die Eventübersicht wieder geschlossen** ist. Das rein
  strukturelle „Brett offen?" meldete bisher auch die noch offene Übersicht als
  „offen" → falsches REOPEN_OK. Ein Fehlklick wird jetzt als `REOPEN_BOARD_MISS`
  (mit `overview_still_open`) korrekt erkannt statt als Erfolg verbucht.

## [1.3.1] — 2026-06-20

### Fix: Box-leer-Neustart lief nie (öffnete das Eventboard nicht, klickte ins Leere)

- **Ursache:** Im Box-leer-Pfad rief der Bot `_open_puzzle_game()`, das als
  ersten Schritt „Brett schon offen?" prüft und dann abbricht. Diese Prüfung
  (`validate_puzzle_region`) ist aber **rein strukturell** und meldet **jede**
  brett-förmige Region als „offen" — auch das gerade per ESC geschlossene/leere
  Brett. Folge: der Strg+E-→-Eventliste-→-Klick-Flow wurde **komplett
  übersprungen**, der Bot lief im Normalloop weiter und klickte `getpiece` ins
  Leere, bis er am Garbage-Board stoppte.
- **Fix:** Nach dem ESC wird der Neustart jetzt **erzwungen**
  (`_open_puzzle_game(force=True)`) — der „schon offen?"-Kurzschluss wird im
  Box-leer-Pfad übersprungen, der Eventlisten-Neustart läuft garantiert. Der
  Selbststart (Brett zu beim Start) behält die alte „nicht doppelt öffnen"-
  Semantik.
- **SOTA-Debug:** Jeder Reopen-Schritt schreibt jetzt einen strukturierten
  `SNAP`-Block (`REOPEN_BEGIN` / `_NO_OVERVIEW` / `_NO_LABEL` / `_OK` /
  `_BOARD_MISS`) mit den **rohen Best-NCC** aller Flow-Templates + Anker/Spielfeld;
  jeder Strg+E-Versuch loggt die gemessene Titel-NCC. Bei erneutem Fehlschlag
  steht im Log exakt der Schritt **und** der Grund (Übersicht nicht erkannt?
  Label unter Schwelle? Klick lieferte kein Brett?).
- Nebenbei: Log-Zeilen zeigten Roh-Platzhalter (`#{streak}/{threshold}`) statt
  Werten — Format wird jetzt korrekt eingesetzt.

## [1.3.0] — 2026-06-20

### Fisch-Puzzle: startet das Spiel selbst + füllt Boxen per Event-Neustart (kein Inventar-Scan/Drag mehr)

Komplett neuer, viel robusterer Weg — **ohne** die fehleranfällige „Inventar-offen?"-Prüfung und **ohne** Drag.

- **Der Bot startet das Puzzle jetzt selbst.** Beim Start prüft er, ob das Brett
  schon offen ist; wenn nicht, öffnet er es über die **Eventübersicht** (Strg+E →
  „FISCHPUZZLESPIEL" robust per Bild-Erkennung finden — Sortierung/Position egal —
  → auf den **Namen** klicken, nicht auf „Ansehen" → Brett-offen verifizieren).
  Kein harter Abbruch mehr nur, weil das Brett zu war.
- **Leere Boxen werden per Spiel-Neustart nachgefüllt:** sind die Standard-Boxen
  leer, drückt der Bot **ESC** und öffnet das Spiel erneut über die Eventübersicht
  → Boxen sind wieder gefüllt (sofern vorhanden). Sind sie danach immer noch leer,
  **stoppt** der Bot mit klarer Debug-Meldung „Puzzle-Boxen leer". Ein Reopen-Cap
  verhindert eine ESC↔Öffnen-Endlosschleife.
- **Erkennung-vor-Aktion:** Doppel-Guard (Übersicht-Titel **und** das
  „FISCHPUZZLESPIEL"-Label müssen matchen), sonst kein Klick. Jeder Fehlschritt
  schreibt eine Diagnose (rohe Best-NCC + Debug-Frame) ins Log. Am Event-Bild
  gemessen: Label-Self-NCC **1.00**, nächster Fremd-Treffer **0.49** → Schwelle
  0.82 mit großem Abstand.
- **Box-Nachlegen über Inventar-Scan/Drag komplett entfernt** (Standard **und**
  Deluxe-Refill) — inkl. der alten, auf manchen Clients kaputten „Inventar-offen?"-
  Probe, der GUI-Schalter, Config und i18n. **Deluxe-Spielen** (force_deluxe-
  Platzierung) bleibt unverändert.

**Validierung:** 352 berührte Tests grün (11 neue: Selbststart, Event-Öffnen,
Restart-Refill, „Boxen leer"-Stop). **Restunsicherheit:** die Bild-Schwelle der
„FISCHPUZZLESPIEL"-Erkennung ist am echten Client ggf. nachzujustieren (headless
nicht final prüfbar) — Debug-Logs zeigen jeden Knapp-daneben-Fall.

## [1.2.38] — 2026-06-20

### Eingabe-Mechanik aufgeräumt: Zwei-Klick statt Drag — aber nur wo es sicher ist

Grundwahrheit (User): Items werden per **Zwei-Klick** gesetzt — Linksklick auf die
Quelle (aufnehmen), Linksklick aufs Ziel (setzen) — kein Drag&Drop. Beim Scannen
des Codes zeigte sich aber: **nicht jeder Drag ist gleich.** Entscheidend ist das
Ziel:

- **Slot → UI-Slot (sicher → auf Zwei-Klick umgestellt):**
  - **Energiesplitter** Hammer → Dolch (`_two_click_move`): aufnehmen + setzen,
    kein hängender Mausknopf. Gleichzeitig die Basis für die geplante
    seitenübergreifende Verarbeitung (Zwei-Klick funktioniert über einen
    Seitenwechsel hinweg).
  - **Puzzle-Box-Nachlegen** Box → Box-Slot (`refill.two_click_place`).
- **Slot → 3D-Welt (bewusst weiter als Drag — sicherer):**
  - Item **wegwerfen** (auf den Boden) und **Fisch aufs Lagerfeuer** bleiben Drag.
    Ein zweiter Klick in die 3D-Welt würde — falls die Aufnahme mal nicht greift —
    die **Figur loslaufen lassen**. Drag vermeidet das. (Das ist der Grund, warum
    „überall Zwei-Klick" hier *nicht* sauberer wäre.)
- **Fischen unangetastet** (Köder-Nachfüllung nutzt dieselbe geteilte `drag` —
  bewusst nicht verändert).

### Außerdem
- **Campfire-Vogelperspektive** finalisiert: statt des fragilen `g`-Tasten-Holds
  jetzt dieselbe **Rechtsklick-Drag-Geste** wie beim Energiesplitter (zuverlässige
  Top-Down-Kamera, client-unabhängig). (Kamera-Geste — kein Item-Move, bleibt
  daher Drag.)

328+ Tests grün (neu: Zwei-Klick-Move statt Drag + Gate-Schutz; Box → Box-Slot
per Zwei-Klick). Hinweis: die Zwei-Klick-Umstellung ist am Live-Client noch
gegenzuprüfen (Aufnahme-Klick muss den Stack greifen) — die Re-Read-Verifikation
stoppt sicher, falls nicht.

## [1.2.37] — 2026-06-20

### Energiesplitter (Dolch): „kauft 20, verarbeitet 1, stoppt" behoben + Default 20

- **Der Bot verarbeitet jetzt die GANZE Runde.** Bei `daggers_per_round = 20`
  kaufte er 20 Dolche, verarbeitete **1** und stoppte mit `process_unverified`.
  Ursache: ein Anti-Drift-Riegel verglich *kumulativ gekaufte* mit *verarbeiteten*
  Dolchen (`gekauft − verarbeitet > 2`). Nach Batch-Kauf von 20 ist das nach dem
  ersten Verarbeiten 20 − 1 = 19 > 2 → sofortiger Fehl-Stop (trat bei jeder
  Rundengröße ≥ 4 auf; bei 1–3 blieb es unsichtbar). Der Riegel ist **entfernt** —
  echte Fehl-Verarbeitung fängt weiterhin der bestehende Schutz (Stop nach
  `consecutive_unverified_stop` Fehlversuchen **in Folge**; ein Erfolg setzt den
  Zähler zurück). Damit läuft **kaufen → alles verarbeiten → nächste Runde**
  korrekt für jede Rundengröße.
- **Default `daggers_per_round` ist jetzt 20** (vorher 1). Bestehende
  gespeicherte Werte bleiben erhalten — der neue Default greift für neue Configs.
- **Dolch-Erkennung über alle Leucht-Zustände bestätigt** (kein Code nötig): an
  20 echten Bildern gemessen — frisch gekaufte Dolche **leuchten** (4 Eck-Blooms),
  trotzdem trennt die Icon-Erkennung konfusionsfrei (Dolch-glühend 0.76–0.82,
  Dolch-normal 1.00, Hammer ≤ 0.52, leer 0.19; Schwelle 0.70). Der Glow war
  **nicht** die Stopp-Ursache.
- 1 neuer Regressionstest (20er-Runde ohne Fehl-Stop). 291 grün.

## [1.2.36] — 2026-06-20

### Energiesplitter: Inventar vereinheitlicht — 45 Slots (9 Zeilen) + zahl-robuste Item-Erkennung

Zwei strukturelle Inventar-Bugs behoben (am echten Bild gemessen):

- **Inventar ist 5×9 = 45 Slots, nicht 40.** Der Bot modellierte nur 8 Zeilen
  (40 Slots) und war damit **blind für die 9. (unterste) Zeile**: freie Plätze
  wurden unterzählt, und Hämmer/Dolche/Lande-Slots in Zeile 9 wurden übersehen
  (mögliche Fehl-Stops „kein Platz"/„unverifiziert"). Jetzt **45 Slots** durchweg
  — an einer vollen Hammer-Seite bestätigt (Zeilen 1–9 belegt, Zeile 10 leer).
- **Item-Erkennung ist jetzt unabhängig von der Stack-Zahl.** Das alte Voll-
  Zellen-Template nahm die eingeblendete Stückzahl mit ins Matching → bei
  **größeren Zahlen brach die Erkennung ein** (gemessen: NCC 0.93 bei normaler
  Zahl, **0.57 bei großer → 0 Hämmer erkannt** → der Bot hätte „keine Hämmer"
  gemeldet und gestoppt). Jetzt wird **nur die Icon-Region** verglichen (das
  Zahl-Band unten ist maskiert) → **beide Fälle 1.00**, Diskriminierung bleibt
  (leerer Slot 0.18, Fremd-Item 0.52). Greift einheitlich für alle Slot-Checks
  (Bestand, freie Plätze, Lande-Slot, Drag-Quelle/Ziel).
- Grundlage für die geteilte Inventar-Wahrheit (ein Inventar für alle Modi): die
  Lager-Geometrie ist dieselbe Form (5×9), nur ein anderer Ursprung — für die
  spätere Lagerverwalter-Session festgehalten.
- 7 neue Tests (45 Slots voll/leer, 9. Zeile, Zahl-Unabhängigkeit an großer-Zahl-
  Seite). 220 grün.

## [1.2.35] — 2026-06-20

### Energiesplitter: Inventar-Offen-Erkennung jetzt offset-tolerant (der eigentliche Fix)

- **v1.2.34 hat das Symptom nicht behoben** — der Bot meldete weiter sofort
  `inventory_not_open`, obwohl die Tasche offen war. Grund: der Live-Kamera-Frame
  ist NICHT einfach „Vollfenster mit Titelleiste"; die Annahme aus v1.2.34 traf
  den Live-Fall nicht.
- **Wahre Ursache.** Die alte „Tasche offen?"-Prüfung war eine **pixel-genaue
  Reiter-Template-Probe** (±3 px). Der Live-Capture verschiebt das Bild je nach
  Fenster-/DWM-Rahmen um ein paar Pixel — genug, um die Reiter-Reihe aus der
  ±3 px-Toleranz zu schieben → 0/4 → fälschlich „zu". Die eigentlichen
  Energiesplitter-Erkenner (NPC, Raster, Shop) liefen dagegen **pixelgenau live**
  — sie nutzen die kalibrierte Raster-Geometrie, mit der der Live-Frame
  nachweislich übereinstimmt (der Bot kaufte Dolche exakt an den Raster-Slots).
- **Fix.** Neue, **template-freie, offset-tolerante** Erkennung
  `detect.inventory_open`: misst die **periodische 32 px-Slot-Struktur** des
  Rasters (Rand- vs. Mitte-Helligkeit) in **Spalten UND Zeilen** und nimmt das
  Maximum → erkennt **volle** (Spalten-Kontrast) wie **spärliche** (Zeilen-
  Kontrast) Taschen. An den echten Bildern gemessen: **zu ≤ 6,7 / offen ≥ 26,3**
  → Schwelle 15 trennt mit großem Abstand in beide Richtungen. Nutzt dieselbe
  Raster-Geometrie wie die live bewährten Slot-Detektoren — kein Reiter-Pixel-
  Risiko mehr. Ist die Tasche zu, wird wie bisher die Inventar-Taste gedrückt und
  erneut geprüft.
- Die alte Angel-Reiter-Probe (inkl. `_client_shot`/Inventar-Paket-Import) ist
  raus. 6 neue/ersetzte Tests (volle + spärliche offene Tasche, geschlossener
  NPC-Dialog, Toggle-dann-offen, bleibt-zu-Stop). 216 grün.

## [1.2.34] — 2026-06-20

### Energiesplitter: „Inventar nicht erkannt / Tasche konnte nicht geöffnet werden" behoben (Titelleisten-Offset)

- **Symptom.** Nach dem Aufräumen des (vollen) Inventars stoppte der Bot sofort
  mit `inventory_not_open` — „Tasche konnte nicht geöffnet werden" —, obwohl das
  Inventar **offen** war.
- **Ursache.** Die Inventar-„offen?"-Prüfung nutzt die bewährte Angel-Open-Probe
  (Abgleich der vier Seiten-Reiter I–IV). Diese externe Probe bekam ein **rohes
  Kamera-Bild inklusive der ~31 px Windows-Titelleiste** und tastete die
  Reiter-Reihe dadurch **31 px zu weit oben** ab → 0 von 4 Reitern erkannt →
  fälschlich „zu". Die eigentlichen Energiesplitter-Detektoren normieren intern
  selbst auf den 800×600-Client — **nur die Open-Probe nicht**.
- **Fix.** Die Open-Probe bekommt jetzt ein **auf den 800×600-Client normiertes
  Bild** (Titelleiste/Rahmen entfernt). Am echten Screenshot belegt: roh **0/4**
  (zu) → normiert **3/4** (offen). Die Normierung ist idempotent — ein bereits
  korrekt zugeschnittenes Bild bleibt unverändert, der bisher funktionierende
  Fall ändert sich nicht.
- 3 neue Tests (Titelleisten-Normierung + End-to-end-Offen-Erkennung am echten
  Vollfenster-Bild + Gegenprobe roh-vs-normiert).

## [1.2.33] — 2026-06-20

### Energiesplitter (Dolch-Modus): Zerlege-Bestätigung + „hört bei vollem Beutel auf zu kaufen"

- **Zerlege-Bestätigungsfenster wird jetzt bejaht.** Beim Hammer→Dolch-Drag
  öffnet Metin2 den Dialog „Möchtest du das wirklich zerlegen?" (Ja/Nein) —
  bisher fälschlich als „KEIN Bestätigungsfenster" angenommen. Ohne Klick auf
  **Ja** blieb der Dolch unverarbeitet → Stopp `process_unverified`. Der Bot
  erkennt den Dialog jetzt robust an seinem **Ja-Knopf** (gleiches Asset wie die
  Kauf-Bestätigung, nur ~41 px tiefer wegen 4 statt 2 Textzeilen; NCC 0,99,
  ROI deckt beide Höhen ab) und klickt **immer sofort Ja** — wie bei den anderen
  Bestätigungsfenstern dieser Art. Kontext-gegated (nur direkt nach dem Drag),
  kein Fehlauslösen in Shop/Spielwelt (am echten Screenshot belegt).
- **Kein falscher Abbruch mehr bei vollem Beutel.** Im Live-Log stoppte der Bot
  bei 11/20 Dolchen mit `buy_unverified`: war der Beutel voll, hatte der nächste
  gekaufte Dolch **keinen Lande-Slot** → Inventar-Diff `None` → Hard-Stop.
  Jetzt erkennt der Bot „Beutel voll" **vor** dem Kauf und **verarbeitet die
  bereits gekauften Dolche** (Zerlegen schafft Platz), statt abzubrechen — und
  kauft in den Folgerunden weiter, bis die Hämmer aufgebraucht sind. Nur wenn von
  Anfang an **nichts** gekauft wurde und der Beutel voll ist, gibt es einen
  ehrlichen `no_space`-Stop.
- 7 neue Tests (Zerlege-Dialog-Erkennung + Ja-Klick + voller-Beutel-verarbeitet-
  statt-Stopp + Process-Drag-klickt-Ja). Gesamt grün.

## [1.2.32] — 2026-06-17

### Box-Nachlegen: blockierende „Inventar offen?"-Prüfung ersetzt (jetzt template-frei)

- **Nächster Blocker behoben.** Nach v1.2.31 erkannte der Bot die Box zwar, kam
  aber **gar nicht so weit**: die alte „Inventar offen?"-Prüfung (über Tab-
  Vorlagen) scheiterte auf dem Client und meldete „Inventar nicht als offen
  verifizierbar → kein Nachlegen" — der Box-Finder lief nie an.
- **Fix: template-freie Offen-Erkennung.** Statt der Tab-Vorlagen prüft der Bot
  jetzt die **periodische Slot-Struktur** des Inventars (Slot-Ränder sind alle
  32 px deutlich dunkler als die Slot-Mitten). Am echten Bild gemessen:
  **offen Differenz ≈ 38, Spielwelt ≈ 3,5** → glasklare Trennung (Schwelle 15).
- **Robustes Öffnen mit Toggle.** Ist die Tasche zu, drückt der Bot (mit Fokus)
  die Inventar-Taste und prüft erneut — er klickt **nicht mehr blind** in
  geschlossene Tabs/in die Spielwelt. End-to-end am echten Screenshot bewiesen:
  Offen-Check → Box (Slot 23) gefunden → Drag ausgeführt.
- 6 neue Tests (Offen-Erkennung + Öffnen-dann-Ziehen + „bleibt zu → keine
  Blind-Klicks").

## [1.2.31] — 2026-06-17

### Box-Nachlegen: Puzzle-Boxen werden im Inventar jetzt zuverlässig erkannt

- **Echte Ursache gefunden (aus deinem Inventar-Screenshot kalibriert).** Das
  Nachlegen scannte zwar alle 4 Seiten, **erkannte aber keine einzige Box** und
  stoppte mit „Boxen aufgebraucht" — obwohl die Boxen auf Seite IV lagen. Zwei
  Gründe, beide behoben:
  1. Die automatische Raster-Ausrichtung lag **~10 px daneben** → Slots wurden
     versetzt abgetastet. Jetzt wird das **feste, kalibrierte Raster** genutzt.
  2. Die Box trägt eine **große Stückzahl** (z. B. 57/104/200) in der **unteren
     Icon-Hälfte** → das Voll-Icon passte nicht (Abweichung 41 statt <22). Jetzt
     wird **nur die obere Icon-Hälfte** abgeglichen (die Zahl wird ignoriert).
- **Am echten Screenshot bewiesen:** Standard-Box-Treffer mit Abweichung **≈ 1,0**
  (perfekt), alle Nicht-Box-Slots **≥ 39** → eindeutige Trennung. Der Finder
  erkennt im Bild korrekt die Standard-Boxen (Slot 23) und die Deluxe-Box (Slot 26).
- Eigener, client-robuster Box-Finder (ersetzt für das Nachlegen den allgemeinen
  Inventar-Scan, der auf dem Client nichts erkannte). 4 neue Tests inkl.
  „erkennt trotz aufgedruckter Stückzahl".

## [1.2.30] — 2026-06-17

### Puzzle-Solver: durchgehend optimal bis zum Schluss (Finish-Modus entfernt)

- **Echter Logik-Fehler gefunden & behoben (vom Nutzer gemeldet).** Wenn unten nur
  noch ein **1-Zug-Loch** offen war (z. B. ein L mit 3 Feldern), legte der Bot nach
  langem Warten einen _fragmentierenden_ Stein (z. B. ein Einzelfeld) und erzeugte
  damit **2 Einzelfelder → 1 Zug/Stein mehr** als nötig. Ursache: ein „Finish-
  Modus", der nach vielen Verwerfen einen suboptimalen Stein **erzwang**.
- **Fix: Finish-Modus komplett entfernt.** Der Bot spielt jetzt **durchgehend die
  beweisbar optimale Strategie** — er legt einen Stein **nur**, wenn das die
  erwartete Steinzahl bis zum Sieg **strikt senkt**, sonst wartet er auf den
  richtigen Stein. **Minimale Steine zu jeder Zeit, keine künstlichen Grenzen.**
- **Per Monte-Carlo bewiesen (50.000 Spiele):** die Policy erreicht **exakt** das
  vorhergesagte Optimum (15,58 ≈ V[leer]=15,57 Steine), **0 Steckenbleiber**. Der
  alte Finish-/Immer-legen-Ansatz verbrauchte **22 % mehr Steine**.
- Sicherheits-Backstop gegen ein echtes Hängen (Stein wird dauerhaft fehl-erkannt)
  auf **120** Verwerfen-in-Folge kalibriert — greift laut Monte-Carlo **nie** ins
  legitime optimale Warten ein (max. ~62 in 1/100.000 Spielen). Neuer
  Optimalitäts-Regressionstest verhindert künftige Verschlechterungen.

## [1.2.29] — 2026-06-17

### Deluxe-Box: reaktive Erkennung statt Zahl-Lesen — wird jetzt zuverlässig genutzt

- **Ursache gefunden (aus deinem Screenshot + Log):** Die alte Logik las pro Zug
  eine **Stückzahl direkt auf dem Box-Slot** — die es bei leerer/normaler Box
  **gar nicht gibt** (die „Anzahl" steht in einem separaten Feld unten). Ergebnis:
  Erkennung las immer **0** → Deluxe-Box wurde **nie geöffnet**. (Die Klick-
  Koordinaten `(503,271)`/`(503,328)` waren laut Screenshot korrekt — nur die
  Zahl-Lesung war falsch.)
- **Neue, reaktive Strategie (wie gewünscht, ohne Speed-Nachteil):** Der Bot liest
  **keine** Box-Zahl mehr pro Zug. Stattdessen: liegt ein freies 2×3-Loch, **öffnet
  er einfach die Deluxe-Box** (sie ist „fast immer" voll) und legt den Magenta-
  2×3-Stein. **Erst wenn nichts kommt** (kein Magenta), erkennt er den Slot als
  **leer** und reagiert: **Box aus dem Inventar nachlegen** (falls aktiviert) — und
  wenn keine mehr da ist, **schaltet er Deluxe einfach ab und spielt normal
  weiter** (kein Stopp). Keine ständige Prüfung = kein Geschwindigkeitsverlust.
- Debug-Log entsprechend aktualisiert (`Deluxe-Box öffnen …`, `Slot ist LEER …`,
  `aus Inventar nachgelegt …`, `Deluxe abgeschaltet …`).

## [1.2.28] — 2026-06-17

### Fix: „KI optimiert" friert beim ersten Start nicht mehr ~19 s ein

- **Ursache des „Hängens beim ersten Start" gefunden.** Die KI-Wertfunktion
  (über alle 16,7 Mio Brettzustände) wurde beim **allerersten** „KI optimiert"-Zug
  **live berechnet** (~19 Sekunden) — solange wirkte der Bot **eingefroren**. In
  der portablen EXE war die vorberechnete Datei nicht enthalten, also passierte das
  bei jedem frischen Start (bzw. dauerhaft, wenn der Ordner nicht beschreibbar ist).
- **Fix:** Die Wertfunktion ist jetzt **vorberechnet und komprimiert in der EXE
  gebündelt** (`trained_V.npz`, ~13 MB) und lädt in **~0,2 s** statt 19 s zu
  rechnen. Zusätzlich wird sie **beim Puzzle-Start einmalig vorgeladen** (mit
  Log-Meldung), sodass der erste Zug sofort kommt. Kein Einfrieren mehr.

## [1.2.27] — 2026-06-17

### Force Deluxe: Deluxe-Box wird endlich genutzt (opportunistisch + Diagnose)

- **Grundlegender Umbau der Deluxe-Logik.** Bisher reservierte „Force Deluxe" ein
  festes 2×3-Feld und wartete — das blieb im Log **hängen**, sobald die Box-Zahl-
  Erkennung 0 las: die Deluxe-Box wurde **nie geöffnet**, der Solver füllte
  stattdessen das ganze Brett und verwarf endlos. Jetzt arbeitet der Bot
  **opportunistisch, genau wie gewünscht**: Sobald **irgendwo ein freies 2×3-Loch**
  auf dem Brett liegt **und eine Deluxe-Box verfügbar** ist, öffnet er die
  Deluxe-Box und füllt das Loch mit dem **Magenta-2×3-Stein** (deterministischer
  6-Zellen-Fit = der beste Zug). Kein starres Reservat mehr.
- **Endlich Diagnose im Log.** Bei jeder Prüfung steht jetzt: `Deluxe-Prüfung:
freies 2x3-Loch bei …, Deluxe-Boxen gelesen=N` — damit ist **sofort sichtbar**,
  ob der Bot eine Deluxe-Box erkennt (das war bisher völlig unprotokolliert und der
  eigentliche Grund, warum „nichts passierte").
- **Schleifen-Sicherung.** Liefert das Öffnen der Deluxe-Box **keinen** Magenta-
  Stein (Slot war doch leer), zählt der Bot das, und nach 2 Fehlversuchen schaltet
  er die Deluxe-Nutzung für den Lauf ab und spielt normal weiter — keine Endlos-
  Klicks mehr auf einen leeren Slot.
- Fehlt eine Deluxe-Box im Slot, aber „Boxen automatisch nachlegen" ist an, wird
  eine aus dem Inventar nachgezogen (wie bei den Standard-Boxen).

## [1.2.26] — 2026-06-17

### Fix: Puzzle-Box-Nachlegen öffnet das Inventar jetzt wirklich

- **Bugfix zum Box-Nachlegen (v1.2.25):** Beim Versuch nachzulegen meldete der Bot
  „Inventar nicht als offen verifizierbar" und legte **nichts** nach. Ursache: Das
  Puzzle spielt nur mit **Mausklicks** — das Spielfenster hatte daher **keinen
  Tastatur-Fokus**, und der Inventar-Hotkey (`i`) ging ins Leere → das Inventar
  öffnete nie. Jetzt wird das Spielfenster **vor jedem Hotkey-Druck fokussiert**
  (wie beim Energiesplitter), sodass das Inventar zuverlässig aufgeht.
- **Schnelleres Auslösen:** Das Nachlegen greift jetzt schon nach **2** leeren
  „Stein holen" in Folge (statt 3) — mit dem 2-Sekunden-Farb-Lesefenster pro
  Zyklus wirkte 3 zuvor wie „legt gar nichts nach".
- **Klare Diagnose-Zeile** im Log bei jedem leeren Stein: `Auto-Nachlegen an=…,
Engine=…, Streak=N/2` — macht sofort sichtbar, ob der Schalter aktiv ist.

## [1.2.25] — 2026-06-17

### Fisch-Puzzle: leere Boxen automatisch aus dem Inventar nachlegen (opt-in)

- Neuer Schalter **„Boxen automatisch nachlegen"** (Puzzle-Einstellungen, unter
  „Force Deluxe"). Ist er an und läuft mitten im Spiel eine **Puzzle-Box leer**,
  zieht der Bot selbstständig eine neue Box aus dem **Inventar** in den Box-Slot:
  - **Standard-Box** → unterer Slot, **Deluxe-Box** → oberer Slot (nie vertauscht).
  - Immer der **erste Fund**, gescannt über Inventarseiten **I → IV, Slots 1–45**.
  - Es wird **nur eine sicher erkannte Box** gezogen — niemals ein anderes Item.
  - Das **Inventar wird bei Bedarf geöffnet** (verifiziert; ohne offenes Inventar
    kein Blind-Drag). Sind die Boxen **aufgebraucht** → der Bot **stoppt** mit
    klarer Meldung statt endlos ins Leere zu klicken.
  - **F6/Stop** bricht eine laufende Nachlege-Aktion sofort ab; Obergrenze von
    20 Nachlegungen pro Lauf als Sicherheitsnetz.
- **Default AUS (opt-in):** Drag + Icon-Erkennung sind nur am **echten Spiel**
  verifizierbar. Bitte aktivieren und den **ersten Lauf beobachten**.
- Baut vollständig auf der bereits getesteten Nachlege-Engine (Inventar-Scan +
  Drag) auf, die auch das Köder-Nachlegen beim Angeln nutzt. 24 neue Tests.

## [1.2.24] — 2026-06-17

### Lagerfeuer-Grillen: hartes 35-Sekunden-Limit

- Das gelegte Lagerfeuer ist nur **~35 Sekunden** da — der Bot rechnet jetzt
  **keine Sekunde länger** damit. Ab dem Platzieren läuft eine harte Frist;
  ist sie abgelaufen, wird **nicht weiter gegrillt** (kein Fisch-Drag mehr ins
  Leere, wo kein Feuer mehr ist). Sauberer Abschluss mit dem bisherigen Stand.

## [1.2.23] — 2026-06-17

### Energiesplitter Dolch-Modus: Shop kauft jetzt + ALLE Dolche werden verarbeitet

- **`bag_not_open`-Stopp behoben.** Beim Waffenhändler ging der Shop auf, dann
  stoppte der Bot mit „bag_not_open". Ursache: ein doppelter Taschen-Check
  (`panel_is_bag`) war nicht kalibriert → lieferte immer „nicht offen" → Stopp.
  Entfernt — die Tasche wird ohnehin schon zuverlässig (open_probe) verifiziert.
  Der Dolch-Kauf läuft jetzt durch.
- **Auch bereits vorhandene Dolche werden weggehämmert.** Der Bot verarbeitet
  jetzt **alle Dolche im Inventar** (gekaufte **und** schon vorher vorhandene) —
  aber **NUR Slots, die sicher als Dolch erkannt sind** (NCC-Gewinner unter allen
  Item-Vorlagen). **Niemals ein anderes Item.** Vor jedem Zug wird das Ziel
  zusätzlich erneut als Dolch geprüft (doppelte Sicherheit).

## [1.2.22] — 2026-06-16

### Energiesplitter: NPC-Dialog bekommt Zeit zum Erscheinen (Kauf scheiterte an „Laden öffnen")

- Ein kompletter Tester-Lauf zeigte: NPC erkannt + angeklickt, aber dann
  „Laden öffnen nicht gefunden" (NCC 0.274) → Stopp. Ursache: die Suche nach der
  Dialogzeile lief **~30 ms nach dem NPC-Klick** — der NPC-Dialog war da noch gar
  nicht aufgegangen.
- **Fix:** Nach dem NPC-Ansprechen wartet der Bot jetzt kurz, **bis der Dialog
  erscheint**, und sucht „Laden öffnen" **mehrfach mit Renderpause** (bis 5×),
  bevor er aufgibt.
- **Log-Flut reduziert:** „ZUSTAND: Tick" wird nur noch geloggt, wenn sich
  wirklich etwas ändert (vorher ~80 identische Zeilen während Wartephasen — sah
  eingefroren aus).

## [1.2.21] — 2026-06-16

### Energiesplitter: Shop-Item-Suche mit Render-Retry (Kauf scheiterte „knapp")

- Die ganze Kauf-Kette läuft jetzt durch bis zum Shop (Vogelperspektive → NPC →
  „Laden öffnen" → Shop). Ein Tester sah am Schluss „Hammer nicht im Shop"
  (NCC 0.547), weil der **Shop nach dem Öffnen noch einblendete** und beim ersten
  Blick noch nicht fertig gerendert war.
- **Fix:** Die Item-Suche im Shop (Hammer **und** Dolch) wird jetzt **mehrfach mit
  kurzer Renderpause wiederholt** (bis zu 6×), bevor „nicht im Shop" gemeldet wird
  — fängt das Einblenden zuverlässig ab.

## [1.2.20] — 2026-06-16

### Energiesplitter: Standard ist jetzt SCHARF/Live (direkt testbar)

- Der Energiesplitter startet bei einer **frischen Installation jetzt im
  Scharf/Live-Modus** (statt Simulation) — Tester können direkt loslegen, ohne
  erst einen Schalter umzulegen. Der **„Scharf/Live"-Schalter bleibt** (jederzeit
  auf Simulation zurückstellbar). Die Sicherheits-Backstops bleiben voll aktiv:
  **Erkennung-vor-Aktion** (Kauf/Drag nur auf verifizierte Ziele), das
  **Phase-0-GATE** (kein Klick ohne erkannte Assets/800×600/Kalibrierung), das
  **Aktions-Limit** und **F6**.

## [1.2.19] — 2026-06-16

### Energiesplitter: Kauf-Bestätigung, echte Vogelperspektive (Drag), Dolch-Verarbeitung

- **Kauf-Bestätigung „Ja".** Jeder Shop-Kauf fragt „Möchtest du … kaufen?" — der
  Bot erkennt den Dialog am „Ja"-Knopf (aus deinem Bild kalibriert; self 1.00,
  Shop/Szene ≤ 0.62 → Schwelle 0.85, zusätzlich nur direkt nach einem Kauf-Klick
  geprüft) und klickt **Ja**. Gilt für Hammer- UND Dolch-Kauf.
- **Vogelperspektive jetzt per RECHTSKLICK-DRAG** (deine Methode): Rechtsklick
  gedrückt halten und die Maus in einem Rutsch **25 % der Höhe nach unten** ziehen
  → volle Top-Down-Sicht; erst dann klappt der NPC-Klick zuverlässig. Wird einmal
  pro Lauf gemacht (Kamera bleibt) — gilt für Alchemist + Waffenhändler. Das alte
  „g"-Tasten-Manöver und der zugehörige Schalter sind **komplett raus** (Code +
  Einstellungen).
- **Dolch-Verarbeitung korrekt:** Hammer lässt sich nur bei **geschlossenem**
  Waffenhändler-Laden auf einen Dolch ziehen → der Bot **schließt den Laden (ESC)
  vor dem Ziehen**; für die nächste Runde wird der NPC erneut angesprochen und der
  Laden neu geöffnet (Vogelperspektive bleibt, kein erneutes Kippen).

## [1.2.18] — 2026-06-16

### Update-Helfer bombenfest gemacht (zusätzliche Absicherung zu 1.2.17)

- **Doppelte Fenster-Unterdrückung:** zusätzlich zu `CREATE_NO_WINDOW` wird der
  Helfer jetzt mit `STARTUPINFO`/`SW_HIDE` gestartet — falls je eine exotische
  Windows-/Antivirus-Konfiguration das eine Flag ignoriert, greift das andere.
- **Regressionstest** sichert dauerhaft, dass die Warte-/Kopier-Schleifen des
  Helfers **hart begrenzt** bleiben (kann nie wieder zu einer Endlos-/Fenster-
  Flut werden).
- Voller Code-Scan: der einzige fenster-/prozess-spawnende Pfad war der Update-
  Helfer; `os.startfile` (Log öffnen) und `webbrowser.open` (Releases/Hilfe) sind
  nutzer-initiiert und harmlos.

## [1.2.17] — 2026-06-16

### KRITISCH behoben: Update-Helfer öffnete Dutzende CMD-Fenster (unbeendbar)

- **Beim Update poppten viele schwarze CMD-Fenster auf** (`ping -n 2 127.0.0.1`,
  `find "<PID>"`) und der PC ließ sich nur per Hard-Reset retten. Ursache: das
  Selbstersetzungs-`.bat` wurde mit `DETACHED_PROCESS` gestartet → das `cmd` hatte
  **gar keine Konsole**, also allokierte **jeder** Kindbefehl (tasklist/find/ping)
  eine **eigene sichtbare** Konsole — im Sekundentakt, fokus-stehlend, unbeendbar.
- **Fix:** Der Helfer läuft jetzt mit `CREATE_NO_WINDOW` (versteckte Konsole, von
  allen Kindbefehlen geerbt) → **kein einziges Fenster**. Zusätzlich sind die
  Warte-/Kopier-Schleifen **hart begrenzt** (statt potenziell endlos), falls die
  alte Instanz mal nicht sofort schließt.

> Wichtig: Wer noch eine ältere Version hat, sollte dieses Update **NICHT** über
> den In-App-Button ziehen (der alte Helfer hat den Bug noch), sondern die EXE
> einmalig **manuell** von der Releases-Seite ersetzen. Ab dann sind Updates sauber.

## [1.2.16] — 2026-06-16

### Energiesplitter: Shop öffnen (Dialog → „Laden öffnen") kalibriert — Hammer-Kauf jetzt durchgehend

- **„Laden öffnen" wird im Dialog erkannt + geklickt.** Aus deinen Dialog-Bildern
  kalibriert (`templates/laden_oeffnen.png`): die Zeile wird per Farb-NCC im
  zentrierten Optionen-Band gefunden (vorhanden ≥ 0.985, abwesend ≤ 0.36) —
  funktioniert für Alchemist UND Waffenhändler (die Zeile sitzt je nach
  Dialoggröße bei anderer Höhe). Danach kurze Render-Pause, dann sucht der Bot
  das Item im Shop (200er-Hammer am kalibrierten Anker, NCC 0.91 verifiziert).
- **Kein fragiles fixes Shop-Header-Template mehr** (das Shop-Panel ist frei
  verschiebbar): „Shop offen" wird dadurch verifiziert, dass das Item gefunden
  wird — sonst sauberer Stop.
- Damit läuft die **Hammer-Kauf-Kette durchgehend**: NPC ansprechen → „Laden
  öffnen" → Shop → 200er-Hammer rechtsklicken → Re-Read-Verifikation.

> Hinweis: Für mehr Stacks als auf **Inventar-Seite I** frei sind, kommt als
> nächstes der **Mehrseiten-Scan (II/III/IV)** inkl. seitenübergreifender
> Kauf-Verifikation. Für einen ersten scharfen Test: `Hammer-Stacks` ≤ freie
> Plätze auf Seite I wählen.

## [1.2.15] — 2026-06-16

### Energiesplitter: AFK-Dialog wegklicken + NPC per Linksklick ansprechen

- **AFK-Dialog wird automatisch weggeklickt.** Der zentrierte „Du bist im AFK-
  Modus"-Dialog blockiert alle Klicks/Tasten → der Bot kam nie zum NPC. Er
  erkennt ihn jetzt am OK-Knopf (NCC, gebündeltes Template; self 1.00, normale
  Szene/Shop ≤ 0.44) und klickt zu Beginn jedes Ticks **OK** weg.
- **NPC wird per LINKSklick mittig auf den Namen angesprochen** (statt Rechtsklick-
  Anvisieren) — der sichere Weg, einen NPC anzusprechen. Der gefundene grüne
  Namens-Mittelpunkt aus der Erkennung ist das Klickziel; die Vogelperspektive
  läuft davor, falls der Name sonst nicht sichtbar ist.
- Der Dialog-Schritt stoppt nicht mehr hart, wenn die Dialog-Vorlage noch nicht
  kalibriert ist (klarer Hinweis-Log statt Abbruch).
- Volles Debug für beide: „AFK-Dialog erkannt → OK klicken", „NPC ansprechen —
  LINKSklick MITTIG auf den Namen".

> Noch offen für einen vollständigen Kauf (nächste Stufe): Dialog-/Shop-Erkennung
> aus den `erstgespräch*`/`Shopgeöffnet*`-Bildern kalibrieren + Mehrseiten-Scan.

## [1.2.14] — 2026-06-16

### Behoben (Energiesplitter: erkennt jetzt, ob die Tasche offen ist – und öffnet sie)

- **Tasche-offen-Erkennung wiederverwendet.** Der Energiesplitter scannte das
  Inventar bisher „blind" und las bei geschlossener/falscher Tasche 0 freie
  Plätze (→ falscher „kein Platz"-Stopp). Jetzt nutzt er **dieselbe bewährte
  Logik wie der Angel-Bot** (`inventory.open_probe`: Tab-Template-Probe + Toggle-
  Hotkey): er prüft vor dem Scan, ob die Tasche offen ist, und **öffnet sie
  selbst** (Taste I), wenn nicht. Schlägt das fehl, stoppt er mit klarer Meldung.
  Greift in beiden Aktionen (Hammer kaufen + Dolche verarbeiten).
- Die Inventar-Toggle-Taste kommt aus der Config (Default `I`).

## [1.2.13] — 2026-06-16

### Behoben (Energiesplitter-Reiter: Buttons + Reihenfolge + Klartext)

- **Buttons wackelten/flackerten** beim Start auf dem Energie-Reiter: die zwei
  Start/Stopp-Knöpfe wurden ~100×/s neu konfiguriert (jeder Bot-Tick). Jetzt nur
  noch bei echter Zustandsänderung (Dirty-Check) — kein Flackern mehr.
- **Reiter-Reihenfolge:** „Energie" steht jetzt **über** der Rangliste
  (bei den Bot-Modi: Angeln, Puzzle, Inventar, Seher, **Energie**, Rangliste …).
- **Klartext bei vollem Inventar:** Stoppt der Bot mangels Platz, sagt die
  Meldung jetzt deutlich „Inventar zeigt 0 freie Plätze (Seite I) – bitte
  Inventar öffnen UND Platz schaffen, dann erneut starten" (vorher knapp „Kein
  freier Inventarplatz").

## [1.2.12] — 2026-06-16

### Behoben (Energiesplitter: NPC-Erkennung – jetzt in ALLEN Perspektiven)

Der NPC wurde trotz sichtbarem grünem Namen nie erkannt (`ncc=0.0`). Drei
Ursachen, gegen **alle 17 gelieferten NPC-Bilder** (8 Alchemist + 9
Waffenschmied) gemessen und behoben:

- **Template wurde nie geladen.** Der Such-Schlüssel war `npc_alchemist`, das
  Verzeichnis liefert aber bereits `npc/` → gesucht wurde `npc/npc_alchemist.png`
  statt `npc/alchemist.png` → Vorlage = leer → `find_npc_name` lieferte glatt
  `0.0`. Behoben (korrekter Schlüssel + `load_template` toleriert das Präfix
  zusätzlich defensiv).
- **Suchfenster schnitt Rand-NPCs ab.** Je nach Kamerawinkel liegt der Name bei
  x 126…565 / y 106…429; das alte Fenster (x 150…620, y 100…420) schnitt linke/
  untere Lagen ab. Region an der vollen gemessenen Spanne neu kalibriert.
- **Validiert über alle Perspektiven:** Mit der gebündelten Vorlage + grüner
  Maske wird der Name jetzt in **allen 8 Alchemist- und 9 Waffenschmied-Bildern**
  gefunden (NCC 0.87–0.99). Ein neuer Test prüft das dauerhaft in der CI — fällt
  ein Kamerawinkel durch, schlägt er fehl.

## [1.2.11] — 2026-06-16

### Behoben (Energiesplitter: Spiel-Fenster wird beim Lauf fokussiert)

- **Fenster-Fokus beim Start + vor Tastendrücken.** Tasten (z. B. die
  Vogelperspektive `g`) gehen immer an das **fokussierte** Fenster — ohne Fokus
  landeten sie im Bot-Fenster und bewirkten im Spiel nichts. Dadurch wurde die
  Kamera nie umgeschaltet und der NPC blieb „nicht erkennbar" (NPC-Suche drehte
  sich endlos mit `ncc=0.0`). Der Bot holt das Spiel-Fenster jetzt **beim
  Lauf-Start einmal in den Vordergrund** und **vor jedem Tastendruck** erneut
  (reiner `SetForegroundWindow`-Aufruf, kein Prozess-Zugriff). Maus-Klicks
  aktivieren das Fenster ohnehin selbst. Gilt für **beide** NPCs (Alchemist +
  Waffenhändler).

## [1.2.10] — 2026-06-16

### Behoben + verbessert (Energiesplitter: erster scharfer Lauf)

- **Absturz beim NPC-Ansprechen behoben.** Beim ersten scharfen Lauf (GATE grün)
  brach `approach_npc` mit `TypeError: t() got multiple values for argument 'key'`
  ab (das Log-Format-Feld hieß `key` und kollidierte mit dem `key`-Parameter der
  Übersetzungsfunktion). Latenter Bug — er konnte erst auftreten, seit der Bot
  dank v1.2.9 überhaupt bis zum Flow kommt. Der Bot stoppte dabei sauber (kein
  unkontrolliertes Weiterlaufen), tat aber nichts.
- **Vogelperspektive: jetzt mehrfach mit Renderzeit.** Wird der NPC nicht erkannt,
  schaltet der Bot die **Vogelperspektive** (Taste `g`) um, **gibt der Kamera
  Zeit zum Umschalten** (≈0,8 s) und sucht **mehrfach erneut** (abwechselnd
  Normal-/Vogelperspektive, standardmäßig bis zu 4 Versuche), bevor er sauber mit
  „NPC nicht erkennbar" stoppt. Vorher gab es genau einen Tastendruck + sofortige
  Neusuche (10 ms später — die Kamera war da noch gar nicht umgeschaltet). F6
  stoppt während der Versuche jederzeit.

## [1.2.9] — 2026-06-16

### Behoben (Energiesplitter: lief „dauerhaft", war nicht stoppbar, tat nichts)

- **Templates fehlten in der EXE.** Die Hammer-/Dolch-/NPC-Vorlagen
  (`energiesplitter/templates/`) wurden bisher **nicht in die EXE gepackt** →
  der Phase-0-GATE war in der gebauten App IMMER rot (`item:hammer`,
  `npc:alchemist` „nicht gefunden") und der Bot konnte nie etwas tun („stand
  nur rum"). Beide Spec-Dateien bündeln die Vorlagen jetzt.
- **„Läuft dauerhaft / nicht stoppbar" behoben.** Der Start/Stop-Knopf des
  Energiesplitters blieb nach einem Selbst-Stopp des Bots rot auf „Stoppen"
  stehen, obwohl der Bot schon gestoppt war — ein Klick darauf **startete neu**
  statt zu stoppen (Endlos-Restart). `sync_controls` spiegelt jetzt bei jeder
  Zustandsänderung den echten Laufzustand auf die Knöpfe; ein gestoppter Bot
  zeigt wieder „Start". F6 stoppt weiterhin jederzeit.
- **Klartext-Debug, warum es nicht ging.** Statt kryptischer Tokens
  (`npc:alchemist`) meldet der Bot jetzt verständlich, **was fehlt**: „Alchemist
  nicht erkennbar", „Waffenhändler nicht erkennbar", „Fenster nicht 800×600",
  „Inventar-Raster nicht kalibriert" usw.
- **Klare Trennung „nicht bereit" vs. „Simulation".** Fehlt wirklich etwas →
  Stopp mit Klartext-Gründen. Ist alles bereit, aber „Scharf/Live" ist AUS →
  klare Meldung „SIMULATION aktiv … schalte ‚Scharf/Live' ein", dann sauberer
  Stopp (kein verwirrendes „phase0_not_ready", kein Dauer-Neustart).
- **Auto-Stopp bei Fehlern bleibt garantiert.** Wie bei allen anderen Bot-Modi
  stoppt der Energiesplitter bei jedem Fehler/Block automatisch (und über F6) —
  er läuft nie unkontrolliert weiter. Im scharfen Lauf werden „Gekauft …",
  „Dolch gekauft", „Verarbeitet …" weiterhin lückenlos protokolliert.

## [1.2.8] — 2026-06-16

### Geändert (Energiesplitter: vereinfacht + Einstellungen aufgeräumt)

- **Yang spielt keine Rolle mehr.** Preis, Kontostand und Ausgabe-Überwachung
  (inkl. Yang-Rechner und Yang-Leser) wurden komplett entfernt — der Bot kauft
  und verarbeitet einfach, ohne Yang zu zählen. Als Sicherheit bleiben das
  **Aktions-Limit**, der **Stop nach unverifizierten Käufen** und vor allem die
  **Erkennung vor Aktion** (es wird nur gekauft/gezogen, was sicher als Hammer
  bzw. Dolch erkannt wurde).
- **Hammer immer als 200er-Stack.** Du gibst nur noch die **Anzahl 200er-Stacks**
  ein; der Bot kauft genau so viele 200er-Stacks (keine 1er/50er mehr).
- **Dolche werden nacheinander verarbeitet** (keine Massen-Verarbeitung): pro
  Runde 1 (oder mehrere) Dolche kaufen, dann Hammer-Stack einzeln auf jeden Dolch
  ziehen.
- **Einstellungen komplett auf Deutsch, gruppiert und scrollbar.** Keine
  englischen Roh-Bezeichner mehr; heikle Tempo-Regler liegen unter „Erweitert"
  mit Warnhinweis. Standard bleibt **Simulation** (bewusster „Scharf/Live"-
  Schalter für echte Käufe).

## [1.2.7] — 2026-06-15

### Behoben (kritisch)

- **App-Start-Absturz behoben.** v1.2.6 konnte wegen eines fehlenden Rail-
  Eintrags (`KeyError: 'energiesplitter'`) gar nicht starten. Der neue
  Energiesplitter-Reiter ist jetzt korrekt in der Seitenleiste verdrahtet; der
  Start wurde am echten GUI verifiziert (alle Reiter bauen + schalten). Zusätzlich
  ist die Seitenleiste jetzt absturzfest: ein unbekannter Reiter wird übersprungen
  statt die ganze App zu killen.

## [1.2.6] — 2026-06-15

### Energiesplitter-Modul: scharf-fähig (kalibriert)

- **Vollständig kalibriert:** Inventar-Raster, Hammer-/Dolch-Erkennung,
  NPC-Erkennung (Alchemist/Waffenhändler) und der **Yang-Leser** (liest den
  rohen Yang-Betrag unten rechts) sind aus echten Spielbildern geeicht. Das
  Modul kann jetzt **scharf** kaufen und verarbeiten.
- **Sicher startet es trotzdem:** Default ist **Simulation** — du musst „Scharf
  / Live" bewusst einschalten, bevor echtes Yang ausgegeben wird. Empfehlung:
  erster echter Lauf mit kleiner Hammerzahl und Aufsicht.
- **Erkennung vor Aktion:** Gekauft/verarbeitet wird **nur**, was als Hammer
  bzw. Dolch erkannt wurde — passt etwas nicht, **stoppt** der Bot sauber statt
  falsch zu klicken oder zu ziehen.
- **Yang-Schutz:** Mindest-Reserve, Ausgabe-Limit und Aktions-Limit greifen vor
  jedem Kauf. Neuer Schalter **„Yang-Prüfung"** (Standard an): aus = der Bot
  bricht nicht ab, falls der Yang-Stand mal nicht lesbar ist — dann begrenzen
  Ausgabe- und Aktions-Limit (kein Live-Reserve-Schutz; bewusst wählen).

## [1.2.5] — 2026-06-15

### Hinzugefügt (Energiesplitter-Modul — Vorschau/Gerüst)

- **Neuer Reiter „Energiesplitter"** mit zweigeteiltem Start-Button
  (**Hammer kaufen** / **Dolche kaufen + verarbeiten**), Eingabe der
  **Hammer-Anzahl** mit **Yang-Rechner** (Anzahl × 15.000 für Hammer +
  Anzahl × 15.000 für Dolche), eigenen Einstellungen und umfangreichen Logs.
- **Noch nicht scharf (mit Absicht):** Das Modul führt aktuell **keine** echten
  Käufe/Verarbeitungen aus. Ein **Sicherheits-GATE (Phase 0)** verhindert jede
  Maus-Aktion, bis die restlichen Erkennungs-Bilder + die Kalibrierung vorliegen.
  Mehrere **Gold-Schutz-Backstops** (Mindest-Reserve, Ausgabe-Limit, Aktions-
  Limit) sind eingebaut. Die scharfe Kauf-/Verarbeitungs-Logik folgt in einem
  nächsten Update; der erste echte Lauf läuft bewusst überwacht mit hoher
  Gold-Reserve.

### Geändert (intern, ohne Verhaltensänderung an Angeln/Puzzle)

- Energiesplitter-Bot in kleine, fokussierte Module aufgeteilt (alle < 800
  Zeilen) und auf Robustheit getrimmt. Hammer-Stack-Größen auf **1 / 50 / 200**
  korrigiert.

## [1.2.4] — 2026-06-14

### Behoben (Fischpuzzle: klügere Endspiel-Entscheidung)

- **Finish-Modus zerstört kein 1-Zug-Loch mehr:** Stand das Brett kurz vor
  Fertig und war in genau **einem** Zug komplettierbar (z. B. ein L-förmiges
  Loch, das ein L-Stein füllt), konnte der „Finish"-Notmodus stattdessen einen
  unpassenden Stein hineinzwingen und das Loch fragmentieren — danach hing der
  Bot lange im Verwerfen fest (im User-Log nachgewiesen). Jetzt wartet er
  geduldig auf den komplettierenden Stein (gedeckelt, damit er nie endlos
  wartet).

### Hinzugefügt (Fischpuzzle: Sicherheits-/Plausibilitäts-Schicht)

- **Platzierungs-Audit + Konfidenz-Log:** Nach jeder Platzierung wird das
  erwartete gegen das tatsächlich gelesene Brett geprüft und Abweichungen
  werden geloggt; pro Stein werden rohe Farbwerte + Erkennungs-Konfidenz
  protokolliert. Damit werden Fehl-Erkennungen erstmals nachvollziehbar
  (Beobachtung — der Spielablauf ändert sich dadurch nicht).
- **Vorsichtigere Farb-Erkennung:** Eine mehrdeutige Stein-Farbe wird lieber
  verworfen als mit dem Risiko einer Fehlplatzierung gesetzt.
- **Brett-Plausibilität:** Ein offensichtlich gestörtes Brett-Bild (viele
  Zellen ohne echte Steinfarbe) wird kurz neu gelesen, statt darauf zu
  entscheiden.
- **Sicherheits-Stopp:** Werden sehr viele Steine in Folge ohne jede
  Platzierung verworfen, stoppt der Bot sauber, statt endlos Boxen zu
  verbrauchen.

## [1.1.7] — 2026-06-10

### Geändert (User-Feedback: Timer-Bedienung unmissverständlich)

- **EIN Schalter statt Checkbox+Segment:** Die Zeitlimit-Steuerung ist jetzt
  ein einziges Dreifach-Segment **Aus | Stoppen | Inventar-Cleanup** plus
  Minutenfeld. Die alte Kombination war eine Falle: Segment auf „Inventar-
  Cleanup", aber Häkchen vergessen → gar kein Timer aktiv, und ein Stopp aus
  anderem Grund sah wie ein Cleanup-Fehler aus (User-Report). **0 Minuten
  bedeutet ebenfalls: nie stoppen** (im Hilfetext dokumentiert).
- **Eine Timer-Autorität:** Der historische bot-interne Zeitlimit-Stop im
  Fishingbot ist deaktiviert — nur noch der RunLoop-Timer feuert, und nur der
  kennt die Aktion (Stoppen vs. Cleanup). Damit kann ein Zeitlimit nie mehr
  Cleanup-blind stoppen.

## [1.1.6] — 2026-06-10

### Behoben (Live-Feedback aus v1.1.5)

- **Offen-Erkennung auf entfernten Standorten:** Die Inventar-Tab-Leiste ist
  leicht transparent — je nach Szene dahinter (Wasser/Steg) lasen inaktive
  Tabs bis zu MAD 8,7 und die Schwelle 8 meldete fälschlich „zu" (die
  Abbrüche im Nutzer-Log). Schwelle auf 15 (Landschaft bleibt ≥26, weiter
  große Marge); mit den 4 gelieferten Seiten-Screenshots (I–IV) als
  Test-Fixtures abgesichert.
- **Goldfisch-Bestätigung: Fenster wandert!** Der Bestätigungs-Dialog steht
  nicht an fester Position (Höhe hängt vom Text ab; Live-Referenzen: OK bei
  y=250 vs. y=202). Der OK-Knopf wird jetzt per Template über den ganzen
  Frame GESUCHT (zweistufig: Knopf-NCC ≥0,70 + flache Leisten-Flanken) und
  exakt am Fund geklickt.
- **Inventar-Management-Grid:** letzte Spalte war abgeschnitten → 8 Spalten
  (eine Reihe mehr), per Tk-Messung verifiziert (Grid endet bei x=514 von 555).

### Verbessert

- **Wegwerfen/Grillen ~2× schneller:** Der Drag-Pfad (12 Zwischen-Moves)
  zahlte pro Move den globalen 0,05s-Hold (~0,6 s/Item nur fürs Ziehen);
  reine Maus-Moves laufen jetzt mit PAUSE=0 (nur Down/Up behalten ihren Hold).
- **„Inventar managen" zeigt den Lauf:** Knopf wird zu „läuft … [F6] stoppt"
  (gesperrt); **F6 bricht Grillen/Wegwerfen sauber nach dem aktuellen Item
  ab** (Status „gestoppt", Log zeigt den Stand).
- **Cleanup-Timer:** Countdown 40 s → **30 s**; läuft bei 00:00 noch ein
  Grill-/Wegwerf-Worker, wird er aktiv gestoppt (Abbruch nach dem aktuellen
  Item) und das Angeln startet direkt danach neu (User-Spez).
- **Inventar-Seite bleibt erhalten:** Nach Scan/Grillen/Wegwerfen klickt der
  Bot die Seite (I–IV) wieder an, die vor dem Lauf offen war.

## [1.1.5] — 2026-06-10

### Neu

- **Zeitlimit-Aktion „Inventar-Cleanup" (entweder/oder):** Beim „Stoppen nach
  Zeit (Min.)" lässt sich jetzt wählen, was nach Ablauf passiert: **Stoppen**
  (wie bisher) ODER **Inventar-Cleanup** — der Bot stoppt, stellt sicher, dass
  das Inventar offen ist (neue Offen-Erkennung), scannt es, wendet die
  Behalten/Entfernen/Lagerfeuer-Markierungen an (grillen + wegwerfen) und
  startet das Angeln nach einem sichtbaren **40-Sekunden-Countdown** im
  Top-Timer automatisch neu — der Zeit-Timer beginnt dann von vorn
  (Dauerbetrieb mit periodischem Aufräumen). Abbruch jederzeit per Stop-Hotkey
  oder manuellem Start.
- **Start-Knopf kontextabhängig:** Starten ist nur noch in den Ansichten
  _Fishing_ und _Puzzle_ möglich (dort ist eindeutig, was gestartet wird) — in
  Inventar/Rangliste/Roadmap/Console/Einstellungen ist der Start-Knopf
  ausgegraut. Stoppen bleibt bei laufendem Bot in jeder Ansicht möglich.

### Behoben

- **Puzzle: Steine wurden sofort verworfen statt gesetzt (User-Report):** Der
  Bot las die Stein-Farbe genau EINMAL, ~0,1–0,3 s nach dem Holen — da war der
  Stein oft noch nicht gerendert (Log: Hintergrund-Grau b=31 g=34 r=36 am
  Sample-Punkt) → `new_piece=None` → sofortiges Wegwerfen, bei jedem Stein.
  Jetzt liest State 4 bis zu 2 s lang pro Frame ein frisches Capture nach
  (Erfolg beendet die Schleife sofort; erst nach Ablauf greift der bisherige
  Verwerfen-Pfad, voll geloggt). Zusätzlich war das BLAU-Fenster zu eng: der
  live gemessene blaue Stein (255,74,0) fiel mit g 100–115 durch → auf
  g 60–130 verbreitert (kollisionsfrei; kein anderes Fenster hat b>240 und
  r<10). On top: **Toleranz-Klassifikation** als zweite Stufe (±40/Kanal gegen
  die 6 Referenz-Zentroide, eindeutig oder gar nicht) — erkennt JEDEN künftig
  gedrifteten Farbton sofort, beweisbar verwechslungsfrei (kleinste Kanal-Lücke
  zweier Steinfarben 85 > 2×40; Invarianten-Test pinnt das, bei 45 hätten
  Orange/Gelb überlappt) und Hintergrund/Garbage trifft konstruktiv nie. Neue
  Tests: `TestColorReadRetry` + `TestClassifyPieceTolerant` +
  `TestTolerantFallbackWiring` (test_puzzle_glue), Disjunktheits-Invariante +
  Sweep-Kontrakt in test_color_sampling.
- **Goldener Thunfisch: Bestätigungs-Fenster wurde nie geklickt (Bot hing):**
  Nach dem Options-Klick (z. B. Freilassen) antwortet der Server mit einem
  zweiten Fenster mit OK-Knopf. Der alte Code klickte OK blind 0,1 s nach dem
  Options-Klick — praktisch immer BEVOR das Fenster existierte; und da dieses
  Fenster die Bildecken nicht schwärzt, sah die Tagesbelohnungs-Erkennung es
  nie → Dialog blieb offen. Jetzt: eigene Erkennung des Bestätigungs-Dialogs
  (Template-Match der Knopf-Leiste, beidseitig des OK-Knopfs, hover-sicher;
  Selbst-Match 0.0 vs. nächster Negativfall ≥27) und OK-Klick erst, wenn der
  Dialog wirklich im Frame steht (bis 10 s Wartefenster, retry-sicher).
  OK-Position präzise nachgemessen: Client (403,250) Knopf-Mitte (alt 399,246
  = Knopfrand). Templates `images/golden_confirm_bar_{l,r}.png`, Referenz
  `FischOCR/GoldenerThunfischAuswahlbestätigen.png`; neue Tests
  `tests/test_golden_confirm.py`.

- **„Bot laeuft los" bei Scan/Manage (Klick in die Landschaft):** Die
  Inventar-Taste ist ein TOGGLE — war der Beutel schon offen (z. B. direkt nach
  einem Scan, der ihn absichtlich offen laesst), schloss der blinde
  Oeffnen-Druck ihn wieder, und die folgenden Tab-Klicks bzw. Drag-Quellen
  landeten als Links-Klicks in der 3D-Welt → der Charakter lief los. Alle drei
  Live-Fluesse (Scan, Lagerfeuer-Braten, Wegwerfen) pruefen den Offen-Status
  jetzt VOR jedem Tastendruck und bei Misserfolg brechen sie ab, BEVOR
  irgendetwas geklickt wird (`inventory.scan_not_open` /
  `campfire.status_not_open` / `discard.status_not_open`).

### Neu

- **Selbststaendige Offen-Erkennung (`inventory/open_probe.py`):** Template-
  Match der vier Seiten-Reiter (I–IV) an den kalibrierten Positionen — die je
  eine AKTIVE (hellere) Seite matcht ihr Inaktiv-Template nicht, die anderen
  drei matchen pixelgenau. Regel „≥3 von 4 matchen = offen". Vermessen auf
  echten Captures: offen 0.0–0.6 MAD (inaktiv) vs. 39–53 (aktiv) vs. 26–69
  (geschlossen/Landschaft); adversarialer Sweep mit 73.170 Platzierungen ueber
  die Landschaft: **0 Falsch-Offen**. Templates gebuendelt unter
  `inventory_tab_templates/` (beide .spec-Dateien), Extraktor
  `tools/extract_tab_templates.py`.
- **Toggle-Selbstheilung:** Liest ein offener Beutel wegen Tooltip/Cursor auf
  der Tab-Reihe faelschlich „zu", schliesst Druck 1 ihn sauber und Druck 2
  oeffnet ihn verifiziert wieder (max. 2 Druecke, Cursor wird vor jeder Probe
  geparkt).
- **Test-Fenster zeichnet die Tab-Reihe** (echte Templates), damit der Scan
  gegen das Fake-Inventar weiterhin funktioniert; neue Testdatei
  `tests/test_inventory_open_probe.py` (Synthese + echte Open-/Closed-Shots
  inkl. Seite-II-aktiv).

## [1.1.5] — Run-1 Haertung (Statistik/Ranking/Telemetrie-Server, Teil desselben Releases)

### Behoben

- **Statistik-Persistenz bei Absturz/Update:** Akkumulierte Laufzeit ging auf
  manchen Beenden-Pfaden verloren (Fenster schliessen ohne Fang/Loesen, harter
  `os._exit` beim Auto-Update). Jeder Exit-Pfad sichert die `stats.json` jetzt
  final atomar (`App._flush_stats` -> in `hack.py` registrierter Hook).
- **Atomares Speichern unter Last:** `stats.save()` schreibt pro Aufruf in einen
  eindeutigen Temp-Namen und wiederholt `os.replace` kurz bei transienten
  Windows-Sharing-Violations (WinError 5). Damit gehen unter gleichzeitigen
  Schreibern keine Schreibvorgaenge mehr verloren (0/300 statt ~128/300 Fehler),
  und der Nebenlaeufigkeits-Test ist deterministisch gruen.
- **Telemetrie nur ueber HTTPS:** Die URL-Validierung lehnt jetzt `http://`
  (und alle Nicht-`https`-Schemata) ab und faellt auf den HTTPS-Default zurueck
  — Username/HWID/Stats gehen nie im Klartext ueber die Leitung.

### Server (Artefakte) — Defense-in-Depth

- **IP-Spoofing-Schutz:** Die App vertraut `X-Real-IP` bzw. dem rechtesten
  `X-Forwarded-For`-Hop (von nginx angehaengt), nie dem faelschbaren linken
  Eintrag; nginx-`real_ip`-Hinweise im Server-Block + DEPLOY.md.
- **Beschraenkter Rate-Limiter:** Die In-Process-Bucket-Map wird global geleert
  (periodisch + ab Obergrenze), schliesst die unbeschraenkte Speicher-Wachstum.
- **nginx leerer-X-HWID-Bypass geschlossen** (Map auf `$binary_remote_addr`).

### Tests / Doku

- Testsuite auf **533 Tests** aktualisiert (Doku-Zahl korrigiert, vormals
  faelschlich „126"); Server-Suite **44** gruen. Thread-Timing-Flakiness in den
  Telemetrie-Sender-Tests beseitigt (ereignisgesteuert statt `sleep`).

## [1.1.4] — 2026-06-07

### Behoben / Verbessert (Angel-Chat-Erkennung)

- **3 gemeldete Faenge wurden nicht erkannt:** _Karpfen_ und _Aal_ lieferten
  `UNKNOWN` (der Glyphen-Atlas kannte die Zeichen `A`/`f` nicht, daher fiel die
  Fuzzy-Aehnlichkeit unter die Schwelle; bei _Aal_ zusaetzlich fatal, weil der
  Name nur 3 Buchstaben hat). _Schwarzes Haarfärbemittel_ funktionierte schon,
  ist jetzt aber stabiler. Aus den gelieferten Chat-Bildern nachtrainiert:
  3 neue Whole-Name-Templates + die Atlas-Glyphen `A`/`f`/`z`. Die neuen Glyphen
  verbessern auch bestehende Namen (Spiegelkarpfen, alle Haarfärbemittel lesen
  jetzt das `f`). Bestehende Templates bleiben byte-identisch.
- **Sicherheitsnetz gegen stille Luecken:** Neuer Test deckt JEDEN fangbaren
  Namen (`ITEM_NAMES`) gegen Atlas+Fuzzy ab. Aktuell 41/44 sicher erkennbar;
  dokumentierte Rest-Luecken (`Ayu`, `Blondes`/`Braunes Haarfärbemittel` —
  fehlende Glyphen `y`/`B`) degradieren SICHER (UNKNOWN → Fisch wird behalten,
  nie faelschlich abgebrochen). Ein neuer, nicht erkennbarer Fisch laesst den
  Test kuenftig sofort anschlagen.
- Neues Dev-Tool `tools/synthesize_chat_reference.py` (Chat-Crop → 802×632
  Referenzframe) fuer reproduzierbares Nachtrainieren weiterer Faenge.

### Oberflaeche

- **Schrift im ganzen Interface groesser/besser lesbar:** Die globale
  Widget-Skalierung wurde von `0.85` (~15% kompakter) auf `1.0` angehoben und der
  zuvor sehr kleine, graue Abschnitts-Untertitel ("Infos", z.B. _„Scan the
  inventory and locate tracked items"_) vergroessert. Damit der No-Scroll-Aufbau
  erhalten bleibt, sind die fixen Fenstergroessen (Hauptfenster + Onboarding-,
  Effekt- und Fenster-Auswahl-Dialog) proportional mitgewachsen.

Erkennungs-/Template- + reine UI-Skalierungs-Aenderung — KEINE Eingabe-/Timing-
Aenderung (headless getestet; die optische Schriftgroesse bitte einmal im Spiel
gegenpruefen).

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

- Headless-Testsuite (reine Logik, ohne GUI/Spiel): **533 Tests gruen**.

### Unveraendert (bewusst, byte-stabil)

- **Angeln** (`fishingbot.py`, `fishfilter.py`, `hsvfilter.py`) und der
  **Standard-Puzzle-Solver** (Greedy in `tetris.py`): Verhalten wie im Original.
  Die KI bzw. die optionalen Modi laufen ausschliesslich, wenn explizit gewaehlt.
