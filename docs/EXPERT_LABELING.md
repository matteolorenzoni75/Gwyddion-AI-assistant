# AFM Expert Labeler — scansioni una alla volta

**Avvio:** eseguire `AFM_Expert_Labeler.bat` da `C:\AFM_image_wizard`,
oppure `\.venv\Scripts\python.exe -m afm_copilot.labeler` per visualizzare
eventuali errori.

La maschera di labeling e' indipendente dalle ricette di processing. Mostra
una scansione per volta nel viewer scientifico (calibrazione XY/Z, range,
profilo, zoom, colori) e permette di attribuire:

- classe morfologica principale, includendo `uncertain` e `mixed`;
- uno o piu' artefatti (tilt, bow, banding, drift, spikes, double tip, ...);
- qualita' della scansione e confidenza dell'esperto 1-5;
- ID del campione/sessione strumentale, per evitare leakage fra split;
- ruolo esplicito: `unassigned`, `train`, `validation`, `holdout`;
- note libere dell'operatore;
- dimensioni XY, risoluzione, range Z, Sq grezzo e descrittori numerici
  del motore AFM Copilot (quando calcolabili).

I dati e le etichette vengono salvati **soltanto sul PC**, in
`%USERPROFILE%\AFM_Copilot_Private_Audits\labeling\labels.sqlite3`,
fuori dalla repository pubblica. Non caricare mai il database su GitHub:
contiene percorsi e note riservate.

## Sessioni incrementali

La prima apertura importa ricorsivamente i formati riconosciuti da
`C:\AFM_Automation\OLD input IMAGES`. Per aggiungere altri scansioni,
cliccare **Add folder (recursive)**. La reimportazione non cancella mai
le etichette gia' salvate. Il contatore visualizza immagini etichettate e
quote di train/validation/holdout; **Next unlabelled** torna al prossimo
esempio in sospeso. Le modifiche vengono persistite tramite **Save label**
oppure **Save + next**; **Skip** non salva.

Il corpus dell'utente inizialmente selezionato comprende 244 immagini,
ma l'inventario dello stesso archivio ha trovato 268 file fisici e 257
sequenze di byte distinte. Sono **numeri diversi**: non si assume che
tutti i 268 siano membri del set di 244, ne' che i 13 non riconciliati
siano duplicati. Si possono importare nuovi gruppi nel tempo.

La classe e' scelta dall'esperto **guardando la topografia, non il filename**.
I descrittori sono osservazioni numeriche e non una predizione del modello.
Il file strumentale originale non viene modificato e le conversioni
Gwyddion rimangono in una directory temporanea separata per percorso.

## Divisione training/validation/holdout

Le 244 immagini possono fungere da corpus iniziale **ora che l'operatore
ne ha esplicitamente autorizzato il labeling supervisionato**.
Non si deve tuttavia usare tutto lo stesso corpus sia per addestrare
sia per misurare l'accuratezza finale.

Prima di selezionare un ruolo non `unassigned`, inserire l'ID di
campione/sessione. Il database impedisce di mettere nello split di train
un'immagine dello stesso gruppo o con gli stessi byte di una di holdout.
Scansioni diverse dello stesso campione devono avere lo **stesso ID**;
per immagini correlate ma non identiche e' compito dell'operatore non
assegnare gruppi diversi. Le classi `uncertain` non possono diventare
training truth.

Il labeling non crea ne' addestra ancora alcun classificatore. Una futura
pipeline dovra' estrarre i soli esempi approvati, fare il split per
campione e verificare l'accuratezza, inclusa la capacita' di astenersi.

## Test

```powershell
cd C:\AFM_image_wizard
git pull --ff-only origin dev/image-wizard
.\.venv\Scripts\python.exe -B -m pytest tests\test_labeling.py -q
.\.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m afm_copilot.labeler
```

**Non eseguire `git add .`** in presenza di dataset locali o report
privati. La PR verso `main` resta in bozza finche' la validazione Windows
e quella scientifica non sono completate.
