import unittest

from apps.open_ai.references.assistants.base import BaseAssistant
from apps.open_ai.references.models.assistants.message import MessageCreate
from apps.open_ai.references.models.assistants.run import RunCreate

from core.utilities.data.qlist import QList

import pytest


@pytest.mark.skip("deprecated")
class TestServiceAssistant(unittest.TestCase):

    def test_simple_flow(self):
        assistant = BaseAssistant()
        assistant.load()

        messages = [
            MessageCreate(role='user', content='100'),
            MessageCreate(role='user', content='101'),
            MessageCreate(role='user', content='132')
            ]

        assistant.add_messages_to_thread(messages)

        trigger = RunCreate(assistant_id=assistant.properties.id,
                            instructions='Add all numbers. Give me numeric value only. No explanations.',
                            temperature=0.0)
        assistant.run_thread(run=trigger)
        assistant.wait_for_runs_to_complete()

        replies = assistant.get_replies()
        answer = QList(replies).first()
        self.assertEqual(answer.content[0].text.value, '333')


