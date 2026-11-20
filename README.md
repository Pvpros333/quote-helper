# Quote Helper

A small Mac app to use alongside Jobber while you write quotes. It does two things:

1. **New estimate**: paste the assessment transcript and your job notes, add photos, and get a priced material list with live prices from local stores and online retailers. Every price links to where it was found.
2. **Check quote**: paste your finished Jobber quote (or attach the PDF) to see what the materials will really cost and how much profit is left after materials, labor and other costs. You can link it to a saved assessment so it reuses those notes, photos and prices.

Totals include waste %, a consumables allowance and your sales tax. You can change any quantity or price in the results, and the totals update right away. Jobs are saved on your Mac and can be exported to CSV or printed.

## Setup (one time)

1. Install Python 3 from <https://www.python.org/downloads/macos/> if you don't have it.
2. Get an Anthropic API key at <https://console.anthropic.com> (API Keys). Usage is billed per request, roughly $1–3 per estimate, mostly from the web searches and reading store pages.
3. Double-click **`Start Quote Helper.command`**. If macOS blocks it, right-click it and choose **Open**, then click **Open** again.
   The first launch takes about a minute to install. After that, your browser opens to the app.
4. Open **Settings**. Enter your API key, city/state/ZIP (used for local pricing), sales tax %, and preferred suppliers.

Leave the Terminal window open while you use the app. Close it (or press Ctrl+C) to quit.

## Tips

- The more measurements in the transcript or notes, the better the quantities.
- Check the **low confidence** lines first. Those prices couldn't be verified online and were estimated.
- An estimate takes 2–6 minutes while it searches and reads store pages. You can watch its progress on screen.

## Where your data lives

`~/Library/Application Support/QuoteHelper/` holds `settings.json` (including your API key) and `jobs/` (one JSON file per job plus its photos).
