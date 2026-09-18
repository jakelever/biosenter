"""Train the biomedical sentence splitter (a spaCy `senter`) on the data
built by prepare_pmc_senter_corpus.py.

Thin wrapper around `spacy train` so the run lands in the same runs/
layout as everything else and the config lives in the repo. The trained
model is written to <run_dir>/<run_name>/model-best -- copy that into
biosenter/model/ (or point BIOSENTER_MODEL at it) to use it, see
biosenter/_model.py.
"""

import argparse
from pathlib import Path

from spacy.cli.train import train as spacy_train

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / 'biosenter' / 'senter' / 'config.cfg'


def main():
	parser = argparse.ArgumentParser(description='Train the spaCy senter sentence splitter')
	parser.add_argument('--data_dir', required=True, type=str, help='Directory of .spacy files from prepare_pmc_senter_corpus.py')
	parser.add_argument('--run_dir', default='runs', type=str, help='Parent directory for run outputs')
	parser.add_argument('--run_name', required=True, type=str, help='Name of this run (subdirectory of run_dir)')
	parser.add_argument('--config', default=str(DEFAULT_CONFIG), type=str, help='spaCy training config')
	parser.add_argument('--train', default='pmc_train.spacy', type=str, help='Training set filename within data_dir')
	parser.add_argument('--val', default='pmc_val.spacy', type=str, help='Validation set filename within data_dir')
	parser.add_argument('--gpu_id', default=-1, type=int, help='GPU to use, or -1 for CPU (the default: this model is small)')
	args = parser.parse_args()

	data_dir = Path(args.data_dir)
	output_path = Path(args.run_dir) / args.run_name
	output_path.mkdir(parents=True, exist_ok=True)

	spacy_train(
		Path(args.config),
		output_path,
		use_gpu=args.gpu_id,
		overrides={
			'paths.train': str(data_dir / args.train),
			'paths.dev': str(data_dir / args.val),
		},
	)

	print(f"Best model: {output_path / 'model-best'}")


if __name__ == '__main__':
	main()
