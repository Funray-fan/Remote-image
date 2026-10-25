"""模块注册表，主流程只通过名称查找实现。"""

from __future__ import annotations

from typing import TypeVar


T = TypeVar("T")


class PluginRegistry:
    def __init__(self) -> None:
        self._items: dict[str, object] = {}

    def register(self, name: str, plugin: T) -> T:
        if not name or name.strip() != name:
            raise ValueError("插件名称不能为空且不能含首尾空格")
        if name in self._items:
            raise ValueError(f"插件已注册: {name}")
        self._items[name] = plugin
        return plugin

    def get(self, name: str, expected_type: type[T] | None = None) -> T:
        try:
            item = self._items[name]
        except KeyError as error:
            available = ", ".join(sorted(self._items)) or "无"
            raise KeyError(f"未找到插件 {name}；可用插件: {available}") from error
        if expected_type is not None and not isinstance(item, expected_type):
            raise TypeError(f"插件 {name} 类型不符合要求")
        return item  # type: ignore[return-value]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._items))

