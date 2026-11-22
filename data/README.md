# Historical draw data

Upload two files into this folder using **Add file → Upload files**:

- `loto6.csv` (2,156 historical draws, through round 2156)
- `loto7.csv` (704 historical draws, through round 704)

These contain only public lottery result dates and numbers. A scheduled GitHub Actions workflow imports them to Cloudflare D1 without resetting search progress. Avoid uploading the original datasets with additional financial columns or any credentials. Never commit API keys.
