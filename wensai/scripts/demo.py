"""从普通客户端走完整条链路。仅使用 Python 标准库和随包样例。"""

import argparse
import hashlib
import json
from pathlib import Path
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "campus-plan.docx"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def demonstrate(base: str):
    base = base.rstrip("/")
    client = build_opener(ProxyHandler({}))

    def request(method, path, data=None, content_type=None):
        headers = {"Content-Type": content_type} if content_type else {}
        req = Request(base + path, data=data, method=method, headers=headers)
        with client.open(req, timeout=15) as response:
            if response.headers.get_content_type() == "application/json":
                return json.load(response)
            return response.read()

    def post_json(path, obj):
        return request("POST", "/api/v1" + path, json.dumps(obj).encode(), "application/json")

    print("服务状态", request("GET", "/health")["status"])
    project = post_json("/projects", {"name": "校园节能方案 · 接口演示"})
    print("项目 ID", project["id"])

    sample = SAMPLE.read_bytes()
    boundary = uuid4().hex
    part = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{SAMPLE.name}"\r\n'
            f'Content-Type: {DOCX}\r\n\r\n').encode("ascii")
    material = request("POST", f'/api/v1/projects/{project["id"]}/materials',
                       part + sample + f"\r\n--{boundary}--\r\n".encode("ascii"),
                       "multipart/form-data; boundary=" + boundary)
    print("材料已入库，版本", material["version_no"], material["version_id"])
    task = post_json("/tasks", {"version_id": material["version_id"]})
    path = "/api/v1/tasks/" + task["id"]
    print("任务 ID", task["id"])
    deadline = monotonic() + 90
    after, status = 0, None
    while monotonic() < deadline:
        page = request("GET", f"{path}/events?after={after}")
        for event in page["items"]:
            status = event["status"]
            print(f'  {event["seq"]:>2}  {status:<10} {event["message"]}')
        after = page["next_after"]
        if status == "completed":
            break
        if status in {"failed", "cancelled"}:
            raise RuntimeError("任务结束，详情为 " + str(request("GET", path)))
        sleep(0.15)
    else:
        raise RuntimeError("等待评审超时，可凭任务 ID 继续查询。")

    report = request("GET", path + "/result")
    print("总分", report["overall_score"], "｜", report["summary"])
    for finding in report["findings"]:
        print("问题", finding["description"])
        for suggestion in finding["suggestions"]:
            print("建议", suggestion["content"])
    exported = request("GET", f'/api/v1/versions/{material["version_id"]}/export')
    digest = hashlib.sha256(exported).hexdigest()
    if digest != material["sha256"] or exported != sample:
        raise RuntimeError("导出数据与原始样例不一致。")
    print("版本导出校验通过，SHA-256", digest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="问赛本地后端联调（每次新建一个演示项目）")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    try:
        demonstrate(parser.parse_args().base_url)
    except HTTPError as error:
        raise SystemExit(f"HTTP {error.code} {error.read().decode(errors='replace')}") from None
    except URLError as error:
        raise SystemExit(f"连接失败，请先启动本地服务。{error.reason}") from None
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
