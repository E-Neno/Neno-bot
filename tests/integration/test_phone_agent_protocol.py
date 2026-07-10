from app.phone_agent_schemas import (
    AgentActionRequest,
    AgentCapabilities,
    AgentHello,
    AgentObservation,
)


def test_agent_hello_uses_v0_protocol():
    hello = AgentHello(device_id="xiaomi-14-local", client="android-apk")

    assert hello.type == "hello"
    assert hello.protocol == "phone-agent-v0"


def test_observation_keeps_capability_flags_explicit():
    obs = AgentObservation(
        device_id="xiaomi-14-local",
        state="idle",
        foreground_app="浏览器",
        screen={"width": 1080, "height": 2400},
        capabilities=AgentCapabilities(
            accessibility=True,
            screenshot=True,
            notification=False,
            root_daemon=False,
            kernel_touch=False,
        ),
    )

    assert obs.capabilities.accessibility is True
    assert obs.capabilities.kernel_touch is False


def test_action_request_requires_known_risk_level():
    action = AgentActionRequest(
        action_id="act_001",
        tool="tap",
        risk="low",
        args={"x": 5400, "y": 8200, "coordinate": "normalized_10000"},
        reason="点击搜索框",
    )

    assert action.type == "action_request"
    assert action.risk == "low"


def test_agent_ws_sends_controller_hello(client):
    with client.websocket_connect("/agent/ws?device_id=xiaomi-14-local") as ws:
        payload = ws.receive_json()

    assert payload == {
        "type": "hello",
        "device_id": "controller",
        "client": "pc-console",
        "protocol": "phone-agent-v0",
    }


def test_mobile_agent_ws_uses_mobile_namespace(client):
    with client.websocket_connect("/mobile/agent/ws?device_id=xiaomi-14-local") as ws:
        payload = ws.receive_json()

    assert payload["type"] == "hello"
    assert payload["protocol"] == "phone-agent-v0"


def test_agent_ws_acknowledges_observation(client):
    with client.websocket_connect("/mobile/agent/ws?device_id=xiaomi-14-local") as ws:
        ws.receive_json()
        ws.send_json(
            {
                "type": "observation",
                "device_id": "xiaomi-14-local",
                "state": "idle",
            }
        )
        payload = ws.receive_json()

    assert payload == {
        "type": "observation_ack",
        "device_id": "xiaomi-14-local",
    }
