"""AgentCore — main LLM loop for Finance Agent.

Handles Groq API calls, tool call dispatch, and multi-turn tool execution.
Supports multiple tool calls per turn with a max limit to prevent infinite loops.
"""

import os
import json
from tools import registry
from dotenv import load_dotenv
from groq import Groq, BadRequestError
from agent.classifier import classify_intent
from config import MODEL, MAX_TOOL_CALLS, DEBUG, MAX_HISTORY_MESSAGES

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def run(user_message: str, session) -> str:
    """Process a user message through the LLM loop.

    Sends message to Groq, handles tool calls, returns final response.

    Args:
        user_message: Raw message from user
        session:      Current Session instance

    Returns:
        Final natural language response string from LLM
    """

    # Trim tool result from history
    session.trim_old_tool_results()

    if session.message_count > MAX_HISTORY_MESSAGES:
        session.clear_history()

    session.add_message("user", user_message)

    # ── Phase B — classify intent, filter tools ────────────────────────────────
    intent = classify_intent(user_message)
    tools  = registry.get_tools_for_intent(intent)
    if DEBUG: print(f"[CL] intent: {intent} | tools: {len(tools)}/15")

    # fresh delete/update flow — clear stale step storage
    if intent in ("delete", "update"):
        session.state.reset_steps()

    tool_call_count = 0
    errors = []

    while tool_call_count < MAX_TOOL_CALLS:

        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=session.get_history(),
                tools=tools,
                tool_choice="none" if tool_call_count > 0 else "auto",
                parallel_tool_calls=False
            )
        except BadRequestError as e:
            error_str = str(e)
            if "tool_use_failed" in error_str:
                try:
                    import re
                    match = re.search(r"'failed_generation': '(\{.+?\})'", error_str)
                    if match:
                        failed = json.loads(match.group(1))
                        tool_name = failed["name"]
                        args = failed["arguments"]

                        # normalize type_ → type
                        if "type_" in args:
                            args["type"] = args.pop("type_")

                        result = registry.execute(tool_name, args, session)

                        fake_id = f"recovered_{tool_call_count}"
                        session.history.append({
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [{
                                "id": fake_id,
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(args)
                                }
                            }]
                        })
                        session.add_tool_result(fake_id, tool_name, result)
                        tool_call_count += 1
                        continue

                except Exception:
                    import traceback
                    traceback.print_exc()

                return "I had trouble with that — could you try rephrasing?"
            return f"Request failed: {error_str}"

        message = response.choices[0].message

        # no tool call — LLM gave final response
        if not message.tool_calls:
            final_response = message.content or "I couldn't generate a response."
            session.add_message("assistant", final_response)

            # auto-clear after response — never during active delete/update flow
            if session.message_count > MAX_HISTORY_MESSAGES and session.state.mode == "idle":
                session.clear_history()
                session.add_system_prompt()

            return final_response

        # append assistant message with tool calls to history
        session.add_assistant_message(message)

        # handle all tool calls in this turn
        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            tool_call_count += 1

            try:
                args = json.loads(tool_call.function.arguments)
                result = registry.execute(tool_name, args, session)
            except Exception as e:
                result = f"Tool {tool_name} failed: {str(e)}"
                errors.append(f"{tool_name}: {str(e)}")

            session.add_tool_result(tool_call.id, tool_call.function.name, result)

        # max tool calls reached — force final response
        if tool_call_count >= MAX_TOOL_CALLS:
            try:
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=session.get_history(),
                    tools=registry.get_schemas(),
                    tool_choice="none"
                )
                final_response = response.choices[0].message.content or "Done."
            except Exception:
                final_response = "I've completed the operations but couldn't generate a summary."

            session.add_message("assistant", final_response)

            # auto-clear after response — never during active delete/update flow
            if session.message_count > MAX_HISTORY_MESSAGES and session.state.mode == "idle":
                session.clear_history()
                session.add_system_prompt()

            return final_response


    return "Something went wrong — please try again"