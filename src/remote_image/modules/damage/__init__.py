"""C2 建筑灾损模型与推理适配模块。"""

from .baseline_adapter import EmptyBaselineDamageAdapter
from .contract_check import ContractTestReport, check_adapter_contract

__all__ = [
    "EmptyBaselineDamageAdapter",
    "ContractTestReport",
    "check_adapter_contract",
]
