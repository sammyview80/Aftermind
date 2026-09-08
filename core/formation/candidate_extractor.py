from domain.models.candidate import Candidate
from domain.models.experience import Experience

# Content that carries no durable information — acknowledgements,
# filler — even though it's a perfectly normal turn in a conversation.
_TRIVIAL_PHRASES = {
    "ok",
    "okay",
    "ok thanks",
    "okay thanks",
    "thanks",
    "thank you",
    "got it",
    "sure",
    "sounds good",
    "no problem",
    "alright",
    "cool",
}


def _is_trivial(text: str) -> bool:
    normalized = text.strip().lower().rstrip(".!")
    return not normalized or normalized in _TRIVIAL_PHRASES


class CandidateExtractor:
    """Pulls candidate memories out of an Experience.

    This stage only asks "is there any durable content here at all?" — it
    filters out pure noise (acknowledgements, empty turns) but does not
    score or judge worth beyond that. Scoring is the evaluator's job.
    """

    def extract(self, experience: Experience) -> list[Candidate]:
        text = (experience.output or experience.input or "").strip()
        if _is_trivial(text):
            return []

        return [
            Candidate(
                experience_id=experience.experience_id,
                scope=experience.scope,
                content=text,
                source_event_ids=tuple(event.event_id for event in experience.events),
            )
        ]
