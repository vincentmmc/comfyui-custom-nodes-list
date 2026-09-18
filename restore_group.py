"""Produce a flat restoration plan; never execute decrypted node code."""
from .decode_hidden_json import decrypt_hidden_json


def restore_group(text):
    nodes = []
    count = 0
    total_bytes = 0

    def slot(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or int(value) != value:
            raise ValueError("输出端口编号无效")
        return int(value)

    def expand(ciphertext, bindings=None, depth=0):
        nonlocal count, total_bytes
        if depth > 32 or not isinstance(ciphertext, str):
            raise ValueError("嵌套组数据无效或超过 32 层")
        total_bytes += len(ciphertext)
        if total_bytes > 16 * 1024 * 1024:
            raise ValueError("解码数据超过 16 MiB 上限")
        data = decrypt_hidden_json(ciphertext)
        count += len(data)
        if count > 5000:
            raise ValueError("节点总数超过 5000 个上限")
        cache, visiting = {}, set()

        def resolve(value):
            # Same link recognition as the original LamGroupNode implementation.
            linked = (isinstance(value, list) and len(value) == 2 and
                      isinstance(value[0], str) and isinstance(value[1], (str, int, float)))
            if not linked:
                return {"kind": "value", "value": value}
            source, index = value
            if source == "hidden":
                if not isinstance(index, str):
                    raise ValueError("隐藏组输入名称无效")
                if bindings is None:
                    return {"kind": "external", "name": index}
                return bindings.get(index, {"kind": "missing"})
            index = slot(index)
            result = build(source)
            if isinstance(result, str):
                return {"kind": "link", "node": result, "slot": index}
            if index not in result:
                raise ValueError("嵌套组缺少被引用的输出端口")
            return result[index]

        def build(key):
            if key in cache:
                return cache[key]
            if key in visiting:
                raise ValueError("内部节点存在循环连接")
            if key not in data:
                raise ValueError("引用了不存在的内部节点")
            visiting.add(key)
            record = data[key]
            if not isinstance(record, dict) or not isinstance(record.get("inputs"), dict) or not isinstance(record.get("class_type"), str):
                raise ValueError("内部节点格式无效")
            inputs = {name: resolve(value) for name, value in record["inputs"].items()}
            if record["class_type"] == "LamGroupNode":
                hidden = inputs.get("hiddenJson", {})
                if hidden.get("kind") != "value":
                    raise ValueError("嵌套组 hiddenJson 必须为固定字符串")
                result = expand(hidden.get("value"), inputs, depth + 1)
            else:
                result = str(len(nodes) + 1)
                item = {"id": result, "class_type": record["class_type"], "inputs": inputs}
                if isinstance(record.get("_meta"), dict) and isinstance(record["_meta"].get("title"), str):
                    item["title"] = record["_meta"]["title"]
                nodes.append(item)
            visiting.remove(key)
            cache[key] = result
            return result

        outputs = {}
        for key, record in data.items():
            if not isinstance(record, dict) or not isinstance(record.get("outputs"), list):
                raise ValueError("内部节点输出映射无效")
            for pair in record["outputs"]:
                if not isinstance(pair, list) or len(pair) != 2:
                    raise ValueError("内部节点输出映射无效")
                outer, inner = map(slot, pair)
                target = resolve([key, inner])
                if outer in outputs and outputs[outer] != target:
                    raise ValueError("输出映射冲突")
                outputs[outer] = target
        if not outputs:
            raise ValueError("隐藏组没有可还原的输出")
        return outputs

    outputs = expand(text)
    # Retain only ancestors of exported outputs, matching the original executor.
    by_id = {node["id"]: node for node in nodes}
    reachable, pending = set(), list(outputs.values())
    while pending:
        value = pending.pop()
        if value["kind"] == "link" and value["node"] not in reachable:
            reachable.add(value["node"])
            pending.extend(by_id[value["node"]]["inputs"].values())
    return {"nodes": [node for node in nodes if node["id"] in reachable], "outputs": outputs}


def register_routes():
    from aiohttp import web
    from server import PromptServer

    @PromptServer.instance.routes.post("/custom_nodes_list/restore_lam_group")
    async def restore(request):
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("请求必须为 JSON 对象")
            return web.json_response({"success": True, **restore_group(body.get("hiddenJson"))})
        except ImportError:
            return web.json_response({"success": False, "error": "请在 ComfyUI 的 Python 环境安装 cryptography（requirements.txt）。"}, status=503)
        except ValueError as exc:
            return web.json_response({"success": False, "error": str(exc)}, status=400)
        except (TypeError, KeyError, RecursionError):
            return web.json_response({"success": False, "error": "节点数据格式无效或依赖嵌套过深。"}, status=400)
