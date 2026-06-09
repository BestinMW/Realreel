# Tests

Run the project-level unit tests from the `Realreel` directory:

```bash
python -m unittest discover tests
```

For friendlier output that explains each test and shows whether it passed or failed:

```bash
python run_tests.py
```

These tests cover URL parsing, OCR and vision indicator normalization, claim-analysis guardrails, and repost scoring/merge behavior without requiring network access, API keys, media files, or a live database.
