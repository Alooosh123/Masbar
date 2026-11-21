.PHONY: backend test web install seed

install:
	cd backend && python -m venv ../.venv && ../.venv/Scripts/python -m pip install -r requirements.txt
	cd web && npm install

backend:
	cd backend && ../.venv/Scripts/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8010

test:
	cd backend && ../.venv/Scripts/python -m pytest -q

web:
	cd web && npm run dev

seed:
	@echo "Sample knowledge base lives in data/kb and is loaded automatically."
