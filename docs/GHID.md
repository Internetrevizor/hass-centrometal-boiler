# Ghidul integrării Centrometal Boiler System (PelTec II Lambda)

Stare la 22.10.2026, versiunea **0.2.0.21** (pe branch-ul `claude/git-release-commit-f8oo83`).

## 1. Ce este

Integrare Home Assistant (custom component, instalată prin HACS) pentru cazanele Centrometal conectate la portalul cloud prin CM WiFi-Box. Citește datele prin HTTP (polling) și WebSocket (STOMP, timp real) și trimite comenzi (pornire/oprire cazan, circuite, setări editabile).

- Domeniu: `centrometal_boiler`
- Cod: `custom_components/centrometal_boiler/`
- Familii suportate: PelTec II (`peltec2`), PelTec (`peltec`), Compact, CM Pelet-set, BioTec, BioTec Plus. Detaliile de mai jos sunt pentru **PelTec II**.

## 2. Instalația proprietarului

| | |
|---|---|
| Cazan | PelTec II Lambda, firmware controler `v3.03dL` |
| Schema hidraulică | **43** (`B_KONF` = 42): buffer „CAS” (senzori sus/jos) + circuitul **K1 = ACM (DHW)** |
| P1 | **pompa de ACM** a circuitului K1, aceeași pompă ca `K1B_P` (entitatea „DHW Pump (K1)”). `B_P1` nu are entitate separată: în captură, `B_P1` și `K1B_P` au comutat în aceeași milisecundă la toate cele 7 cicluri. |
| P2 | pompa de **recirculare ACM** (K1), entitatea „P2 DHW Recirculation Pump (K1)” |
| P3, P4 | nefolosite în schema 43 (atribut `Function: Not used in this configuration`) |
| Vana cu 4 căi | pe circuitul cazanului, automată (`B_misP`, „4-Way Mixing Valve Position”) |
| Senzor ACM | neinstalat (portalul afișează „-°C”) |

Sursa pentru schema 43: manualul cazanului, pagina 57.

## 3. Instalare și actualizare

1. HACS → integrarea Centrometal → ⋮ → **Update information** → instalează versiunea nouă.
2. Repornește Home Assistant.
3. Prima pornire după actualizare șterge automat entitățile pe care integrarea nu le mai creează. Curățarea e sărită dacă datele de la portal par incomplete.

`entity_id`-urile nu se schimbă între versiuni (sunt legate de `unique_id` = `<serial>-<parametru>`). La unele entități se schimbă doar numele afișat.

## 4. Stările cazanului (Boiler State, `B_STATE`)

Textele urmează tabelul „Operation stages” din manualul de regulare (pag. 96–97). Automatizările care compară textul au nevoie de șirurile exacte. Atributul `Raw stage code` conține codul simplu (`S4`, `D6`…) și e mai sigur pentru automatizări.

| Cod | Text în HA | Schimbat în 0.2.0.21 |
|---|---|---|
| OFF | OFF: Switched off | |
| S0 | S0: Initial fan blowing, waiting for grate initial position | da (era „Fan blowing / grate check”) |
| S1 | S1: Not in use | da (era „Not used”) |
| S2 | S2: Initial pellet filling | |
| S3 | S3: Waiting for flame | |
| S3-1 | S3-1: Extended ignition / flame verification | |
| S3-2 | S3-2: Additional ignition fuel charge | |
| S4 | S4: Electric heater working after flame appears | da (era „Electric heater igniting”, greșit) |
| S5 | S5: Flame developing | |
| SP1…SP5 | SP1: Stabilising 1 … SP5: Stabilising 5 (manualul are doar SP1–SP3) | |
| S6 | S6: Additional flame development | |
| D0…D6 | D0: Power D0 (min) … D6: Power D6 (max) | |
| S7 | S7: Shutdown stage | |
| S7-1 | S7-1: Shutdown 1, waiting for flame to disappear | da (era „Shutting down”) |
| S7-2 | S7-2: Shutdown 2, fan at maximum speed | da (era „Final fan blowing”) |
| S7-3 | S7-3: Standby, waiting for start request | da (era „Standby”) |
| PF0 | PF0: Power failure — electric heater on, waiting for flame | da (era „heater starting”) |
| PF1 | PF1: Power failure — flame appeared, electric heater off | da (era „heater off”) |
| PF2 | PF2: Power failure — flame developing | |
| PF3 | PF3: Power failure — waiting for flame to disappear | da (era „waiting for flame off”) |
| PF4 | PF4: Power failure — final fan blowing | da (era „final blowing”) |
| C0 | C0: Grate cleaning | |

