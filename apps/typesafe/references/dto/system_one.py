"""Validated, bounded subset of TypeSafe's System One response contract."""
from dataclasses import dataclass
import math


class TypeSafeError(RuntimeError):
    """Sanitized error safe to return to an agent."""


def number(value, low=0, high=1):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise TypeSafeError('TypeSafe returned an invalid numeric answer.')
    return value


def distribution(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise TypeSafeError('TypeSafe returned an invalid probability distribution.')
    if abs(sum(number(v) for v in value.values()) - 1) > .02:
        raise TypeSafeError('TypeSafe probabilities do not sum to one.')
    return value


@dataclass
class DtoTypeSafeResponse:
    model: str | None = None
    answers: dict | None = None
    usage: dict | None = None

    @classmethod
    def parse(cls, raw, questions):
        try:
            model, answers, usage = raw['model'], raw['answers'], raw['usage']
            if not isinstance(model, str) or not 1 <= len(model) <= 200:
                raise TypeSafeError('TypeSafe returned an invalid model.')
            if not isinstance(answers, dict) or set(answers) != set(questions):
                raise TypeSafeError('TypeSafe returned missing or unexpected answers.')
            clean = {}
            for key, question in questions.items():
                answer = answers[key]
                kind = question['type']
                if answer['type'] != kind:
                    raise TypeSafeError('TypeSafe returned an incorrect answer type.')
                if kind == 'noul':
                    clean[key] = {'type': kind, 'noul': number(answer['noul'])}
                else:
                    criteria = question['criteria']
                    keys = criteria if kind == 'choice' else [str(i) for i in range(len(criteria))]
                    probs = distribution(answer['probabilities'], keys)
                    row = {'type': kind, 'probabilities': probs, 'confidence': number(answer['confidence'])}
                    if kind == 'choice':
                        choice = answer['choice']
                        if choice not in criteria or probs[choice] < max(probs.values()):
                            raise TypeSafeError('TypeSafe returned an invalid choice.')
                        row['choice'] = choice
                    else:
                        row['score'] = number(answer['score'], high=len(criteria) - 1)
                        expected = sum(int(k) * v for k, v in probs.items())
                        if abs(row['score'] - expected) > .03:
                            raise TypeSafeError('TypeSafe returned an inconsistent score.')
                    clean[key] = row
            clean_usage = {}
            for key in ('input_tokens', 'output_tokens'):
                if type(usage[key]) is not int or usage[key] < 0:
                    raise TypeSafeError('TypeSafe returned invalid token usage.')
                clean_usage[key] = usage[key]
            return cls(model, clean, clean_usage)
        except (KeyError, TypeError, AttributeError):
            raise TypeSafeError('TypeSafe returned an invalid response schema.') from None
