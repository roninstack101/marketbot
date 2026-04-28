"""
Code generation, debugging, and explanation tools.
All tools call the LLM to produce or analyse source code.
"""
import json

import structlog

from app.agent.llm_client import call_llm, call_llm_json

log = structlog.get_logger(__name__)

_WRITE_CODE_SYSTEM = """\
You are an expert software engineer. Write clean, well-structured, production-quality code.

Return a JSON object with these fields:
{
  "language": "<programming language used>",
  "filename": "<suggested filename with extension>",
  "code": "<the complete source code>",
  "explanation": "<brief explanation of how the code works>",
  "usage_example": "<short example showing how to use or run the code>"
}

Rules:
- Write complete, working code – never use placeholder comments like '# TODO'.
- Follow idiomatic conventions for the language (PEP 8 for Python, etc.).
- Include only imports/dependencies that are actually needed.
- Do NOT wrap the JSON in markdown fences.
"""

_DEBUG_CODE_SYSTEM = """\
You are an expert debugger. Analyse the code and error, find the root cause, and return a fixed version.

Return a JSON object:
{
  "root_cause": "<concise explanation of the bug>",
  "fixed_code": "<the complete corrected source code>",
  "changes_made": ["<list of specific changes>"],
  "explanation": "<why the fix works>"
}

Do NOT wrap the JSON in markdown fences.
"""

_EXPLAIN_CODE_SYSTEM = """\
You are a skilled technical educator. Explain code clearly for the stated audience.

Return a JSON object:
{
  "summary": "<one-sentence summary of what the code does>",
  "detailed_explanation": "<step-by-step explanation of how it works>",
  "key_concepts": ["<important concepts or patterns used>"],
  "potential_issues": ["<any bugs, edge cases, or improvements worth noting>"],
  "complexity": "<time/space complexity if applicable>"
}

Do NOT wrap the JSON in markdown fences.
"""


async def write_code(
    language: str,
    task: str,
    context: str = "",
    style_notes: str = "",
) -> str:
    """
    Generate source code for a given task in any programming language.

    Args:
        language:    Target language (python, javascript, typescript, go, rust, …).
        task:        Description of what the code should do.
        context:     Additional project or environment context.
        style_notes: Coding style preferences (e.g. "use async/await", "no classes").

    Returns:
        JSON string with filename, code, explanation, and usage example.
    """
    log.info("write_code", language=language, task=task[:80])

    human = f"""\
Language: {language}
Task: {task}
Context: {context or 'None'}
Style notes: {style_notes or 'None'}

Write the code now.
"""
    result = await call_llm_json(
        [
            {"role": "system", "content": _WRITE_CODE_SYSTEM},
            {"role": "user", "content": human},
        ],
        temperature=0.2,
    )
    log.info("code_written", filename=result.get("filename", ""))
    return json.dumps(result, indent=2)


async def debug_code(
    code: str,
    language: str,
    error_message: str = "",
    context: str = "",
) -> str:
    """
    Debug and fix broken or buggy source code.

    Args:
        code:          The source code to debug.
        language:      Programming language of the code.
        error_message: Error message or stack trace (if available).
        context:       Additional context about what the code should do.

    Returns:
        JSON string with root cause, fixed code, and explanation.
    """
    log.info("debug_code", language=language, has_error=bool(error_message))

    human = f"""\
Language: {language}
Error message: {error_message or 'No error message provided – analyse for bugs.'}
Context: {context or 'None'}

Code to debug:
```{language}
{code}
```

Find the bug and return the fix.
"""
    result = await call_llm_json(
        [
            {"role": "system", "content": _DEBUG_CODE_SYSTEM},
            {"role": "user", "content": human},
        ],
        temperature=0.1,
    )
    log.info("code_debugged", changes=len(result.get("changes_made", [])))
    return json.dumps(result, indent=2)


async def explain_code(
    code: str,
    language: str = "",
    audience: str = "developer",
) -> str:
    """
    Explain what a piece of code does in plain language.

    Args:
        code:     The source code to explain.
        language: Programming language (auto-detected if empty).
        audience: Target audience – 'developer', 'beginner', or 'non-technical'.

    Returns:
        JSON string with summary, detailed explanation, and key concepts.
    """
    log.info("explain_code", audience=audience)

    human = f"""\
Language: {language or 'auto-detect'}
Audience: {audience}

Code:
```
{code}
```

Explain this code now.
"""
    result = await call_llm_json(
        [
            {"role": "system", "content": _EXPLAIN_CODE_SYSTEM},
            {"role": "user", "content": human},
        ],
        temperature=0.3,
    )
    log.info("code_explained", summary=result.get("summary", "")[:80])
    return json.dumps(result, indent=2)