Testul `tests/test_operation_stage_labels.py` fixează lista completă, ca nicio schimbare să nu se producă din greșeală.

Alte decodări PelTec II:
- `B_start` („Burner Command”): 0 Stopped, 1 Running, 2 Stopping, 3 Cleaning. Dacă `B_STATE` = S7-3, arată „Paused / standby”.
- `B_specG` („Status Mark”): 0 None, 1 R (flacără pierdută), 2 B (bimetal țeavă peleți), 3 T (turbulatori), 4 G (curățare grătar), 5 F.

## 5. Schemele hidraulice PelTec II

`B_KONF` e numărul schemei minus 1 (portalul și ecranul controlerului arată numărul real). Tabelul complet cu cele 45 de scheme e în `custom_components/centrometal_boiler/peltec2.py` (`PELTEC2_SCHEMES`), transcris din manualul cazanului, capitolul 4.2.2 (pag. 23–58). E verificat încrucișat cu manualul de regulare: lista „DHW priority” (pag. 52) și tabelul „Installation” (pag. 54).

Ce decide schema:

| Entitate | Se creează în schemele |
|---|---|
| Buffer Tank Heat Request (`B_bup`) | 11–44 |
| DHW Priority (`B_PTV_PRI`) | 2, 5, 6, 9, 10, 13–20, 25, 32, 35, 40, 43, 44 |
| DHW Recirculation Enabled / Pump (`B_REC`, `B_REO`) | toate schemele cu pompă de recirculare ACM |

Ce face releul P1, după manual:

| Rolul lui P1 | Scheme |
|---|---|
| Pompa circuitului K1 (calorifere/pardoseală) | 1–4, 6, 7, 21–27, 30–42 |
| Pompa de ACM pe K1 | 9, 10, 43, 44 |
| Vana cu 3 căi (diverter); agentul termic îl circulă pompa cazanului P(PWM) | 13–16 |
| Pompa buffer-ului | 17–20 |
| Pompa circuitului K2 | 28, 29 |
| Pompa de recirculare ACM | 8, 12 |
| Pompă comună K1/ACM; vana cu 3 căi e pe P2 | 5 |
| Nefolosit | 11, 45 |

Releele P1–P4 primesc numele rolului din schema activă (de ex. „P2 DHW Recirculation Pump (K1)”) și au atributul `Function`. Unde P1 e chiar pompa lui K1, nu se creează entitate separată pentru P1 (`K1B_P` o raportează deja). Unde K1/K2 încarcă boilerul de ACM cu pompa proprie, pompa circuitului se numește „DHW Pump (K1)” / „DHW Pump (K2)”. O schemă care nu e în manual (`B_KONF` ≥ 45) se comportă ca înainte.

Entitatea **Configuration** arată schema (de ex. `43. BUF + K1 DHW`) și are atributele: Buffer tank, DHW tank, DHW recirculation, P1…P4.

Restul parametrilor (temperaturi, contoare, circuit K1, setări editabile) sunt descriși în `PARAMETERS.md`.

## 6. Manualele de referință

Ambele sunt publicate de Centrometal (centrometal.hr → descărcări), în engleză. Nu sunt în repo: repo-ul e public, iar manualele sunt materialul producătorului.

