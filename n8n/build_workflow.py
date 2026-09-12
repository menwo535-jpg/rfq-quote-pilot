"""Build an importable n8n workflow. No credentials or customer data are bundled."""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from make_request import make_request


def workflow(payload, *, url="http://127.0.0.1:8765/quote", credential_id=None):
    def node(name, kind, version, position, parameters):
        return {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "rfq-pilot/" + name)),
            "name": name, "type": "n8n-nodes-base." + kind,
            "typeVersion": version, "position": position, "parameters": parameters,
        }

    request = node("Prepare draft", "httpRequest", 4.2, [460, 300], {
        "method": "POST", "url": url,
        "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
        "sendBody": True, "specifyBody": "json", "jsonBody": "={{ $json }}",
        "options": {"timeout": 30000, "response": {"response": {"responseFormat": "json"}}},
    })
    # Names alone do not grant access: the importer must select/create this credential.
    credential = {"name": "RFQ local API"}
    if credential_id:
        credential["id"] = credential_id
    request["credentials"] = {"httpHeaderAuth": credential}
    request["retryOnFail"] = False
    request["onError"] = "stopWorkflow"
    condition = "={{ $json.quote?.status === 'DRAFT_FOR_APPROVAL' && $json.quote?.review_count === 0 && $json.quote?.complete_totals_by_currency != null && Object.keys($json.quote.complete_totals_by_currency).length > 0 }}"
    nodes = [
        node("Manual start", "manualTrigger", 1, [0, 300], {}),
        node("Synthetic RFQ input", "set", 3.4, [220, 300], {
            "mode": "raw", "jsonOutput": json.dumps(payload, ensure_ascii=False), "options": {},
        }),
        request,
        node("All lines matched", "if", 2.2, [700, 300], {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                "conditions": [{"id": "all-lines-matched", "leftValue": condition, "rightValue": "",
                                "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
                "combinator": "and",
            }, "options": {},
        }),
    ]
    for name, y in (("Draft awaiting human approval", 180), ("Unresolved lines - review required", 420)):
        nodes.append(node(name, "convertToFile", 1.1, [960, y], {
            "operation": "toBinary", "sourceProperty": "artifacts.xlsx_base64",
            "binaryPropertyName": "workbook",
            "options": {"fileName": "quote-draft.xlsx", "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        }))

    def edge(name):
        return {"node": name, "type": "main", "index": 0}

    return {
        "name": "RFQ PDF to Excel - local review routing", "nodes": nodes,
        "connections": {
            "Manual start": {"main": [[edge("Synthetic RFQ input")]]},
            "Synthetic RFQ input": {"main": [[edge("Prepare draft")]]},
            "Prepare draft": {"main": [[edge("All lines matched")]]},
            "All lines matched": {"main": [[edge("Draft awaiting human approval")], [edge("Unresolved lines - review required")]]},
        },
        "settings": {"executionOrder": "v1"}, "active": False,
        "pinData": {}, "tags": [],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("rfq-review-workflow.json"))
    args = parser.parse_args()
    payload = json.loads(make_request(ROOT / "samples/rfq.pdf", ROOT / "samples/catalogue.csv", include_xlsx=True))
    args.out.write_text(json.dumps(workflow(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Created synthetic workflow; select a Header Auth credential before running.")


if __name__ == "__main__":
    main()
