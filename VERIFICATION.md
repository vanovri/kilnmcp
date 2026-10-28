# Local verification

Verified on 28 October 2026 using Python from the existing KilnMCP virtual environment.

Command: `python -m pytest -q`.

Result: 15 tests passed in the exported source directory. Coverage includes core simulation, parser behaviour, mocked HTTP authentication headers, MCP stdio tools/resources/prompts, offline end-to-end reports, UART replay, streamable HTTP, and PDF generation.

No live model API, physical kiln, certification workflow or production data was used. Generated runtime data and reports are excluded from this source snapshot.
