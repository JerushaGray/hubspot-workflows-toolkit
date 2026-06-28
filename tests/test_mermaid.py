import json
import os

from hsflow.mermaid import to_mermaid

HERE = os.path.dirname(__file__)
SAMPLE = os.path.join(HERE, "..", "examples", "sample_flow.json")


def load_sample():
    with open(SAMPLE, encoding="utf-8") as fh:
        return json.load(fh)


def render():
    return to_mermaid(load_sample())


def test_is_a_flowchart():
    assert render().startswith("flowchart TD")


def test_dangling_node_and_class():
    out = render()
    assert 'n9999["9999 (missing)"]' in out
    assert "class n9999 dangling;" in out
    assert "n10 --> n9999" in out


def test_goto_edge_is_dashed():
    assert "n6 -. GOTO .-> n8" in render()


def test_orphan_and_nodefault_and_start_classes():
    out = render()
    assert "class n11 orphan;" in out
    assert "class n8 nodefault;" in out
    assert "class n1 start;" in out


def test_node_labels_carry_detail():
    out = render()
    assert 'n2["2: DELAY 1 day"]' in out      # delay humanized
    assert "3: SEND_EMAIL #100001" in out      # email content id
    assert "5: BRANCH" in out                  # branch relabelled


def test_every_action_has_a_node():
    flow = load_sample()
    out = to_mermaid(flow)
    for action in flow["actions"]:
        assert f'n{action["actionId"]}[' in out


def test_label_special_chars_are_sanitized():
    # Characters that would break a Mermaid ["..."] label are escaped:
    # " -> ', [ -> (, ] -> ). The raw form must not leak into the output.
    flow = {
        "id": "x",
        "startActionId": "1",
        "actions": [
            {"actionId": "1", "actionTypeId": "0-5", "fields": {"property_name": 'a"b[c]'}},
        ],
    }
    out = to_mermaid(flow)
    assert "a'b(c)" in out
    assert 'a"b[c]' not in out
