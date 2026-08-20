"""Lazy PyTorch sequence backends for the institutional Deep Learning Lab.

The module deliberately avoids importing torch at package import time. Streamlit can
therefore start without the optional runtime, while an explicitly selected PyTorch
challenger fails with a clear installation message.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import random
from typing import Any

import numpy as np

TORCH_MODEL_NAMES = ("PyTorch LSTM", "PyTorch GRU", "PyTorch Conv1D")
BACKEND_VERSION = "ML-NEURAL-BACKENDS-V1.0"


@dataclass(frozen=True)
class TorchSequenceConfig:
    epochs: int = 12
    batch_size: int = 32
    learning_rate: float = 1e-3
    weight_decay: float = 1e-4
    validation_fraction: float = 0.20
    minimum_validation_rows: int = 16
    patience: int = 4


def neural_runtime_status() -> dict[str, bool]:
    return {
        "pytorch": importlib.util.find_spec("torch") is not None,
        "tensorflow": importlib.util.find_spec("tensorflow") is not None,
    }


def _scale_sequences(
    X_train: np.ndarray,
    X_test: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    mean = np.nanmean(X_train, axis=(0, 1), keepdims=True)
    scale = np.nanstd(X_train, axis=(0, 1), keepdims=True)
    mean = np.nan_to_num(mean, nan=0.0, posinf=0.0, neginf=0.0)
    scale = np.where(np.isfinite(scale) & (scale > 1e-8), scale, 1.0)
    train = np.nan_to_num((X_train - mean) / scale, nan=0.0, posinf=0.0, neginf=0.0)
    test = np.nan_to_num((X_test - mean) / scale, nan=0.0, posinf=0.0, neginf=0.0)
    return train.astype(np.float32), test.astype(np.float32)


def _build_torch_model(model_name: str, n_features: int, torch: Any) -> Any:
    nn = torch.nn

    class RecurrentClassifier(nn.Module):
        def __init__(self, cell: str) -> None:
            super().__init__()
            recurrent = nn.LSTM if cell == "lstm" else nn.GRU
            self.encoder = recurrent(
                input_size=n_features,
                hidden_size=48,
                num_layers=1,
                batch_first=True,
            )
            self.head = nn.Sequential(
                nn.LayerNorm(48),
                nn.Linear(48, 32),
                nn.GELU(),
                nn.Dropout(0.20),
                nn.Linear(32, 1),
            )

        def forward(self, x: Any) -> Any:
            encoded, _ = self.encoder(x)
            return self.head(encoded[:, -1, :]).squeeze(-1)

    class CausalConvClassifier(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.network = nn.Sequential(
                nn.ConstantPad1d((2, 0), 0.0),
                nn.Conv1d(n_features, 48, kernel_size=3),
                nn.GELU(),
                nn.BatchNorm1d(48),
                nn.Dropout(0.20),
                nn.ConstantPad1d((2, 0), 0.0),
                nn.Conv1d(48, 32, kernel_size=3),
                nn.GELU(),
                nn.AdaptiveAvgPool1d(1),
            )
            self.head = nn.Sequential(
                nn.Flatten(),
                nn.Linear(32, 24),
                nn.GELU(),
                nn.Dropout(0.20),
                nn.Linear(24, 1),
            )

        def forward(self, x: Any) -> Any:
            return self.head(self.network(x.transpose(1, 2))).squeeze(-1)

    if model_name == "PyTorch LSTM":
        return RecurrentClassifier("lstm")
    if model_name == "PyTorch GRU":
        return RecurrentClassifier("gru")
    if model_name == "PyTorch Conv1D":
        return CausalConvClassifier()
    raise ValueError(f"Architecture PyTorch inconnue : {model_name}")


def predict_torch_sequence_model(
    model_name: str,
    X_train_sequence: np.ndarray,
    y_train: np.ndarray,
    X_test_sequence: np.ndarray,
    *,
    random_state: int = 42,
    purge_bars: int = 20,
    config: TorchSequenceConfig | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if model_name not in TORCH_MODEL_NAMES:
        raise ValueError(f"Modèle PyTorch inconnu : {model_name}")
    if importlib.util.find_spec("torch") is None:
        raise RuntimeError(
            "PyTorch runtime absent. Installe requirements-ml.txt avant "
            "de sélectionner un challenger PyTorch."
        )

    import torch
    from torch.utils.data import DataLoader, TensorDataset

    from .sequence_engine import apply_temperature, fit_temperature

    cfg = config or TorchSequenceConfig()
    X_train = np.asarray(X_train_sequence, dtype=np.float32)
    X_test = np.asarray(X_test_sequence, dtype=np.float32)
    y = np.asarray(y_train, dtype=np.float32).reshape(-1)
    if X_train.ndim != 3 or X_test.ndim != 3:
        raise ValueError("Les tenseurs PyTorch doivent avoir la forme [sample, lookback, feature].")
    if len(X_train) != len(y):
        raise ValueError("X_train et y_train doivent avoir la même longueur.")
    if len(np.unique(y.astype(int))) < 2:
        raise ValueError("Le train PyTorch doit contenir les deux classes.")

    X_train, X_test = _scale_sequences(X_train, X_test)
    random.seed(random_state)
    np.random.seed(random_state)
    torch.manual_seed(random_state)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(random_state)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    validation_rows = max(
        int(cfg.minimum_validation_rows),
        int(round(len(y) * float(cfg.validation_fraction))),
    )
    fit_end = len(y) - validation_rows - int(max(0, purge_bars))
    if fit_end < 32:
        fit_end = len(y)
        validation_start = len(y)
    else:
        validation_start = fit_end + int(max(0, purge_bars))

    X_fit = X_train[:fit_end]
    y_fit = y[:fit_end]
    X_validation = X_train[validation_start:]
    y_validation = y[validation_start:]

    model = _build_torch_model(model_name, X_train.shape[2], torch).to(device)
    positives = max(float(y_fit.sum()), 1.0)
    negatives = max(float(len(y_fit) - y_fit.sum()), 1.0)
    pos_weight = torch.tensor(
        [float(np.clip(negatives / positives, 0.25, 4.0))],
        dtype=torch.float32,
        device=device,
    )
    criterion = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(cfg.learning_rate),
        weight_decay=float(cfg.weight_decay),
    )
    generator = torch.Generator().manual_seed(random_state)
    loader = DataLoader(
        TensorDataset(torch.from_numpy(X_fit), torch.from_numpy(y_fit)),
        batch_size=min(int(cfg.batch_size), max(1, len(X_fit))),
        shuffle=True,
        generator=generator,
    )

    best_state = None
    best_loss = float("inf")
    patience_left = int(cfg.patience)
    epochs_run = 0
    for epoch in range(max(1, int(cfg.epochs))):
        model.train()
        for batch_x, batch_y in loader:
            batch_x = batch_x.to(device)
            batch_y = batch_y.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(batch_x), batch_y)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
        epochs_run = epoch + 1

        if len(X_validation) == 0:
            continue
        model.eval()
        with torch.no_grad():
            val_logits = model(torch.from_numpy(X_validation).to(device))
            val_loss = float(criterion(val_logits, torch.from_numpy(y_validation).to(device)).item())
        if val_loss < best_loss - 1e-5:
            best_loss = val_loss
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            patience_left = int(cfg.patience)
        else:
            patience_left -= 1
            if patience_left <= 0:
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()

    def probability(array: np.ndarray) -> np.ndarray:
        if len(array) == 0:
            return np.asarray([], dtype=float)
        with torch.no_grad():
            logits = model(torch.from_numpy(array).to(device))
            return torch.sigmoid(logits).detach().cpu().numpy().astype(float)

    train_probability = probability(X_train)
    test_probability = probability(X_test)
    temperature = 1.0
    if len(X_validation) >= int(cfg.minimum_validation_rows):
        raw_validation = probability(X_validation)
        temperature = float(fit_temperature(y_validation.astype(int), raw_validation))
        train_probability = apply_temperature(train_probability, temperature)
        test_probability = apply_temperature(test_probability, temperature)

    detail = {
        "backend": f"PyTorch {torch.__version__}",
        "architecture": model_name.removeprefix("PyTorch "),
        "device": str(device),
        "lookback_consumed": int(X_train.shape[1]),
        "features": int(X_train.shape[2]),
        "epochs_run": int(epochs_run),
        "validation_rows": int(len(X_validation)),
        "purge_bars": int(max(0, purge_bars)),
        "temperature": float(temperature),
        "engine_version": BACKEND_VERSION,
    }
    return train_probability, test_probability, detail
