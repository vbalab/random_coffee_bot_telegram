from keybert import KeyBERT  # type: ignore

from nespresso.recsys.searching.preprocessing.model import model

keyword_model = KeyBERT(model=model)


def ExtractKeywords(text: str) -> str:
    n_words = len(text.split())

    top_n: int = min(15, max(3, int(n_words / 5)))
    nr_candidates = top_n + 2

    result = keyword_model.extract_keywords(
        text,
        top_n=top_n,
        keyphrase_ngram_range=(1, 3),
        stop_words=None,
        use_maxsum=True,
        nr_candidates=nr_candidates,
    )

    keywords = ", ".join([kw for kw, _ in result])

    return keywords
