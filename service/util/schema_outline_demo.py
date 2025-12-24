import os, sys

_HERE = os.path.dirname(__file__)
_SERVICE_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)

from util.schema_outline import compact_outline_from_model, compact_outline_from_schema
from models import (
    ClaimProcessingResult,
    ArticleEnrichment,
    ModelResponseOutput,
    FactCheckResponseOutput,
    SilverUpdate,
    SilverFollowup,
)


def show(name: str, model) -> None:
    print("=" * 80)
    print(name)
    print("-" * 80)
    try:
        outline = compact_outline_from_model(model)
    except Exception as e:
        outline = f"<error: {e}>"
    print(outline)
    print()


def main():
    show("ClaimProcessingResult", ClaimProcessingResult)
    show("ArticleEnrichment", ArticleEnrichment)
    show("ModelResponseOutput", ModelResponseOutput)
    show("FactCheckResponseOutput", FactCheckResponseOutput)
    show("SilverUpdate", SilverUpdate)
    show("SilverFollowup", SilverFollowup)

    # Also demonstrate a small ad-hoc JSON schema
    sample_schema = {
        "title": "Sample",
        "type": "object",
        "required": ["id", "status"],
        "properties": {
            "id": {"type": "string"},
            "status": {"enum": ["new", "processing", "done"]},
            "tags": {"type": "array", "items": {"type": "string"}},
            "created_at": {"type": "string", "format": "date-time"},
        },
        "$defs": {
            "Nested": {
                "type": "object",
                "properties": {"k": {"type": "string"}, "v": {"type": "integer"}},
                "required": ["k"]
            }
        }
    }
    print("=" * 80)
    print("Ad-hoc JSON schema (Sample)")
    print("-" * 80)
    print(compact_outline_from_schema(sample_schema))


if __name__ == "__main__":
    main()
