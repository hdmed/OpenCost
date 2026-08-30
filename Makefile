PYTHON := python

.PHONY: extract report watch full all clean open test

# Extraction incrémentale (delta depuis le dernier sync)
extract:
	$(PYTHON) extract.py

# Ré-extraction complète (à utiliser après modification de config/pricing.json)
full:
	$(PYTHON) extract.py --full

# Génère dist/report.html (offline)
report:
	$(PYTHON) extract.py
	$(PYTHON) build_report.py

# Re-extraction complète + rapport
all: full report

# Surveille opencode.db et régénère automatiquement (extract + build)
watch:
	$(PYTHON) extract.py --watch --build

# Ouvre le rapport
open:
	$(PYTHON) -c "import os,webbrowser; webbrowser.open('file:///'+os.path.abspath('dist/report.html'))"

test:
	$(PYTHON) -m py_compile extract.py build_report.py
	$(PYTHON) -m unittest discover -s tests -v

# Remet à zéro le cache d'extraction (dataset + état de sync + rapport)
clean:
	$(PYTHON) -c "import os; [os.remove(f) for f in ['data/dataset.json','data/sync_state.json','dist/report.html'] if os.path.exists(f)]"