**„Technical instructions Controller PelTec II Lambda”** (fișierul `PelTec-II-Lambda-12-48-regulation-ENG.pdf`, 100 de pagini):
- pag. 52: DHW priority (lista schemelor cu boiler ACM);
- pag. 54: Installation (care scheme au buffer și circuite);
- pag. 55–58: Manual test (P(PWM), P1–P4, vane);
- pag. 81–86: erori și avertizări (E12 presostat de siguranță, E18 nu apare flacăra la aprindere, E19, E23, E24, W2, I1–I19);
- pag. 96–97: Operation stages (tabelul S0…C0, PF0–PF4);
- pag. 97–98: marcajele R, T, G, B.

**„Technical instructions PelTec II Lambda”** (fișierul `PelTec-II-Lambda-12-48-boiler-ENG.pdf`, 96 de pagini):
- cap. 4.2.2, pag. 23–58: cele 45 de configurații, cu legenda pompelor și senzorilor;
- pag. 57: configurația 43 (instalația proprietarului).

## 7. Cum se publică o versiune

Regula proprietarului: **nu se face push în `main`**. Release-urile pleacă de pe branch-ul `claude/git-release-commit-f8oo83`.

1. Pentru o versiune nouă se schimbă: `custom_components/centrometal_boiler/manifest.json` (`version`), badge-ul și titlul din `README.md`, `tests/test_repository_layout.py` (versiunea așteptată) și o secțiune nouă în `CHANGELOG.md`.
2. Commit și push pe branch. CI-ul (Validate, Hassfest, HACS) rulează la fiecare push.
3. Tag-ul nu poate fi urcat din sesiunile Claude (serverul respinge push-ul de tag-uri). Release-ul se creează din GitHub: Releases → Draft a new release → tag nou `vX.Y.Z.W` → **Target: `claude/git-release-commit-f8oo83`** → descrierea din CHANGELOG → Publish.
4. În HA: HACS → Update information → instalare → repornire.

Istoric:
- **0.2.0.11**: release vechi din `main`.
- **0.2.0.20**: importat din zip, PR-ul [Internetrevizor/hass-centrometal-boiler#1](https://github.com/Internetrevizor/hass-centrometal-boiler/pull/1) intrat în `main`, release publicat pe 26.09.2026.
- **0.2.0.21**: doar pe branch (commit-urile `2c0575a` și `9c5bace`), CI verde. **Release-ul nu era încă publicat la 22.10.2026.**

## 8. Dezvoltare și teste

- Testele au nevoie de Home Assistant instalat. Fără el, 10 module de test nu se pot încărca și sunt sărite în tăcere.
- Local: Python 3.13 + `pip install homeassistant aiohttp pytest pytest-asyncio ruff "websockets>=13.1" "certifi>=2024.7.4" voluptuous`, apoi `ruff check .` și `pytest`.
- CI (`.github/workflows/validate.yml`): Python 3.14 și aceleași dependențe.
- Fixture-uri: `tests/fixtures/peltec2_lambda_real_snapshot.json` și `..._http_snapshot.json` (ambele cu `B_KONF` 12, adică schema 13). Nu se știe de unde provin: proprietarul nu le recunoaște, iar instalația lui e pe schema 43.

## 9. Subiecte deschise

1. **`B_REO` („DHW Recirculation Pump”) față de P2**: pe PelTec II, pompa de recirculare e legată mereu la un releu P (manualul o trece pe P1–P4 în fiecare schemă cu recirculare), deci `B_REO` dublează probabil „P2 DHW Recirculation Pump (K1)”. Proprietarul înclina spre „doar pompele `B_P`, nu `B_RE`”. Modificarea a fost schițată (scoaterea `B_REO` din tabela PelTec II; PelTec-ul vechi îl păstrează; `B_REC` rămâne) și apoi oprită: **neaplicată, de discutat**.
2. Publicarea release-ului v0.2.0.21 și verificarea pe HA-ul real: numele pompelor, entitatea Configuration, o ardere completă S0 → D → S7.
3. Actualizarea automatizărilor care compară textele vechi ale stărilor (tabelul de la punctul 4).
4. Fixture-urile cu `B_KONF` 12, de origine necunoscută.
