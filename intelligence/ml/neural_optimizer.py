# -*- coding: utf-8 -*-
"""
Intelligence V6 - Neural Optimizer
PyTorch implementation of an Attention-augmented sequential market analysis engine.
Supports Temporal Memory (GRU) + Self-Attention for superior pattern recognition.
"""
import os
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    torch = None  # type: ignore
    nn = None     # type: ignore
import numpy as np
import pandas as pd
from typing import List, Optional, Tuple

if not TORCH_AVAILABLE:
    class AttentionLayer:
        pass      # type: ignore

    class NeuralV8Model:
        pass       # type: ignore

    class SequentialTrainer:
        pass   # type: ignore

    _TRAINER_CACHE = None

else:
    class AttentionLayer(nn.Module):
        """Self-Attention mechanism to identify critical points in a time series."""
        def __init__(self, hidden_size: int):
            super(AttentionLayer, self).__init__()
            self.attention = nn.Sequential(
                nn.Linear(hidden_size, hidden_size),
                nn.Tanh(),
                nn.Linear(hidden_size, 1)
            )

        def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
            weights = self.attention(x)
            weights = torch.softmax(weights, dim=1)
            context = torch.sum(weights * x, dim=1)
            return context, weights

    class NeuralV8Model(nn.Module):
        """Intelligence V8: Hardened Attention-GRU Hybrid."""
        def __init__(self, input_size: int, hidden_size: int = 64, num_layers: int = 2):
            super(NeuralV8Model, self).__init__()
            self.hidden_size = hidden_size
            self.bn_input = nn.BatchNorm1d(input_size)
            self.gru = nn.GRU(
                input_size, hidden_size, num_layers,
                batch_first=True,
                dropout=0.3 if num_layers > 1 else 0,
                bidirectional=True
            )
            self.attention = AttentionLayer(hidden_size * 2)
            self.fc = nn.Sequential(
                nn.Linear(hidden_size * 2, hidden_size),
                nn.BatchNorm1d(hidden_size),
                nn.LeakyReLU(0.1),
                nn.Dropout(0.4),
                nn.Linear(hidden_size, 1)
            )
            self.sigmoid = nn.Sigmoid()

        def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
            b, s, f = x.shape
            x_flat = x.view(-1, f)
            x_bn = self.bn_input(x_flat).view(b, s, f)
            gru_out, _ = self.gru(x_bn)
            context, weights = self.attention(gru_out)
            logits = self.fc(context)
            return self.sigmoid(logits), weights

    class SequentialTrainer:
        """Orchestrates training and inference for the Intelligence V8 Neural Optimizer."""
        def __init__(self, input_size: int, model_path: str = "data/neural_v8.pth"):
            self.device = torch.device("cpu")
            self.model = NeuralV8Model(input_size=input_size).to(self.device)
            self.model_path = model_path
            self._load_model()

        def _load_model(self):
            if os.path.exists(self.model_path):
                try:
                    state_dict = torch.load(self.model_path, map_location=self.device)
                    self.model.load_state_dict(state_dict)
                    self.model.eval()
                except Exception as e:
                    print(f"NeuralV8: Error loading weights: {e}")

        def save_model(self):
            os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
            torch.save(self.model.state_dict(), self.model_path)

        def predict(self, sequence: np.ndarray) -> Tuple[float, List[float]]:
            self.model.eval()
            with torch.no_grad():
                tensor_x = torch.from_numpy(sequence).unsqueeze(0).float().to(self.device)
                prob, weights = self.model(tensor_x)
                attn_list = weights.squeeze().tolist()
                if isinstance(attn_list, float):
                    attn_list = [attn_list]
            return float(prob.item()), attn_list

        def train_on_sequences(self, X: np.ndarray, y: np.ndarray, epochs: int = 150, lr: float = 0.001):
            split_idx = int(len(X) * 0.8)
            X_train, X_val = X[:split_idx], X[split_idx:]
            y_train, y_val = y[:split_idx], y[split_idx:]
            if len(X_val) == 0:
                X_train, y_train = X, y
                X_val, y_val = X, y

            self.model.train()
            optimizer = optim.Adam(self.model.parameters(), lr=lr, weight_decay=1e-4)

            X_t = torch.from_numpy(X_train).float().to(self.device)
            y_t = torch.from_numpy(y_train).float().unsqueeze(1).to(self.device)
            X_v = torch.from_numpy(X_val).float().to(self.device)
            y_v = torch.from_numpy(y_val).float().unsqueeze(1).to(self.device)

            def risk_aware_bce(output, target, fp_weight=3.0):
                epsilon = 1e-7
                output = torch.clamp(output, epsilon, 1.0 - epsilon)
                loss = target * torch.log(output) + fp_weight * (1.0 - target) * torch.log(1.0 - output)
                return torch.neg(torch.mean(loss))

            best_val_loss = float('inf')
            patience = 15
            trigger_times = 0

            for epoch in range(epochs):
                self.model.train()
                optimizer.zero_grad()
                outputs, _ = self.model(X_t)
                batch_loss = risk_aware_bce(outputs, y_t)
                batch_loss.backward()
                optimizer.step()

                self.model.eval()
                with torch.no_grad():
                    val_outputs, _ = self.model(X_v)
                    val_loss = risk_aware_bce(val_outputs, y_v)

                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    trigger_times = 0
                    self.save_model()
                else:
                    trigger_times += 1
                    if trigger_times >= patience:
                        break

            return best_val_loss.item()

    _TRAINER_CACHE = None


def get_neural_optimizer(input_size: int = 24):
    if not TORCH_AVAILABLE:
        return None
    global _TRAINER_CACHE
    if _TRAINER_CACHE is None:
        _TRAINER_CACHE = SequentialTrainer(input_size=input_size)
    return _TRAINER_CACHE


get_neural_trainer = get_neural_optimizer
