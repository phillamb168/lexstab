UV := uv

.PHONY: install test validate smoke accept-demo report clean help

help:
	@echo "install      - sync locked dependencies"
	@echo "test         - full offline test suite (mocked providers)"
	@echo "validate     - schemas, prompts, artifacts, integrity, interfaces, manifest"
	@echo "smoke        - mocked end-to-end smoke run + evaluate + report"
	@echo "accept-demo  - full spec §49.16 acceptance demonstration (mocked)"
	@echo "clean        - remove caches and scratch runs"

install:
	$(UV) sync --frozen

test:
	$(UV) run pytest tests/ -q

validate:
	$(UV) run lexstab schema validate
	$(UV) run lexstab domain validate
	$(UV) run lexstab cases validate
	$(UV) run lexstab requests validate
	$(UV) run lexstab contexts validate
	$(UV) run lexstab renderings validate
	$(UV) run lexstab memory validate
	$(UV) run lexstab procedures validate
	$(UV) run lexstab interfaces validate
	$(UV) run lexstab interfaces compare
	$(UV) run lexstab integrity
	$(UV) run lexstab benchmark verify --manifest dataset/manifests/benchmark-v0.1.0.json

smoke:
	$(UV) run lexstab run --config config/run.smoke.yaml --run-id make-smoke
	$(UV) run lexstab evaluate --run runs/make-smoke
	$(UV) run lexstab report --run runs/make-smoke
	@echo "report: runs/make-smoke/report.md"

accept-demo:
	$(UV) run python scripts/acceptance_demo.py

clean:
	rm -rf .pytest_cache .cache runs/make-smoke runs/ci-smoke runs/smoke-0001
