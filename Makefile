PY ?= python3

.PHONY: install test demo serve clean

install:
	$(PY) -m venv .venv && .venv/bin/pip install -r requirements.txt

test:
	.venv/bin/python -m pytest -q tests

demo:
	.venv/bin/python -m ida_dsp demo --out web/demo

serve:
	cd web && $(PY) -m http.server 8000 --bind 0.0.0.0

clean:
	rm -rf web/demo/audio .pytest_cache
