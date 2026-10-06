"""Run the desk pipeline and print measured counts."""

import sys

from app.db import get_session_factory
from app.pipeline import run_pipeline


def main() -> None:
    session = get_session_factory()()
    try:
        report = run_pipeline(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    print(report.format(), flush=True)
    if report.feed_errors:
        print("\nFeed errors:", file=sys.stderr)
        for error in report.feed_errors:
            print(error, file=sys.stderr)
    if report.model_skipped_reason:
        print(report.model_skipped_reason, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        sys.exit(1)
