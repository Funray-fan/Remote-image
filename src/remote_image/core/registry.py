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


class VersionedPluginRegistry:
    """按名称和不可变版本精确解析模型，禁止静默切换权重。"""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], object] = {}

    def register(self, name: str, version: str, plugin: T) -> T:
        key = name.strip(), version.strip()
        if not all(key):
            raise ValueError("名称和版本不能为空")
        if key in self._items:
            raise ValueError(f"插件版本已注册: {key[0]}@{key[1]}")
        self._items[key] = plugin
        return plugin

    def get(self, name: str, version: str, expected_type: type[T] | None = None) -> T:
        key = name, version
        if key not in self._items:
            available = ", ".join(f"{n}@{v}" for n, v in sorted(self._items)) or "无"
            raise KeyError(f"未找到插件 {name}@{version}；可用插件: {available}")
        item = self._items[key]
        if expected_type is not None and not isinstance(item, expected_type):
            raise TypeError(f"插件 {name}@{version} 类型不符合要求")
        return item  # type: ignore[return-value]

    def identities(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted(self._items))

