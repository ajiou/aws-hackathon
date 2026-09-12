# SAM runs this in the Python 3.12 build container. Only backend sources are packaged.
build-ApiFunction:
	mkdir -p "$(ARTIFACTS_DIR)/backend"
	cp *.py "$(ARTIFACTS_DIR)/backend/"
	python3.12 -m pip install -r requirements.txt --target "$(ARTIFACTS_DIR)"
