# machine-learning/scripts/export_serving_model.py
"""
Write the MLflow pyfunc that KServe serves, from the current folds, to a plain directory (no tracking server).
Same arguments as train.py logs to MLflow. Used for local deploys:
    python machine-learning/scripts/export_serving_model.py artifacts/local/serving-model
"""
import os
import shutil
import sys

import cloudpickle
import mlflow
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipelines import train  # noqa: E402

# by value: the serving image has no `pipelines` package (train.py run as __main__ gets this for free)
cloudpickle.register_pickle_by_value(train)


def main(out_dir: str):
    shutil.rmtree(out_dir, ignore_errors=True)
    mlflow.pyfunc.save_model(out_dir, **train.serving_model_kwargs(np.zeros((5, train.EXPECTED_DIM))))
    print(f"[INFO] serving model written to {out_dir}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "artifacts/local/serving-model")
