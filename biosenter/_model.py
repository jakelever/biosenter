"""Resolves which spaCy sentence-splitter model biosenter uses by default.

`BIOSENTER_MODEL` overrides the bundled model with a path to any other
spaCy senter (e.g. a model trained locally with scripts/train_senter.py) --
useful for trying an in-progress retrain against real text without
reinstalling the package.
"""

import os
from pathlib import Path

MODEL_ENV_VAR = 'BIOSENTER_MODEL'

_BUNDLED_MODEL_PATH = Path(__file__).resolve().parent / 'model'


def resolve_model_path():
	"""-> path to the spaCy model to load: BIOSENTER_MODEL if set, else the
	model bundled with this package install."""
	override = os.environ.get(MODEL_ENV_VAR)
	if override:
		return override
	if not _BUNDLED_MODEL_PATH.is_dir():
		raise FileNotFoundError(
			f'No bundled model at {_BUNDLED_MODEL_PATH} and {MODEL_ENV_VAR} is not set. '
			'Install biosenter with its packaged model, or point BIOSENTER_MODEL at a '
			'trained senter (see scripts/train_senter.py).'
		)
	return str(_BUNDLED_MODEL_PATH)
