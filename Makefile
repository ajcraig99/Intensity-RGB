.PHONY: test smoke preview build-linux clean

test:
	python3 -m pytest tests/ -v

smoke:
	python3 -m intensity_rgb.cli clone --input carpark_stairs.e57 --output /tmp/clone.e57

preview:
	python3 -c "from tests.render_preview import render_preview; print('render_preview import OK')"

build-linux:
	bash build/build.sh

clean:
	rm -rf build/work dist tests/artifacts/*.png tests/artifacts/*.e57 __pycache__ */__pycache__ */*/__pycache__ *.egg-info
