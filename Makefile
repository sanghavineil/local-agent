.PHONY: sync sync-apply bootstrap bootstrap-apply adopt-skills doctor test init-project init-project-apply

sync:
	python3 scripts/local_agent.py sync

sync-apply:
	python3 scripts/local_agent.py sync --apply

bootstrap:
	python3 scripts/local_agent.py bootstrap --init-machine-local

bootstrap-apply:
	python3 scripts/local_agent.py bootstrap --apply --init-machine-local

adopt-skills:
	python3 scripts/local_agent.py bootstrap --apply --init-machine-local --adopt-existing-skills

doctor:
	python3 scripts/local_agent.py doctor

test:
	python3 -m unittest discover -s tests -v

init-project:
	python3 scripts/local_agent.py init-project . --with-impeccable-template

init-project-apply:
	python3 scripts/local_agent.py init-project . --apply --with-impeccable-template
