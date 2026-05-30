"""apii — Arabic/GCC PII gateway."""

from apii.pipeline import Pipeline
from apii.types import Detection, EntityKind


def default_pipeline(enable_ner: bool = True) -> Pipeline:
    """Pipeline wired with the structured recognizers + (by default) NER.

    PERSON and ORGANIZATION are NER-only. With `enable_ner` True the ONNX
    engines load if available, else NER silently stays off and the
    pipeline is pure regex. `enable_ner=False` forces the regex-only layer.
    """
    from apii.recognizers import DEFAULT_RECOGNIZERS

    ner_engines: tuple = ()
    if enable_ner:
        from apii.ner import shared_engines

        ner_engines = tuple(shared_engines())
    return Pipeline(DEFAULT_RECOGNIZERS, ner_engines=ner_engines)


__all__ = ["Pipeline", "Detection", "EntityKind", "default_pipeline"]
__version__ = "0.1.0"
