"""安装与 v2 契约的最小自检入口。"""

import json
from pathlib import Path

from remote_image.core.contracts import DamageRequest
from remote_image.core.serialization import from_payload, to_payload
from remote_image.core.validation import validate_contract


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    fixture = root / "tests" / "fixtures" / "contracts_v2" / "damage_request_valid.json"
    if not fixture.is_file():
        print("Remote Image 已安装；仓库外运行时请由项目配置提供契约输入。")
        return
    request = from_payload(DamageRequest, json.loads(fixture.read_text(encoding="utf-8")))
    validate_contract(request)
    print("Remote Image v2 契约自检通过")
    print(json.dumps(to_payload(request), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
