"""Disposable Office parser process, called only with a server-built request file."""

import json
import sys
from pathlib import Path


def main() -> None:
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (request["memory_bytes"], request["memory_bytes"]))
    from app.ingestion.parsing.base import ParserError
    from app.ingestion.parsing.office import OfficeParser

    parser = OfficeParser(
        max_rows=request["max_rows"],
        max_columns=request["max_columns"],
        row_group_size=request["row_group_size"],
    )
    result: dict[str, object]
    try:
        document = parser._parse_document(
            Path(request["source"]).read_bytes(),
            filename=request["filename"],
            mime_type=request["mime_type"],
        )
        result = {"document": document.model_dump(mode="json")}
    except ParserError as error:
        result = {"error": error.code}
    Path(request["output"]).write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
