from pathlib import Path
import shutil


FIXTURES = Path(__file__).parent / "fixtures"
SCHEMAS = Path(__file__).resolve().parents[2] / "assets" / "schemas"


def build_capture_vault(root: Path, claim_fixture: str = "valid-claim.md") -> list[str]:
    """Create raw/, wiki/{claims,sources,companies}, templates/schemas and return declared wiki paths."""
    raw_dir = root / "raw" / "annual-reports"
    claims_dir = root / "wiki" / "claims"
    sources_dir = root / "wiki" / "sources"
    companies_dir = root / "wiki" / "companies"
    schemas_dir = root / "templates" / "schemas"
    for directory in (raw_dir, claims_dir, sources_dir, companies_dir, schemas_dir):
        directory.mkdir(parents=True, exist_ok=True)

    for schema_name in ("claim.yaml", "source.yaml", "company.yaml"):
        shutil.copyfile(SCHEMAS / schema_name, schemas_dir / schema_name)

    (raw_dir / "acme-2025-annual-report.pdf").write_bytes(b"fixture-pdf")
    shutil.copyfile(
        FIXTURES / "example-annual-report.md",
        raw_dir / "acme-2025-annual-report.md",
    )
    shutil.copyfile(FIXTURES / claim_fixture, claims_dir / "claim-acme-revenue.md")
    shutil.copyfile(
        FIXTURES / "valid-source.md",
        sources_dir / "src-acme-2025-annual-report.md",
    )
    shutil.copyfile(FIXTURES / "valid-company.md", companies_dir / "company-acme.md")
    return [
        "wiki/claims/claim-acme-revenue.md",
        "wiki/sources/src-acme-2025-annual-report.md",
        "wiki/companies/company-acme.md",
    ]
