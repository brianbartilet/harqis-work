import logging
from typing import Optional, List

from mcp.server.fastmcp import FastMCP
from apps.open_ai.config import CONFIG
from apps.open_ai.references.web.api.responses import ApiServiceOpenAiResponses, DEFAULT_MODEL
from apps.open_ai.references.web.api.code_interpreter import ApiServiceOpenAiCodeInterpreter

logger = logging.getLogger("harqis-mcp.open_ai")


def register_open_ai_tools(mcp: FastMCP):

    @mcp.tool()
    def openai_generate(
        prompt: str,
        model: str = DEFAULT_MODEL,
        instructions: Optional[str] = None,
        previous_response_id: Optional[str] = None,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
    ) -> dict:
        """Generate a text response using the OpenAI Responses API.

        The Responses API is the current recommended interface for text generation.
        Pass previous_response_id to continue a prior multi-turn conversation
        without re-sending history.

        Args:
            prompt:               The user input text.
            model:                Model ID (default 'gpt-4.1').
            instructions:         System-level instructions for the model.
            previous_response_id: ID of a prior response to chain from.
            temperature:          Sampling temperature 0.0–2.0.
            max_output_tokens:    Maximum number of output tokens.
        """
        logger.info("Tool called: openai_generate model=%s prompt_len=%d", model, len(prompt))
        svc = ApiServiceOpenAiResponses(CONFIG)
        result = svc.create_response(
            input=prompt,
            model=model,
            instructions=instructions,
            previous_response_id=previous_response_id,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        out = {
            "id": result.id,
            "model": result.model,
            "status": result.status,
            "output_text": result.output_text,
            "previous_response_id": result.previous_response_id,
            "usage": result.usage.__dict__ if result.usage else {},
        }
        logger.info("openai_generate response_id=%s status=%s", result.id, result.status)
        return out

    @mcp.tool()
    def openai_get_response(response_id: str) -> dict:
        """Retrieve a previously stored OpenAI response by ID.

        Args:
            response_id: The response ID returned from a prior openai_generate call.
        """
        logger.info("Tool called: openai_get_response id=%s", response_id)
        svc = ApiServiceOpenAiResponses(CONFIG)
        result = svc.get_response(response_id)
        return {
            "id": result.id,
            "model": result.model,
            "status": result.status,
            "output_text": result.output_text,
            "usage": result.usage.__dict__ if result.usage else {},
        }

    @mcp.tool()
    def openai_delete_response(response_id: str) -> dict:
        """Delete a stored OpenAI response.

        Args:
            response_id: The ID of the response to delete.
        """
        logger.info("Tool called: openai_delete_response id=%s", response_id)
        svc = ApiServiceOpenAiResponses(CONFIG)
        return svc.delete_response(response_id)

    @mcp.tool()
    def openai_execute_code(
        prompt: str,
        model: str = DEFAULT_MODEL,
        instructions: Optional[str] = None,
        previous_response_id: Optional[str] = None,
    ) -> dict:
        """Run Python code via the OpenAI Code Interpreter built-in tool.

        Sends a natural language prompt; the model generates and executes Python
        in a sandboxed container. Returns the text output, generated code, and
        stdout logs. Use previous_response_id to continue a session and preserve
        variables from prior turns.

        Args:
            prompt:               Describe what the code should compute or do.
            model:                Model ID (default 'gpt-4.1').
            instructions:         System instructions for the code interpreter session.
            previous_response_id: Continue a prior code interpreter session.
        """
        logger.info("Tool called: openai_execute_code model=%s prompt_len=%d", model, len(prompt))
        svc = ApiServiceOpenAiCodeInterpreter(CONFIG)
        result = svc.execute_code(
            prompt=prompt,
            model=model,
            instructions=instructions,
            previous_response_id=previous_response_id,
        )
        calls = svc.parse_code_calls(result)
        code_outputs = [
            {
                "code": c.code,
                "status": c.status,
                "outputs": [{"type": o.type, "logs": o.logs} for o in (c.outputs or [])],
            }
            for c in calls
        ]
        out = {
            "id": result.id,
            "status": result.status,
            "output_text": result.output_text,
            "code_interpreter_calls": code_outputs,
            "usage": result.usage.__dict__ if result.usage else {},
        }
        logger.info("openai_execute_code response_id=%s calls=%d", result.id, len(code_outputs))
        return out

    @mcp.tool()
    def openai_execute_code_with_files(
        prompt: str,
        file_ids: List[str],
        model: str = DEFAULT_MODEL,
        instructions: Optional[str] = None,
    ) -> dict:
        """Run Python code with uploaded files available to the Code Interpreter.

        The code interpreter can read and process files previously uploaded
        to OpenAI with purpose='assistants'.

        Args:
            prompt:       Describe what code to run against the provided files.
            file_ids:     List of OpenAI file IDs (uploaded with purpose='assistants').
            model:        Model ID (default 'gpt-4.1').
            instructions: System instructions for the session.
        """
        logger.info(
            "Tool called: openai_execute_code_with_files model=%s files=%d",
            model, len(file_ids),
        )
        svc = ApiServiceOpenAiCodeInterpreter(CONFIG)
        result = svc.execute_code_with_files(
            prompt=prompt,
            file_ids=file_ids,
            model=model,
            instructions=instructions,
        )
        calls = svc.parse_code_calls(result)
        code_outputs = [
            {
                "code": c.code,
                "status": c.status,
                "outputs": [{"type": o.type, "logs": o.logs} for o in (c.outputs or [])],
            }
            for c in calls
        ]
        out = {
            "id": result.id,
            "status": result.status,
            "output_text": result.output_text,
            "code_interpreter_calls": code_outputs,
            "usage": result.usage.__dict__ if result.usage else {},
        }
        logger.info(
            "openai_execute_code_with_files response_id=%s files=%s calls=%d",
            result.id, file_ids, len(code_outputs),
        )
        return out
