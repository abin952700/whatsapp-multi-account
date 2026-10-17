.PHONY: mac-setup mac-run mac-build mac-open

mac-setup:
	bash scripts/setup_mac.sh

mac-run:
	bash scripts/start_mac.sh

mac-build:
	bash scripts/build_mac.sh

mac-open:
	@test -d dist/WhatsAppClient.app || (echo "dist/WhatsAppClient.app not found; run: make mac-build" && exit 1)
	open dist/WhatsAppClient.app
