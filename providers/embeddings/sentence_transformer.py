DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class SentenceTransformerEmbedder:
    """Local, offline embedder — no network call, no API cost, unlike
    the LLM providers. The model loads lazily on first `.embed()` so
    importing/constructing this class doesn't pay the load cost (or
    require the optional `sentence-transformers` dependency) until
    semantic recall is actually exercised."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed(self, text: str) -> tuple[float, ...]:
        model = self._load()
        vector = model.encode(text, normalize_embeddings=True)
        return tuple(float(x) for x in vector)
