"""OpenAI Code Interpreter service.

Uses the code_interpreter built-in tool in the Responses API to run Python
code in a sandboxed container managed by OpenAI. The model generates and
executes Python code, returning stdout logs and any produced files.

Inherits from ApiServiceOpenAiResponses so all Responses API methods are
available alongside the code-specific helpers.

See: https://platform.openai.com/docs/guides/code-execution
"""
from typing import Optional, List

from apps.open_ai.references.web.api.responses import ApiServiceOpenAiResponses
from apps.open_ai.references.dto.response import (
    DtoOpenAiResponse,
    DtoOpenAiCodeInterpreterCall,
    DtoOpenAiCodeOutput,
)

DEFAULT_MODEL = "gpt-4.1"

_CODE_INTERPRETER_TOOL = {
    "type": "code_interpreter",
    "container": {"type": "auto"},
}


class ApiServiceOpenAiCodeInterpreter(ApiServiceOpenAiResponses):
    """Responses API with code_interpreter built-in tool enabled."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    def execute_code(
        self,
        prompt: str,
        model: Optional[str] = None,
        instructions: Optional[str] = None,
        previous_response_id: Optional[str] = None,
    ) -> DtoOpenAiResponse:
        """Send a prompt to the code interpreter.

        The model generates Python code, executes it in a sandboxed container,
        and returns the output. Use previous_response_id to continue a session
        and preserve variables defined in prior turns.
        """
        return self.create_response(
            input=prompt,
            model=model or self.default_model,
            instructions=instructions,
            tools=[_CODE_INTERPRETER_TOOL],
            previous_response_id=previous_response_id,
            store=True,
        )

    def execute_code_with_files(
        self,
        prompt: str,
        file_ids: List[str],
        model: Optional[str] = None,
        instructions: Optional[str] = None,
    ) -> DtoOpenAiResponse:
        """Send a prompt with uploaded files available to the interpreter.

        file_ids must be IDs of files uploaded to OpenAI with purpose='assistants'.
        The code interpreter will be able to read those files during execution.
        """
        tool = {
            "type": "code_interpreter",
            "container": {"type": "auto", "file_ids": file_ids},
        }
        return self.create_response(
            input=prompt,
            model=model or self.default_model,
            instructions=instructions,
            tools=[tool],
            store=True,
        )

    def parse_code_calls(self, dto: DtoOpenAiResponse) -> List[DtoOpenAiCodeInterpreterCall]:
        """Extract code_interpreter_call items from a response DTO.

        Returns a list of structured call objects, each containing the
        generated code and its stdout/file outputs.
        """
        calls: List[DtoOpenAiCodeInterpreterCall] = []
        for item in dto.output or []:
            if item.type != "code_interpreter_call":
                continue
            parsed_outputs: List[DtoOpenAiCodeOutput] = []
            for out in item.outputs or []:
                parsed_outputs.append(DtoOpenAiCodeOutput(
                    type=getattr(out, "type", None),
                    logs=getattr(out, "logs", None),
                    files=getattr(out, "files", None),
                ))
            calls.append(DtoOpenAiCodeInterpreterCall(
                id=item.id,
                type=item.type,
                status=item.status,
                code=item.code,
                outputs=parsed_outputs,
            ))
        return calls
