# Locale-specific scrapers

Place locale-specific scrapers in subfolders of this directory.

Each subfolder must include a `locale.json` file so the pipeline can decide when to run the scrapers inside.
Scrapers in the top-level `scrape/` directory still run every time.

## `locale.json` format

```json
{
  "country": "US",
  "province": "California",
  "county": "Santa Clara",
  "subdivisions": {
    "township": "Downtown"
  }
}
```

Notes:
- `country`, `province`, and `county` are expected for state/county level routing.
- `subdivisions` is optional and can include deeper admin divisions (e.g., township).
- Scrapers only run when at least one active subscriber matches the locale metadata.
