"""
General-purpose Q&A tool.
Handles simple questions, explanations, and conversational replies
without spinning up a full multi-step agent plan.
"""
import structlog

from app.agent.llm_client import call_llm

log = structlog.get_logger(__name__)

_QA_SYSTEM = """\
You are a knowledgeable, helpful assistant. Answer the user's question clearly and concisely.

Guidelines:
- For factual questions: give a direct, accurate answer.
- For explanations: be clear, use examples where helpful.
- For opinions or advice: be balanced and practical.
- Keep answers focused — don't pad with unnecessary caveats.
- Use markdown formatting (bold, bullets, code blocks) when it improves readability.
"""


async def write_answer(
    question: str,
    context: str = "",
    brand_name: str = "",
) -> str:
    """
    Answer a general question or conversational prompt directly with the LLM.
    No research or multi-step planning — just a clean, direct response.

    Args:
        question:   The user's question or prompt.
        context:    Optional extra context (e.g. previous conversation turns).
        brand_name: If set, answers in the context of that brand's knowledge/voice.

    Returns:
        The answer as a plain string.
    """
    log.info("write_answer", question=question[:80], brand=brand_name or "none")

    brand_block = ""
    if brand_name:
        from app.brand.store import get_brand_voice_prompt
        brand_block = await get_brand_voice_prompt(brand_name)

    system = (brand_block + "\n\n" + _QA_SYSTEM) if brand_block else _QA_SYSTEM

    human = question
    if context:
        human = f"Context:\n{context}\n\nQuestion:\n{question}"

    return await call_llm(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": human},
        ],
        temperature=0.4,
    )
