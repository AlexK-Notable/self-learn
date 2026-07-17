from pathlib import Path
from starlette.testclient import TestClient
from self_learn_ui.app import create_app
from self_learn_ui.env import load_env
from self_learn_ui.middleware import CSP_HEADER_VALUE, TOKEN_COOKIE_NAME
from self_learn_ui.runner import FakeRunner
from support import make_env

TOKEN="test-token"
CSP="content-security-policy"

def build(tmp):
    sb=make_env(tmp)
    env=load_env(sb.env)
    app=create_app(env=env, token=TOKEN, runner=FakeRunner(), start_watcher=False)
    c=TestClient(app, base_url="http://127.0.0.1:7357")
    return sb,c

def test_probe(tmp_path):
    sb,c=build(tmp_path)
    # 403 (no cookie)
    r=c.get("/"); print("403 path CSP:", r.headers.get(CSP)==CSP_HEADER_VALUE, r.status_code)
    c.cookies.set(TOKEN_COOKIE_NAME, TOKEN)
    # 200
    r=c.get("/"); print("200 CSP:", r.headers.get(CSP)==CSP_HEADER_VALUE, r.status_code)
    # 404
    r=c.get("/nonexistent-xyz"); print("404 CSP:", r.headers.get(CSP)==CSP_HEADER_VALUE, r.status_code)
    # static
    r=c.get("/static/style.css"); print("static CSP:", r.headers.get(CSP)==CSP_HEADER_VALUE, r.status_code)
    # redirect (token param) - don't follow
    r=c.get("/?token="+TOKEN, follow_redirects=False)
    print("303 redirect CSP:", r.headers.get(CSP)==CSP_HEADER_VALUE, r.status_code, "Location:", r.headers.get("location"))
    # Host header casing bypass attempt
    r=c.get("/", headers={"host":"127.0.0.1:7357".upper()}); print("Host UPPER (127.0.0.1:7357 has no letters):", r.status_code)
    r=c.get("/", headers={"host":"LOCALHOST:7357"}); print("Host LOCALHOST upper -> lowered -> allowed:", r.status_code)
    r=c.get("/", headers={"host":"evil.com:7357"}); print("Host evil rejected:", r.status_code)
    r=c.get("/", headers={"host":"[::1]:7357"}); print("Host ipv6 ::1:", r.status_code)
    # CSRF: POST without HX-Request
    r=c.post("/mine/run"); print("POST no HX-Request rejected:", r.status_code)
    r=c.post("/mine/run", headers={"HX-Request":"true"}); print("POST with HX-Request:", r.status_code)
    # SSE CSP + streaming
    with c.stream("GET","/events") as s:
        print("SSE CSP:", s.headers.get(CSP)==CSP_HEADER_VALUE, s.status_code)
