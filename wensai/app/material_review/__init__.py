"""Task B: local parsing, deterministic checks and versioned evaluation contracts."""
from .catalog import list_profiles, load_knowledge, load_profile, validate_catalog, validate_document, validate_review_output
from .fixes import fix_docx as _fix_docx
from .model import MaterialError
from .parse import parse_document
from .rules import run_checks

__all__ = ["MaterialError", "build_review_input", "check_document", "fix_docx", "list_profiles", "load_knowledge", "load_profile",
           "parse_document", "validate_catalog", "validate_document", "validate_review_output"]


def check_document(document, profile_id, *, rendered_page_count=None):
    return run_checks(document, load_profile(profile_id), rendered_page_count=rendered_page_count)


def build_review_input(path, profile_id, *, encoding=None, rendered_page_count=None):
    """Assemble task C's inputs without running an Agent or persisting any result."""
    profile = load_profile(profile_id)
    document = parse_document(path, encoding=encoding)
    validate_document(document)
    return {"schema_version": "1.0", "document": document.to_dict(), "profile": profile,
            "format_report": run_checks(document, profile, rendered_page_count=rendered_page_count),
            "knowledge": load_knowledge(profile["knowledge_refs"])}


def fix_docx(path, destination, profile_id, *, selected_rule_ids=None):
    """Apply selected known rule fixes to a caller-chosen new DOCX path."""
    return _fix_docx(path, destination, load_profile(profile_id), selected_rule_ids=selected_rule_ids)
