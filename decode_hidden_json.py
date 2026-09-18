"""Manually decrypt LamGroupNode hiddenJson without running any node code.

Examples:
    python decode_hidden_json.py workflow.json
    python decode_hidden_json.py workflow.json --node-id 81 -o node81.json
    python decode_hidden_json.py hiddenJson.txt -o decoded.json

Dependency: python -m pip install cryptography
"""

import argparse
import base64
import json
from pathlib import Path
import sys


def decrypt_hidden_json(ciphertext, password="555200"):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidTag

    if not isinstance(ciphertext, str):
        raise ValueError("hiddenJson 必须是字符串")
    ciphertext = ciphertext.strip()
    if len(ciphertext) <= 32:
        raise ValueError("hiddenJson 太短：需要 32 位 nonce 和 Base64 密文")
    try:
        nonce = bytes.fromhex(ciphertext[:32])
        payload = base64.b64decode(ciphertext[32:], validate=True)
    except ValueError as exc:
        raise ValueError("hiddenJson 格式错误：nonce 或 Base64 无效") from exc
    if len(nonce) != 16 or len(payload) < 16:
        raise ValueError("nonce 长度错误或缺少 GCM 认证标签")
    # Reproduce the original extension's trim, pad and truncate rules.
    key = password.strip().ljust(16)[:16].encode("utf-8")
    if len(key) not in (16, 24, 32):
        raise ValueError("密码编码后的长度不是合法 AES 密钥长度")
    try:
        # The final 16 bytes of payload are the tag. AESGCM verifies it.
        plain = AESGCM(key).decrypt(nonce, payload, None)
    except InvalidTag as exc:
        raise ValueError("解密认证失败：密码错误，或密文/认证标签已被修改") from exc
    try:
        result = json.loads(plain.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("解密成功，但内容不是有效的 UTF-8 JSON") from exc
    if not isinstance(result, dict):
        raise ValueError("解密内容不是节点对象")
    return result


def extract_ciphertext(node):
    properties = node.get("properties")
    if isinstance(properties, dict) and properties.get("hiddenJson"):
        return properties["hiddenJson"]
    if node.get("hiddenJson"):
        return node["hiddenJson"]
    inputs = node.get("inputs")
    if isinstance(inputs, dict) and isinstance(inputs.get("hiddenJson"), str):
        return inputs["hiddenJson"]
    widgets = node.get("widgets_values")
    if isinstance(widgets, list) and widgets and isinstance(widgets[0], str):
        return widgets[0]
    raise ValueError("节点中没有 hiddenJson 密文")


def decode_document(text, password="555200", node_id=None):
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        if node_id is not None:
            raise ValueError("--node-id 只适用于工作流 JSON")
        return decrypt_hidden_json(text, password)
    if isinstance(document, str):
        if node_id is not None:
            raise ValueError("--node-id 只适用于工作流 JSON")
        return decrypt_hidden_json(document, password)
    if not isinstance(document, dict):
        raise ValueError("输入应为密文文本、隐藏节点对象或工作流 JSON")

    if isinstance(document.get("nodes"), list):
        candidates = [(str(node.get("id")), node) for node in document["nodes"]
                      if isinstance(node, dict) and node.get("type") == "LamGroupNode"]
    elif any(isinstance(value, dict) and value.get("class_type") == "LamGroupNode"
             for value in document.values()):
        # Also accept the ComfyUI API prompt format.
        candidates = [(str(key), node) for key, node in document.items()
                      if isinstance(node, dict) and node.get("class_type") == "LamGroupNode"]
    else:
        if node_id is not None:
            raise ValueError("--node-id 只适用于工作流 JSON")
        return decrypt_hidden_json(extract_ciphertext(document), password)

    if node_id is not None:
        candidates = [(key, node) for key, node in candidates if key == str(node_id)]
    if not candidates:
        raise ValueError("没有找到指定的 LamGroupNode 隐藏节点")
    groups = []
    for key, node in candidates:
        try:
            decoded = decrypt_hidden_json(extract_ciphertext(node), password)
        except ValueError as exc:
            raise ValueError(f"节点 {key}：{exc}") from exc
        groups.append({"node_id": key, "title": node.get("title", ""), "decoded": decoded})
    # Explicit node selection produces only the original decrypted object.
    if node_id is not None:
        return groups[0]["decoded"]
    return {"format": "LamGroupNode decoded inspection data", "groups": groups}


def main():
    parser = argparse.ArgumentParser(description="解密 LamGroupNode，原样导出内部 JSON；不运行节点、不修改输入文件。")
    parser.add_argument("input", type=Path, help="工作流 JSON、节点 JSON 或包含 hiddenJson 密文的 TXT")
    parser.add_argument("-o", "--output", type=Path, help="输出文件，默认 <输入文件名>.decoded.json")
    parser.add_argument("--node-id", help="只解码指定 ID 的隐藏组，并输出其原始内部 JSON")
    parser.add_argument("--password", default="555200", help="加密口令，默认使用当前扩展内置口令")
    args = parser.parse_args()
    output = args.output or args.input.with_name(args.input.stem + ".decoded.json")
    try:
        if args.input.resolve() == output.resolve():
            raise ValueError("输出路径不能与输入文件相同")
        result = decode_document(args.input.read_text(encoding="utf-8-sig"), args.password, args.node_id)
        # Exclusive creation avoids accidentally overwriting an earlier inspection.
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except ImportError:
        print("缺少依赖，请运行：python -m pip install cryptography", file=sys.stderr)
        return 1
    except FileExistsError:
        print("输出文件已存在，请用 -o 指定其他文件名。", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"解码失败：{exc}", file=sys.stderr)
        return 1
    print(f"解码完成：{output.resolve()}")
    if args.node_id is None and "groups" in result and isinstance(result["groups"], list):
        print(f"已解码 {len(result['groups'])} 个隐藏组，查看各组的 decoded 字段。")
    print("仅导出内部数据；嵌套组的 hiddenJson 保持原样，可提取后再次解码。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
