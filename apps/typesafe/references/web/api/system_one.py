"""Models and versioned recommendation-only decisions."""
from dataclasses import asdict
from datetime import datetime, timezone
import time
import uuid
import sqlite3

from apps.typesafe.receipts import ReceiptStore
from apps.typesafe.templates import build, interpret, POLICY
from apps.typesafe.references.dto.system_one import DtoTypeSafeResponse, TypeSafeError
from apps.typesafe.references.web.base_api_service import BaseApiServiceTypeSafe


class ApiServiceTypeSafeDecisions(BaseApiServiceTypeSafe):
    def list_models(self):
        raw = self._send_json('GET', '/v1/models')
        models = raw.get('models') if isinstance(raw, dict) else None
        if not isinstance(models, list) or len(models) > 200:
            raise TypeSafeError('TypeSafe returned an invalid model list.')
        result = []
        for row in models:
            if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not 1 <= len(row[k]) <= 2000 for k in ('name', 'description', 'release_date')):
                raise TypeSafeError('TypeSafe returned invalid model metadata.')
            result.append({k: row[k] for k in ('name', 'description', 'release_date')})
        return result

    def analyze_decision(self, template, state):
        questions, mapping = build(template, state)
        started = time.monotonic()
        receipt = {'receipt_id': uuid.uuid4().hex, 'created_at': datetime.now(timezone.utc).isoformat(),
                   'template': template, 'requested_model': self.model, 'policy': dict(POLICY)}
        try:
            raw = self._send_json('POST', '/v1/systemone', {'model': self.model, 'state': state, 'questions': questions})
            response = DtoTypeSafeResponse.parse(raw, questions)
            result = {**asdict(response), **interpret(response.answers, mapping)}
            # Persist choice probabilities by ID, never caller-supplied names.
            answers = {k: dict(v) for k, v in response.answers.items()}
            answers['agent'] = {**answers['agent'], 'choice': mapping[answers['agent']['choice']],
                                'probabilities': {mapping[k]: v for k, v in answers['agent']['probabilities'].items()}}
            receipt.update({**result, 'answers': answers})
        except TypeSafeError as exc:
            result = {'status': 'error', 'error': str(exc), 'execution_authorized': False}
            receipt.update(result)
        receipt['latency_ms'] = round((time.monotonic() - started) * 1000)
        try:
            ReceiptStore().save(receipt)
        except (OSError, sqlite3.Error):
            raise TypeSafeError('Decision receipt could not be persisted; do not execute or repeat inference blindly.') from None
        return {**result, 'receipt_id': receipt['receipt_id'], 'template': template,
                'policy': dict(POLICY), 'latency_ms': receipt['latency_ms']}
