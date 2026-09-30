import subprocess
import sys

import analytics.favorite_forward as favorite_forward


def test_help_is_network_free():
    result = subprocess.run([sys.executable, "-m", "analytics.favorite_forward", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "--output" in result.stdout


def test_invalid_options_have_no_side_effect(tmp_path):
    output = tmp_path / "out"
    result = subprocess.run([sys.executable, "-m", "analytics.favorite_forward", "--output", str(output), "--poll-seconds", "1"], capture_output=True, text=True)
    assert result.returncode != 0
    assert not output.exists()


def test_main_fake_http_writes_completed_manifest_and_request_log(tmp_path, monkeypatch):
    urls = []
    def fake_request(method, url, **kwargs):
        urls.append(url)
        return {"data": []}, 200, 1_000
    monkeypatch.setattr(favorite_forward, "_http", fake_request)
    output = tmp_path / "run"
    assert favorite_forward.main(["--output", str(output), "--hours", "1", "--max-markets", "1"]) == 0
    import json
    windows = json.loads((output / "windows.json").read_text())
    assert windows["completed"] is True
    assert urls and len(urls) == 5 and windows["requests"] and windows["request_count"] == 5
    assert all("order=startDate" in url and "ascending=false" in url for url in urls)
    assert not windows["orders_created"]
    assert all("ascending=false" in url for url in urls)
