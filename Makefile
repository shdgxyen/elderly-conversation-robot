PYTHON ?= python3
VENV := pi-backend/.venv
VENV_PYTHON := $(VENV)/bin/python
INSTALL_STAMP := $(VENV)/.requirements-installed

.PHONY: setup run test mock-esp32 mock-audio

setup: $(INSTALL_STAMP)

$(INSTALL_STAMP): pi-backend/requirements.txt
	$(PYTHON) -m venv $(VENV)
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PYTHON) -m pip install -r pi-backend/requirements.txt
	touch $(INSTALL_STAMP)

run: setup
	cd pi-backend && .venv/bin/python -m app

test: setup
	cd pi-backend && .venv/bin/python -m pytest -q

mock-esp32: setup
	$(VENV_PYTHON) tools/mock_esp32.py

mock-audio:
	$(PYTHON) tools/mock_audio.py --output /tmp/elder-companion-mock.wav
