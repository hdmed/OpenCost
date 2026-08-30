# Usage AI : rapport hors-ligne des sessions OpenCode

![Dashboard](assets/thumbnail.png)

Extrait l'utilisation des modÃ¨les IA depuis la base **locale** d'OpenCode
(`opencode.db`, SQLite) et gÃ©nÃ¨re un rapport visuel **100 % hors-ligne** :
un fichier HTML unique, ouvrable par double-clic, avec filtres,
graphes et personnalisation des coÃ»ts par modÃ¨le.

## PrÃ©requis

- Python 3.10+ (stdlib uniquement, **aucun `pip install`**)
- OpenCode ayant des sessions enregistrÃ©es (chemin par dÃ©faut ci-dessous)

Base de donnÃ©es par dÃ©faut :

- Windows : `%USERPROFILE%\.local\share\opencode\opencode.db`
- macOS/Linux : `~/.local/share/opencode/opencode.db`

## Utilisation rapide

```powershell
python extract.py            # 1. extrait les sessions (delta incrÃ©mental)
python build_report.py       # 2. gÃ©nÃ¨re dist/report.html
start dist\report.html       # 3. ouvre le rapport (hors-ligne)
```

Ou tout-en-un :

```powershell
python extract.py --full ; python build_report.py --strict ; start dist\report.html
```

Si `make` est disponible : `make report`, `make open`, `make all`.

## Commandes `extract.py`

| Commande | Effet |
|---|---|
| `python extract.py` | extraction incrÃ©mentale (depuis le dernier sync) |
| `python extract.py --full` | rÃ©-extraction complÃ¨te (aprÃ¨s modification de `config/pricing.json`) |
| `python extract.py --db <chemin>` | base OpenCode personnalisÃ©e |
| `python extract.py --watch` | surveille `opencode.db` (watchdog si dispo, sinon poll) et re-extrait |
| `python extract.py --watch --build` | idem + rÃ©gÃ©nÃ¨re `dist/report.html` |

Variable d'environnement : `OPENCODE_DB` (chemin vers la base).

## Personnalisation des coÃ»ts par modÃ¨le

Ã‰ditez `config/pricing.json` â€” prix pour **1 million de tokens (USD)** ;
la clÃ© est `providerID/modelID` :

```json
{
  "models": {
    "opencode/big-pickle": {
      "input_per_1M": 2.5,
      "output_per_1M": 10.0,
      "cache_read_per_1M": 1.0,
      "cache_write_per_1M": 2.5
    }
  }
}
```

- Un modÃ¨le **absent** de la liste garde le coÃ»t **calculÃ© par OpenCode**.
- AprÃ¨s Ã©dition : `python extract.py --full ; python build_report.py`.
- Dans le rapport, le panneau Â« Personnaliser les coÃ»ts Â» est **live** : la saisie recalcule instantanÃ©ment KPIs/graphes/table, sauvegarde un brouillon `localStorage` et `Exporter pricing.json` tÃ©lÃ©charge le fichier (remplacer `config/pricing.json` puis `--full` pour pÃ©renniser). Bouton ðŸŒ“ thÃ¨me clair/sombre.
- `python build_report.py --external` : `dataset.json` externe (fetch) pour gros volumes (>10k sessions) au lieu dâ€™inline.

## Le rapport (`dist/report.html`)

- KPI : coÃ»t total, tokens entrÃ©s/sortis, cache, coÃ»t/1k tokens, sessions
- Graphes : coÃ»t & tokens/jour par modÃ¨le, donut coÃ»t par modÃ¨le,
  coÃ»t par agent, histogramme coÃ»t/session, ratio cache
- Filtres : plage de dates, modÃ¨les (multi), agent, projet, coÃ»t min/max, recherche
- Table dÃ©taillÃ©e triable (pagination 100, `aria-live`) + export CSV/JSON (live)
- Aucun appel rÃ©seau au chargement (sauf `--external`) : Chart.js et donnÃ©es inlinÃ©s
- `make test` : `py_compile` + `unittest` (7 tests) ; CI GitHub Actions

## Structure

```
config/pricing.json      # coÃ»ts personnalisÃ©s par modÃ¨le (Ã©ditable)
data/dataset.json        # donnÃ©es agrÃ©gÃ©es (gÃ©nÃ©rÃ©es, non versionnÃ©es)
data/sync_state.json     # Ã©tat du sync incrÃ©mental (gÃ©nÃ©rÃ©)
assets/chart.umd.min.js  # Chart.js embarquÃ© au build (offline)
extract.py               # lecture opencode.db -> dataset.json
build_report.py          # dataset.json -> dist/report.html
dist/report.html         # rapport final, unique et hors-ligne
```
