"""Checkpointing and model management utilities."""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import torch


class CheckpointManager:
    """Manages model checkpoints with automatic cleanup and recovery."""

    def __init__(
        self,
        checkpoint_dir: str,
        max_checkpoints: int = 5,
        save_best: bool = True,
        metric_for_best: str = "loss",
        minimize_metric: bool = True,
        save_optimizer: bool = True,
        save_scheduler: bool = True,
    ):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        self.max_checkpoints = max_checkpoints
        self.save_best = save_best
        self.metric_for_best = metric_for_best
        self.minimize_metric = minimize_metric
        self.save_optimizer = save_optimizer
        self.save_scheduler = save_scheduler

        # Track checkpoints
        self.checkpoint_history: list[dict[str, Any]] = []
        self.best_metric = float("inf") if minimize_metric else float("-inf")
        self.best_checkpoint_path: str | None = None

        # Setup logging
        self.logger = logging.getLogger(__name__)

        # Load existing checkpoint history
        self._load_checkpoint_history()

    def save_checkpoint(
        self,
        model: torch.nn.Module,
        step: int,
        epoch: int,
        metrics: dict[str, float],
        optimizer: torch.optim.Optimizer | None = None,
        scheduler: Any | None = None,
        extra_data: dict[str, Any] | None = None,
    ) -> str:
        """Save a model checkpoint."""

        # Create checkpoint data
        checkpoint_data = {
            "model_state_dict": model.state_dict(),
            "step": step,
            "epoch": epoch,
            "metrics": metrics,
            "timestamp": datetime.now().isoformat(),
            "extra_data": extra_data or {},
        }

        # Add optimizer state
        if optimizer is not None and self.save_optimizer:
            checkpoint_data["optimizer_state_dict"] = optimizer.state_dict()

        # Add scheduler state
        if scheduler is not None and self.save_scheduler:
            if hasattr(scheduler, "state_dict"):
                checkpoint_data["scheduler_state_dict"] = scheduler.state_dict()

        # Generate checkpoint filename
        checkpoint_name = f"checkpoint_step_{step}_epoch_{epoch}.pt"
        checkpoint_path = self.checkpoint_dir / checkpoint_name

        # Save checkpoint
        torch.save(checkpoint_data, checkpoint_path)
        self.logger.info(f"Saved checkpoint: {checkpoint_path}")

        # Update checkpoint history
        checkpoint_info = {
            "path": str(checkpoint_path),
            "step": step,
            "epoch": epoch,
            "metrics": metrics,
            "timestamp": checkpoint_data["timestamp"],
        }
        self.checkpoint_history.append(checkpoint_info)

        # Check if this is the best checkpoint
        if self.save_best and self.metric_for_best in metrics:
            current_metric = metrics[self.metric_for_best]
            is_best = (self.minimize_metric and current_metric < self.best_metric) or (
                not self.minimize_metric and current_metric > self.best_metric
            )

            if is_best:
                self.best_metric = current_metric
                self.best_checkpoint_path = str(checkpoint_path)

                # Save as best checkpoint
                best_checkpoint_path = self.checkpoint_dir / "best_checkpoint.pt"
                shutil.copy2(checkpoint_path, best_checkpoint_path)
                self.logger.info(
                    f"New best checkpoint: {best_checkpoint_path} (metric: {current_metric:.4f})"
                )

        # Cleanup old checkpoints
        self._cleanup_checkpoints()

        # Save checkpoint history
        self._save_checkpoint_history()

        return str(checkpoint_path)

    def load_checkpoint(
        self, checkpoint_path: str | None = None, load_best: bool = False
    ) -> dict[str, Any]:
        """Load a checkpoint."""

        if load_best:
            checkpoint_path_obj = self.checkpoint_dir / "best_checkpoint.pt"
        elif checkpoint_path is None:
            # Load latest checkpoint
            latest_path = self.get_latest_checkpoint()
            if latest_path is None:
                raise FileNotFoundError("No checkpoints found")
            checkpoint_path_obj = Path(latest_path)
        else:
            checkpoint_path_obj = Path(checkpoint_path)

        if not checkpoint_path_obj.exists():
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path_obj}")

        self.logger.info(f"Loading checkpoint: {checkpoint_path_obj}")
        checkpoint_data: dict[str, Any] = torch.load(checkpoint_path_obj, map_location="cpu")  # type: ignore[assignment]

        return checkpoint_data

    def load_model_from_checkpoint(
        self,
        model: torch.nn.Module,
        checkpoint_path: str | None = None,
        load_best: bool = False,
        strict: bool = True,
    ) -> dict[str, Any]:
        """Load model state from checkpoint."""

        checkpoint_data = self.load_checkpoint(checkpoint_path, load_best)

        # Load model state
        if "model_state_dict" in checkpoint_data:
            model.load_state_dict(checkpoint_data["model_state_dict"], strict=strict)
            self.logger.info("Loaded model state from checkpoint")
        else:
            self.logger.warning("No model state found in checkpoint")

        return checkpoint_data

    def resume_training(
        self,
        model: torch.nn.Module,
        optimizer: torch.optim.Optimizer | None = None,
        scheduler: Any | None = None,
        checkpoint_path: str | None = None,
    ) -> dict[str, Any]:
        """Resume training from checkpoint."""

        checkpoint_data = self.load_checkpoint(checkpoint_path)

        # Load model state
        if "model_state_dict" in checkpoint_data:
            model.load_state_dict(checkpoint_data["model_state_dict"])
            self.logger.info("Resumed model state from checkpoint")

        # Load optimizer state
        if optimizer is not None and "optimizer_state_dict" in checkpoint_data:
            optimizer.load_state_dict(checkpoint_data["optimizer_state_dict"])
            self.logger.info("Resumed optimizer state from checkpoint")

        # Load scheduler state
        if scheduler is not None and "scheduler_state_dict" in checkpoint_data:
            if hasattr(scheduler, "load_state_dict"):
                scheduler.load_state_dict(checkpoint_data["scheduler_state_dict"])
                self.logger.info("Resumed scheduler state from checkpoint")

        return checkpoint_data

    def get_latest_checkpoint(self) -> str | None:
        """Get path to the latest checkpoint."""
        if not self.checkpoint_history:
            return None

        # Sort by step (latest first)
        sorted_checkpoints = sorted(
            self.checkpoint_history, key=lambda x: x["step"], reverse=True
        )

        # Find first existing checkpoint
        for checkpoint_info in sorted_checkpoints:
            if Path(checkpoint_info["path"]).exists():
                return checkpoint_info["path"]  # type: ignore[no-any-return]

        return None

    def get_best_checkpoint(self) -> str | None:
        """Get path to the best checkpoint."""
        best_path = self.checkpoint_dir / "best_checkpoint.pt"
        if best_path.exists():
            return str(best_path)
        return self.best_checkpoint_path

    def list_checkpoints(self) -> list[dict[str, Any]]:
        """List all available checkpoints."""
        available_checkpoints = []
        for checkpoint_info in self.checkpoint_history:
            if Path(checkpoint_info["path"]).exists():
                available_checkpoints.append(checkpoint_info)

        return sorted(available_checkpoints, key=lambda x: x["step"], reverse=True)

    def delete_checkpoint(self, checkpoint_path: str) -> None:
        """Delete a specific checkpoint."""
        checkpoint_path_obj = Path(checkpoint_path)
        if checkpoint_path_obj.exists():
            checkpoint_path_obj.unlink()
            self.logger.info(f"Deleted checkpoint: {checkpoint_path_obj}")

            # Remove from history
            self.checkpoint_history = [
                info
                for info in self.checkpoint_history
                if info["path"] != str(checkpoint_path_obj)
            ]
            self._save_checkpoint_history()

    def _cleanup_checkpoints(self) -> None:
        """Remove old checkpoints based on max_checkpoints setting."""
        if self.max_checkpoints <= 0:
            return

        # Get existing checkpoints sorted by step
        existing_checkpoints = []
        for checkpoint_info in self.checkpoint_history:
            if Path(checkpoint_info["path"]).exists():
                existing_checkpoints.append(checkpoint_info)

        existing_checkpoints.sort(key=lambda x: x["step"], reverse=True)

        # Remove old checkpoints
        checkpoints_to_remove = existing_checkpoints[self.max_checkpoints :]
        for checkpoint_info in checkpoints_to_remove:
            checkpoint_path = Path(checkpoint_info["path"])

            # Don't delete the best checkpoint
            if str(checkpoint_path) != self.best_checkpoint_path:
                try:
                    checkpoint_path.unlink()
                    self.logger.info(f"Cleaned up old checkpoint: {checkpoint_path}")
                except Exception as e:
                    self.logger.warning(
                        f"Failed to delete checkpoint {checkpoint_path}: {e}"
                    )

        # Update history to only include existing checkpoints
        self.checkpoint_history = [
            info for info in self.checkpoint_history if Path(info["path"]).exists()
        ]

    def _save_checkpoint_history(self) -> None:
        """Save checkpoint history to disk."""
        history_path = self.checkpoint_dir / "checkpoint_history.json"
        history_data = {
            "checkpoint_history": self.checkpoint_history,
            "best_metric": self.best_metric,
            "best_checkpoint_path": self.best_checkpoint_path,
            "metric_for_best": self.metric_for_best,
            "minimize_metric": self.minimize_metric,
        }

        with open(history_path, "w") as f:
            json.dump(history_data, f, indent=2)

    def _load_checkpoint_history(self) -> None:
        """Load checkpoint history from disk."""
        history_path = self.checkpoint_dir / "checkpoint_history.json"

        if history_path.exists():
            try:
                with open(history_path) as f:
                    history_data = json.load(f)

                self.checkpoint_history = history_data.get("checkpoint_history", [])
                self.best_metric = history_data.get(
                    "best_metric",
                    float("inf") if self.minimize_metric else float("-inf"),
                )
                self.best_checkpoint_path = history_data.get("best_checkpoint_path")

                # Filter out non-existent checkpoints
                self.checkpoint_history = [
                    info
                    for info in self.checkpoint_history
                    if Path(info["path"]).exists()
                ]

                self.logger.info(
                    f"Loaded checkpoint history with {len(self.checkpoint_history)} checkpoints"
                )

            except Exception as e:
                self.logger.warning(f"Failed to load checkpoint history: {e}")
                self.checkpoint_history = []

    def export_model(
        self,
        model: torch.nn.Module,
        export_path: str,
        checkpoint_path: str | None = None,
        load_best: bool = False,
        export_format: str = "torch",
    ) -> None:
        """Export model for deployment."""

        # Load checkpoint if specified
        if checkpoint_path or load_best:
            self.load_model_from_checkpoint(model, checkpoint_path, load_best)

        export_path_obj = Path(export_path)
        export_path_obj.parent.mkdir(parents=True, exist_ok=True)

        if export_format == "torch":
            # Save complete model
            torch.save(model, export_path_obj)
        elif export_format == "state_dict":
            # Save only state dict
            torch.save(model.state_dict(), export_path_obj)
        elif export_format == "onnx":
            try:
                # Export to ONNX (requires example input)
                model.eval()
                # This would need example input - placeholder implementation
                self.logger.warning(
                    "ONNX export requires example input - not implemented"
                )
            except ImportError:
                self.logger.error("ONNX export requires torch.onnx")
        elif export_format == "torchscript":
            try:
                # Export to TorchScript
                model.eval()
                scripted_model = torch.jit.script(model)
                scripted_model.save(str(export_path_obj))
            except Exception as e:
                self.logger.error(f"TorchScript export failed: {e}")
        else:
            raise ValueError(f"Unsupported export format: {export_format}")

        self.logger.info(f"Exported model to: {export_path_obj}")

    def get_checkpoint_info(self, checkpoint_path: str) -> dict[str, Any]:
        """Get information about a checkpoint without loading the full model."""
        checkpoint_path_obj = Path(checkpoint_path)

        if not checkpoint_path_obj.exists():
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path_obj}")

        # Load only metadata
        checkpoint_data = torch.load(checkpoint_path_obj, map_location="cpu")

        info = {
            "step": checkpoint_data.get("step"),
            "epoch": checkpoint_data.get("epoch"),
            "metrics": checkpoint_data.get("metrics", {}),
            "timestamp": checkpoint_data.get("timestamp"),
            "file_size": checkpoint_path_obj.stat().st_size,
            "has_optimizer": "optimizer_state_dict" in checkpoint_data,
            "has_scheduler": "scheduler_state_dict" in checkpoint_data,
        }

        return info
