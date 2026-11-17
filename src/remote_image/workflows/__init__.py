"""端到端流程编排，避免业务模块彼此直接耦合。"""

from .damage import load_model, register_model, register_model_loader, run_damage

__all__ = ["load_model", "register_model", "register_model_loader", "run_damage"]

