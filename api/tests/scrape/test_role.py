"""Role and industry keywords. A hint wins when it matches."""

import pytest
from jobhunt.scrape.normalize.role import infer_industry, infer_role


@pytest.mark.parametrize(
    ("title", "hint", "expected"),
    [
        ("Senior Frontend Engineer", None, "frontend"),
        ("Engineer", "Frontend", "frontend"),
        ("Staff Backend Engineer", None, "backend"),
        ("Full Stack Engineer", None, "fullstack"),
        ("ML Engineer", None, "ml"),
        ("Engineering Manager", None, "engineering_manager"),
        ("Platform Engineer", None, "platform_engineer"),
        ("Engineer", None, "software"),
        ("Senior Engineer", None, "software"),
        ("Technical Support Engineer", None, None),
        ("Generalist", None, "other"),
        ("Software Engineer", None, "software"),
        ("Java Engineer", None, "software"),
        ("Software Development Engineer", None, "software"),
        ("Product Engineer", None, "product_engineer"),
        ("Growth Engineer", None, "growth_engineer"),
        ("Web Engineer", None, "web_engineer"),
        ("Web Developer", None, "web_engineer"),
        ("Senior Web Developer (React)", None, "frontend"),
        ("Full Stack .NET Web Engineer", None, "fullstack"),
        ("Fullstack Web Developer", None, "fullstack"),
        ("Forward Deployed Engineer", None, "forward_deployed"),
        ("Data Platform Engineer", None, "data"),
        ("Android Platform Engineer", None, "mobile"),
        ("Security Platform Engineer", None, "security"),
        ("ML Platform Engineer", None, "ml"),
        ("AI Engineer", None, "ml"),
        ("Computer Vision Engineer", None, "ml"),
        ("Research Engineer", None, "ml"),
        ("AI-augmented Engineer", None, "ml"),
        ("LLM Engineer", None, "ml"),
    ],
)
def test_infer_role(title: str, hint: str | None, expected: str | None) -> None:
    assert infer_role(title, hint) == expected


@pytest.mark.parametrize(
    ("hint", "company", "expected"),
    [
        ("Financial Services", "Acme", "fintech"),
        (None, "Northwind Payments", "fintech"),
        ("Healthcare", "Acme", "health"),
        (None, "Acme", None),
    ],
)
def test_infer_industry(hint: str | None, company: str, expected: str | None) -> None:
    assert infer_industry(hint, company) == expected
