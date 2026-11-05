# pinterest-pins

Immagini dei pin (`pin/`) e pubblicazione su Pinterest.

- `coda/*.csv`: pin da pubblicare via API, formato bulk Pinterest. "Publish date" in UTC.
- `pubblicati.csv`: registro scritto dalla GitHub Action "Pubblica pin" (ogni giorno 14:05 UTC, max 2 pin per giro). Un pin gia' nel registro non viene ripubblicato.
- `csv/`: CSV caricati a mano in passato (storico, non toccati dall'Action).
- `tools/pinterest_api.py`: script (OAuth, pubblicazione, prove in sandbox).
