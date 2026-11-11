# After labeling: audit before the first supervised model

The expert labeler keeps a private database at
`%USERPROFILE%\AFM_Copilot_Private_Audits\labeling\labels.sqlite3`.
Do not upload the SQLite database: it contains paths, specimen/group IDs and operator notes.

## Run the safe audit

```powershell
cd C:\AFM_image_wizard
git switch dev/image-wizard
git pull --ff-only origin dev/image-wizard
.\.venv\Scripts\python.exe -B -m pytest tests\test_learning_audit.py -q
.\.venv\Scripts\python.exe -B -m afm_copilot.learning_audit
```

The final command prints **aggregate JSON only**, never filenames, paths, notes,
hashes, specimen identifiers or pixels. Share its terminal output, not SQLite.

Interpret `labeled` as the number with human classifications, including uncertain.
`morphology_counts` displays classes; `specimen_groups_per_partition` counts
independent group IDs in train, validation and holdout; `blockers` lists
scientific or split-integrity gaps. `training_ready` checks minimum data
readiness only, not the quality of human labels or external validity.

The initially selected 244 images can be an extensible labeled corpus.
The 268 raw files counted by the separate importer audit are not automatically
244 unique or independent images. Byte-identical scans and related images
of the same specimen/session must never cross train/validation/holdout.

After the audit, build a conservative offline classifier baseline and
validate by specimen, including per-class confusion, macro-F1, abstention
and label-randomization controls. Do not automatically deploy model suggestions
or optimize corrections to reduce Sq.

## Policy aggiornata: niente identificativo di sessione obbligatorio

L'utente ha completato il labeling di 244 immagini e per ora vuole
**soltanto questi dati etichettati** come base supervisonata. Le ulteriori
immagini future ampliano il **pool di testing** e non richiedono labeling
preliminare. Il campo sessione/campione non e' obbligatorio nel dataset;
l'assenza lascia pero' **non verificata** l'indipendenza del test.

### Piano di deduplicazione reversibile

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests\test_dedup.py -q
.\.venv\Scripts\python.exe -B -m afm_copilot.dedup
```

Il report non contiene path, filename, checksum o note operatore.
`exact_duplicates_excluded` conta copie SHA-256 da omettere da future
estrazioni per training; **nessun file o record SQLite viene cancellato**.
Se le copie hanno labels discordanti, **l'intero gruppo e' sospeso**
anziche' scegliere automaticamente una classe.

Trace e retrace con byte distinti **rimangono entrambe**;
`potential_trace_retrace_pairs_by_name` e' un'indicazione da verificare
con i canali/direzione di scansione, non una prova. TIFF/IBW che codificano
la stessa topografia possono avere SHA diversi: l'attuale dedup
**non li riconosce** e richiederanno un confronto su mappe normalizzate.

Il dedup attuale opera sulle immagini gia' etichettate e produce un
**piano**, non rimuove scansioni dal database. Il futuro trainer dovra'
usare esclusivamente gli ID candidati dopo gli ulteriori controlli.
Per la valutazione finale, coppie trace/retrace e conversioni della stessa
acquisizione non potranno finire in partizioni opposte.

### Preparare la lista depurata in locale (nessuna cancellazione)

```powershell
.\.venv\Scripts\python.exe -B -m afm_copilot.dedup --prepare
```

Scrive unicamente nella cartella privata del Labeler il file
`PRIVATE_dedup_selection.json`, contenente gli ID interni da utilizzare
in un futuro trainer, le copie esatte soppresse e gli eventuali conflitti.
Il database originale di 244 etichette e i file TIFF/IBW/GWY **non cambiano**.
Non caricare né pubblicare il JSON privato. Il comando stampa solo aggregati.

Il futuro pool di testing, ampliabile senza etichettatura iniziale,
deve essere mantenuto separato: i suoi file non diventano
automaticamente esempi supervisionati, né possono fornire metriche
di accuratezza senza riferimenti verificati a posteriori.

## Baseline ML offline — sperimentale

Il primo classificatore usa esclusivamente descrittori numerici calcolati
dal motore AFM (mai filename, note, ID di campione o tag degli artefatti).
Confronta un classificatore di maggioranza e ExtraTrees mediante CV
esplorativa a gruppi; le coppie trace/retrace plausibili restano nello
stesso fold. Le classi con meno di cinque immagini non entrano in questo
primo benchmark, ma conservano tutte le etichette nel database.

Prerequisito ML opzionale:

```powershell
cd C:\AFM_image_wizard
.\.venv\Scripts\python.exe -m pip install -e ".[ml]"
.\.venv\Scripts\python.exe -B -m pytest tests\test_ml_baseline.py -q
.\.venv\Scripts\python.exe -B -m afm_copilot.ml_baseline
```

Il comando esegue il training **solo temporaneamente** sul PC;
non salva modelli, non modifica immagini o ricette Gwyddion e stampa
metriche aggregate (out-of-fold macro-F1, accuracy e recall per classe).
Non e' una stima di generalizzazione indipendente: la separazione
trace/retrace e la dedup SHA non certificano l'indipendenza di campioni
o l'equivalenza fra esportazioni TIFF e IBW.

Si devono verificare in seguito i duplicati cross-format e la coppia
di etichette in conflitto senza riscrivere i dati etichettati.
Un futuro pool non etichettato puo' servire a osservare i risultati
del modello, ma non a misurare l'accuratezza senza riferimento esperto.
