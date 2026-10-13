"""Run with `python -m unittest tests.test_minimal_runtime` without test or Azure extras."""

import json
import socket
import threading
import time
import unittest
from urllib.request import Request, urlopen

import uvicorn

from template_azure_python.api import create_app
from template_azure_python.settings import TaskRepositoryBackend


class MinimalRuntimeTest(unittest.TestCase):
    def test_http_crud_without_optional_dependencies(self) -> None:
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", 0))
        base_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(
            uvicorn.Config(
                create_app(repository_backend=TaskRepositoryBackend.IN_MEMORY),
                log_level="error",
                lifespan="on",
            )
        )
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)

        def stop() -> None:
            server.should_exit = True
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive(), "Server did not shut down")

        worker.start()
        self.addCleanup(stop)
        deadline = time.monotonic() + 5
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(server.started, "Server did not start")

        def request(method: str, path: str, body: dict[str, str] | None = None) -> tuple[int, bytes]:
            data = json.dumps(body).encode() if body is not None else None
            with urlopen(
                Request(base_url + path, data=data, headers={"Content-Type": "application/json"}, method=method),
                timeout=5,
            ) as response:
                return response.status, response.read()

        self.assertEqual(request("GET", "/tasks"), (200, b"[]"))
        status, body = request("POST", "/tasks", {"title": " Minimal "})
        self.assertEqual(status, 201)
        created = json.loads(body)
        self.assertEqual(created["title"], "Minimal")
        path = f"/tasks/{created['id']}"
        self.assertEqual(json.loads(request("GET", path)[1]), created)
        status, body = request("PUT", path, {"title": "Done", "status": "done"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "done")
        self.assertEqual(request("DELETE", path), (204, b""))
        self.assertEqual(request("GET", "/tasks"), (200, b"[]"))
        self.assertEqual(request("GET", "/docs")[0], 200)
        schema = json.loads(request("GET", "/openapi.json")[1])
        self.assertEqual(set(schema["paths"]), {"/tasks", "/tasks/{task_id}"})


if __name__ == "__main__":
    unittest.main()
